import os
import ssl
import base64
import asyncio
import logging

import numpy as np
import librosa
import tensorflow as tf
from scipy.signal import resample

import aiomqtt
import aiomysql

logging.basicConfig(
    format="%(asctime)s - ClienteMqttIA - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- VARIABLES DE ENTORNO ---
BROKER = os.environ["SERVIDOR"]
PORT = int(os.environ["PUERTO_MQTTS"])
MQTT_USER = os.environ["MQTT_USR"]
MQTT_PASS = os.environ["MQTT_PASS"]

TOPICO_ENTRADA = os.environ["TOPICO"]
TOPICO_ALERTA = os.environ["TOPICO_ALERTA"]
TOPICO_MODO = os.environ["TOPICO_MODO"]

# Credenciales de MariaDB
DB_HOST = os.environ["MARIADB_SERVER"]
DB_PORT = int(os.environ.get("MARIADB_PORT", 3306))
DB_USER = os.environ["MARIADB_USER"]
DB_PASS = os.environ["MARIADB_USER_PASS"]
DB_NAME = os.environ["MARIADB_DB_AUDIO"]
DB_TABLE = os.environ["MARIADB_TABLE_AUDIO"]

MODEL_PATH = os.environ.get("MODELO_PATH", "detector_llanto.keras")

# --- PARÁMETROS DEL AUDIO E INFERENCIA ---
SR = 16000
DURATION = 3.0
TARGET_LEN = int(SR * DURATION)
N_MFCC = 40
MAX_LEN = int(SR * DURATION / 512) + 1

# Variable en RAM para trackear el modo actual
modo_actual = "auto"

logging.info(f"Cargando modelo de red neuronal desde '{MODEL_PATH}'...")
modelo = tf.keras.models.load_model(MODEL_PATH)
logging.info("Modelo cargado exitosamente en RAM.")

db_pool: aiomysql.Pool = None

# --- TU FUNCIÓN DE IA INTACTA ---
def detectar_llanto(audio_bytes):
    audio = np.frombuffer(audio_bytes, dtype=np.uint8).astype(np.float32)
    audio = (audio - 128.0) / 128.0
    audio = resample(audio, TARGET_LEN)

    mfcc = librosa.feature.mfcc(
        y=audio,
        sr=SR,
        n_mfcc=N_MFCC
    )
    mfcc = (mfcc - np.mean(mfcc)) / (np.std(mfcc) + 1e-8)

    if mfcc.shape[1] < MAX_LEN:
        pad = MAX_LEN - mfcc.shape[1]
        mfcc = np.pad(mfcc, ((0,0),(0,pad)), mode="constant")
    else:
        mfcc = mfcc[:, :MAX_LEN]

    mfcc = mfcc.reshape(1, N_MFCC, MAX_LEN, 1)
    prob = modelo.predict(mfcc, verbose=0)[0][0]
    return float(prob)

# --- FUNCIÓN DE GUARDADO EN MARIADB ---
async def guardar_en_bd(probabilidad: float, es_llanto: bool, origen: str, duracion: float = 3.0):
    if not db_pool:
        logging.warning("No hay pool de BD activo. Omitiendo registro en MariaDB.")
        return

    query = f"""
        INSERT INTO {DB_TABLE} (probabilidad, es_llanto, origen, duracion_seg)
        VALUES (%s, %s, %s, %s)
    """
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (probabilidad, int(es_llanto), origen, duracion))
                await conn.commit()
        logging.info(f"[MARIADB] Guardado -> Prob: {probabilidad*100:.1f}% | ¿Llanto?: {es_llanto} | Origen: '{origen}'")
    except Exception as e:
        logging.error(f"[MARIADB ERROR] Falló la inserción SQL: {e}")

# --- BUCLE ASÍNCRONO DE ESCUCHA MQTT ---
async def escuchar_y_procesar():
    global db_pool, modo_actual
    
    logging.info(f"Conectando a MariaDB en host '{DB_HOST}', base de datos '{DB_NAME}'...")
    db_pool = await aiomysql.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        autocommit=True
    )
    logging.info("Pool de conexiones con MariaDB operativo.")

    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()

    logging.info(f"Conectando al broker MQTT MQTTS -> {BROKER}:{PORT}...")
    async with aiomqtt.Client(
        hostname=BROKER,
        port=PORT,
        username=MQTT_USER,
        password=MQTT_PASS,
        tls_context=tls_context
    ) as client:
        logging.info("Conectado al broker MQTT exitosamente.")
        
        # Suscribimos al audio y al canal de modo del .env
        await client.subscribe(TOPICO_ENTRADA)
        await client.subscribe(TOPICO_MODO)
        logging.info(f"Suscripto a canales:\n - Audios: {TOPICO_ENTRADA}\n - Control de modo: {TOPICO_MODO}")

        async for message in client.messages:
            try:
                topico_recibido = message.topic.value
                payload = message.payload

                # 1. SI LLEGA EL STRING PLANO DESDE TELEGRAM O LA PICO EN id_prueba/modo
                if topico_recibido == TOPICO_MODO:
                    modo_recibido = payload.decode(errors="ignore").strip().lower()
                    if modo_recibido in ["manual", "auto"]:
                        modo_actual = modo_recibido
                        logging.info(f"🔄 [MODO ACTUALIZADO] El sistema cambió a -> '{modo_actual}'")
                    continue

                # 2. SI LLEGA EL BUFFER DE AUDIO EN id_prueba/audio
                if topico_recibido == TOPICO_ENTRADA:
                    logging.info(f"\n--- [AUDIO RECIBIDO en {topico_recibido} | Origen: '{modo_actual}'] ---")
                    audio_raw = base64.b64decode(payload)

                    logging.info("Procesando audio y ejecutando inferencia neuronal...")
                    probabilidad = await asyncio.to_thread(detectar_llanto, audio_raw)
                    
                    es_llanto = probabilidad >= 0.5
                    logging.info(f"Resultado -> Probabilidad: {probabilidad*100:.2f}% | ¿Es llanto?: {es_llanto}")

                    await guardar_en_bd(probabilidad, es_llanto, origen=modo_actual, duracion=DURATION)

                    if es_llanto:
                        logging.info(f"🚨 Confirmado por IA. Publicando alerta hacia Telegram en -> {TOPICO_ALERTA}")
                        await client.publish(TOPICO_ALERTA, payload=payload, qos=1)
                    else:
                        logging.info("🔇 El sonido no fue clasificado como llanto. Descartando alerta a Telegram.")

            except Exception as e:
                logging.exception(f"Error procesando mensaje entrante: {e}")

async def main():
    while True:
        try:
            await escuchar_y_procesar()
        except Exception as e:
            logging.exception(f"Desconexión imprevista: {e}. Reintentando reconexión en 5 segundos...")
            await asyncio.sleep(5)
        finally:
            if db_pool:
                db_pool.close()
                await db_pool.wait_closed()
                logging.info("Pool de MariaDB cerrado limpiamente.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Servicio clienteMqtt detenido por el usuario.")