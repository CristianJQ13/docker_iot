import os
import ssl
import base64
import wave
import asyncio
import logging
from io import BytesIO

import aiomqtt
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - TelegramBot - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.environ["TB_TOKEN"]
CHAT_ID = int(os.environ["TB_CHAT_ID"])

BROKER = os.environ["SERVIDOR"]
PORT = int(os.environ["PUERTO_MQTTS"])
TOPICO_ALERTA = os.environ["TOPICO_ALERTA"]
TOPICO_ESTADO = os.environ["TOPICO_ESTADO"]  

BASE_TOPIC = TOPICO_ESTADO.rsplit("/", 1)[0]
TOPICO_MODO = f"{BASE_TOPIC}/modo"
TOPICO_UMBRAL = f"{BASE_TOPIC}/umbral"

MQTT_USER = os.environ.get("MQTT_USR", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")

mqtt_client: aiomqtt.Client = None

# Para evitar que el bot repita en el chat un cambio que yo pedi desde Telegram
cambio_solicitado_por_telegram = False

# Teclado inferior con botones
def teclado_persistente():
    return ReplyKeyboardMarkup(
        [["🟢 Encender", "🔴 Apagar"]],
        resize_keyboard=True,
        is_persistent=True
    )

# Handlers de comandos
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    # Para actualizar cuando no se le da la gana de hacerlo solo
    await update.message.reply_text(
        "Limpiando caché de teclados anteriores...",
        reply_markup=ReplyKeyboardRemove()
    )
    await asyncio.sleep(0.5)
    
    await update.message.reply_text(
        "**Panel de control**\n\n"
        "Comandos disponibles para configuración:\n"
        "• `/modo auto` -> Solo detección nocturna por micrófono\n"
        "• `/modo manual` -> Solo disparo por pulsador físico\n"
        "• `/umbral <10-100>` -> Ajusta la sensibilidad del micrófono\n\n"
        "El teclado de encendido/apagado está fijado en la barra inferior",
        reply_markup=teclado_persistente(),
        parse_mode="Markdown"
    )
    logging.info("Teclado y menú actualizados mediante /start")

# Función para cambio de modo
async def cmd_modo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    
    if not mqtt_client:
        await update.message.reply_text("**Error:** El bot no está conectado al broker MQTT.", parse_mode="Markdown")
        return

    if not context.args:
        await update.message.reply_text(
            "**Configuración de Modo**\n\n"
            "Indicar qué modo deseas activar. Ejemplo: `/modo auto`\n\n"
            "**Opciones disponibles:**\n"
            "• `manual` -> Disparo exclusivo por botón pulsador.\n"
            "• `auto` -> Disparo exclusivo por detección de ruido/llanto.\n",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        return

    modo_elegido = context.args[0].lower().strip()
    
    if modo_elegido not in ["manual", "auto", "ambos"]:
        await update.message.reply_text(
            "**Modo inválido.** Elige entre: `manual`, `auto`.",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        return

    # Publico con retain=True para que la Raspi lo recuerde si se reinicia
    await mqtt_client.publish(TOPICO_MODO, payload=modo_elegido, qos=1, retain=True)
    
    iconos = {"manual": "🔘", "auto": "🌙", "ambos": " "}
    await update.message.reply_text(
        f"{iconos[modo_elegido]} Modo configurado en: **{modo_elegido.upper()}**\n"
        f"Memoria actualizada.",
        parse_mode="Markdown",
        reply_markup=teclado_persistente()
    )
    logging.info(f"[TELEGRAM -> MQTT] Modo cambiado a {modo_elegido}")

# Función para elegir el umbral de sensibilidad
async def cmd_umbral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    
    if not mqtt_client:
        await update.message.reply_text("**Error:** El bot no está conectado al broker MQTT actualmente.", parse_mode="Markdown")
        return

    if not context.args:
        await update.message.reply_text(
            "**Selección de Sensibilidad**\n\n"
            "Indicar número entre **10** y **100**. Ejemplo: `/umbral 45`\n\n"
            "• **10-30%:** Muy sensible.\n"
            "• **40-60%:** Intermedio.\n"
            "• **70-100%:** Poco sensible.",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        return

    try:
        valor_umbral = int(context.args[0].strip())
        if valor_umbral < 10 or valor_umbral > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "**Valor inválido.** Ingresa un número entero entre **10** y **100**.",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        return

    await mqtt_client.publish(TOPICO_UMBRAL, payload=str(valor_umbral), qos=1, retain=True)
    
    await update.message.reply_text(
        f"Umbral ajustado a **{valor_umbral}%**\n"
        f"El micrófono ahora disparará alertas cuando el sonido supere este nivel de forma sostenida.",
        parse_mode="Markdown",
        reply_markup=teclado_persistente()
    )
    logging.info(f"[TELEGRAM -> MQTT] Umbral cambiado a {valor_umbral}%")

# Procesado de los botones permanentes
async def texto_teclado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global cambio_solicitado_por_telegram
    if update.effective_chat.id != CHAT_ID or not mqtt_client:
        return
    
    texto = update.message.text
    if "Encender" in texto:
        cambio_solicitado_por_telegram = True
        await mqtt_client.publish(TOPICO_ESTADO, payload="ON", qos=1, retain=True)
        await update.message.reply_text(
            "🟢 Sistema **ENCENDIDO** (`ON`) desde Telegram.",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        logging.info("[TELEGRAM -> MQTT] Estado cambiado a ON")
    elif "Apagar" in texto:
        cambio_solicitado_por_telegram = True
        await mqtt_client.publish(TOPICO_ESTADO, payload="OFF", qos=1, retain=True)
        await update.message.reply_text(
            "🔴 Sistema **APAGADO** (`OFF`) desde Telegram.",
            parse_mode="Markdown",
            reply_markup=teclado_persistente()
        )
        logging.info("[TELEGRAM -> MQTT] Estado cambiado a OFF")

# Funciones de audio y notificación
async def enviar_audio(bot, audio_bytes):
    logging.info("Generando archivo WAV en memoria RAM...")
    wav_buffer = BytesIO()

    with wave.open(wav_buffer, "wb") as wav:
        wav.setnchannels(1)      # Mono
        wav.setsampwidth(1)      # 8 bits
        wav.setframerate(8000)   # 8000 Hz
        wav.writeframes(audio_bytes)

    wav_buffer.seek(0)
    wav_buffer.name = "alerta_llanto.wav"

    logging.info("Enviando audio a Telegram...")
    
    await bot.send_audio(
        chat_id=CHAT_ID,
        audio=wav_buffer,
        caption="¡ATENCIÓN! Se detectó llanto/ruido en la habitación.",
        title="Audio grabado",
        performer="Raspberry Pi Pico W",
        reply_markup=teclado_persistente()
    )
    logging.info("Audio enviado correctamente.")

async def procesar_cambio_estado(bot, payload_str):
    # Notifico en el chat cuando el estado físico de la Raspi cambia
    global cambio_solicitado_por_telegram
    
    if cambio_solicitado_por_telegram:
        cambio_solicitado_por_telegram = False
        return

    estado_upper = payload_str.upper()
    if estado_upper in ["ON", "1", "TRUE"]:
        texto = "**¡Atención!**\nEl sistema fue **ENCENDIDO físicamente** desde la Raspberry Pi."
    elif estado_upper in ["OFF", "0", "FALSE"]:
        texto = "**¡Atención!**\nEl sistema fue **APAGADO físicamente** desde la Raspberry Pi."
    else:
        return

    logging.info(f"[MQTT -> TELEGRAM] Cambio físico detectado: {estado_upper}")
    await bot.send_message(
        chat_id=CHAT_ID,
        text=texto,
        parse_mode="Markdown",
        reply_markup=teclado_persistente()
    )

# Bucle de escucha MQTT
async def escuchar_mqtt(bot):
    global mqtt_client
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()

    logging.info("Conectando al broker MQTT...")

    async with aiomqtt.Client(
        hostname=BROKER,
        port=PORT,
        username=MQTT_USER,
        password=MQTT_PASS,
        tls_context=tls_context,
    ) as client:
        mqtt_client = client
        logging.info("Conectado.")
        
        await client.subscribe(TOPICO_ALERTA)
        await client.subscribe(TOPICO_ESTADO)
        logging.info(f"Suscripto a canales:\n - {TOPICO_ALERTA}\n - {TOPICO_ESTADO}")

        async for message in client.messages:
            try:
                topico_recibido = message.topic.value
                payload = message.payload
                
                if topico_recibido == TOPICO_ALERTA:
                    logging.info("¡Alerta de audio recibida!")
                    audio_bytes = base64.b64decode(payload)
                    await enviar_audio(bot, audio_bytes)
                elif topico_recibido == TOPICO_ESTADO:
                    estado_str = payload.decode().strip()
                    await procesar_cambio_estado(bot, estado_str)
                    
            except Exception as e:
                logging.exception(e)

# Bucle principal asíncrono
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Registro los comandos
    app.add_handler(CommandHandler(["start", "menu", "reset", "estado"], cmd_start))
    app.add_handler(CommandHandler("modo", cmd_modo))
    app.add_handler(CommandHandler("umbral", cmd_umbral))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_teclado))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logging.info("Bot de Telegram iniciado en segundo plano...")

    while True:
        try:
            await escuchar_mqtt(app.bot)
        except Exception as e:
            mqtt_client = None
            logging.exception(e)
            logging.info("Reconectando MQTT en 5 segundos...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Programa detenido por el usuario.")