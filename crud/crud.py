from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_mysqldb import MySQL
import os, logging, io, wave, base64, threading
from werkzeug.middleware.proxy_fix import ProxyFix
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish

logging.basicConfig(format='%(asctime)s - WEB - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "clave_por_defecto")

# Conexión a MariaDB
app.config["MYSQL_USER"] = os.environ.get("MARIADB_USER", "root")
app.config["MYSQL_PASSWORD"] = os.environ.get("MARIADB_USER_PASS", "hola")
app.config["MYSQL_DB"] = os.environ.get("MARIADB_DB_AUDIO", "monitoreo_acustico")
app.config["MYSQL_HOST"] = os.environ.get("MARIADB_SERVER", "mariadb")
mysql = MySQL(app)

ULTIMO_AUDIO_RAM = {
    "pcm_bytes": None,
    "timestamp": None
}

def enviar_comando_mqtt(payload):
    try:
        topico = os.environ.get("TOPICO_ESTADO", "id_prueba/estado")
        host_mqtt = "mosquitto" 
        puerto_mqtt = 1883
        usr = os.environ.get("MQTT_USR", "root")
        pwd = os.environ.get("MQTT_PASS", "hola")
        
        logging.info(f"Enviando comando MQTT -> Tópico: [{topico}] | Payload: [{payload}]")
        auth = {'username': usr, 'password': pwd} if usr else None
        
        publish.single(
            topic=topico, 
            payload=payload,
            hostname=host_mqtt, 
            port=puerto_mqtt,
            auth=auth, 
            qos=1
        )
        return True
    except Exception as e:
        logging.error(f"Error enviando por MQTT: {str(e)}")
        return False

# Hilo en segundo plano para escuchar los audios (notar que es porque uso paho-mqtt, no asíncrona)
def on_mqtt_message(client, userdata, msg):
    try:
        topico_alerta = os.environ.get("TOPICO_ALERTA", "id_prueba/audio")
        if msg.topic == topico_alerta:
            logging.info("Audio recibido por MQTT en Flask. Reteniendo en RAM...")
            # Decodifico el Base64 de la Pico y lo meto en RAM
            pcm_crudo = base64.b64decode(msg.payload)
            from datetime import datetime
            
            ULTIMO_AUDIO_RAM["pcm_bytes"] = pcm_crudo
            ULTIMO_AUDIO_RAM["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logging.error(f"Error procesando audio: {str(e)}")

def iniciar_escucha_mqtt():
    try:
        client = mqtt.Client()
        usr = os.environ.get("MQTT_USR", "root")
        pwd = os.environ.get("MQTT_PASS", "hola")
        if usr:
            client.username_pw_set(usr, pwd)
            
        client.on_message = on_mqtt_message
        client.connect("mosquitto", 1883, 60)
        
        topico_alerta = os.environ.get("TOPICO_ALERTA", "id_prueba/audio")
        client.subscribe(topico_alerta)
        logging.info(f"Servicio Web suscripto a audios en: {topico_alerta}")
        client.loop_forever()
    except Exception as e:
        logging.error(f"Error en hilo de escucha MQTT: {str(e)}")

# Inicio el receptor de audio en un hilo aparte al arrancar Flask
hilo_mqtt = threading.Thread(target=iniciar_escucha_mqtt, daemon=True)
hilo_mqtt.start()

# Rutas principales
@app.route('/')
def index():
    lista_audios = []
    ultimo_registro_db = None
    try:
        cur = mysql.connection.cursor()
        tabla = os.environ.get("MARIADB_TABLE_AUDIO", "historial_llanto")
        
        # Leo los últimos 25 registros de la b.d.d
        cur.execute(f"SELECT timestamp, probabilidad, es_llanto, origen, duracion_seg FROM `{tabla}` ORDER BY timestamp DESC LIMIT 25")
        columnas = [col[0] for col in cur.description]
        lista_audios = [dict(zip(columnas, row)) for row in cur.fetchall()]
        
        if lista_audios:
            ultimo_registro_db = lista_audios[0]
            
        cur.close()
    except Exception as e:
        logging.error(f"Error MySQL: {str(e)}")
        flash("Error de conexión al leer la base de datos estadística")
        
    return render_template(
        'index.html', 
        lista_audios=lista_audios, 
        ultimo=ultimo_registro_db, 
        audio_disponible=ULTIMO_AUDIO_RAM["pcm_bytes"] is not None,
        topico=os.environ.get("TOPICO_ESTADO", "id_prueba/estado")
    )

@app.route('/control', methods=['POST'])
def control():
    accion = request.form.get('accion')
    payload = "ON" if accion == "ENCENDER" else "OFF"
        
    if enviar_comando_mqtt(payload):
        flash(f"Estado '{payload}' enviado a la placa de desarrollo")
    else:
        flash("Error: No se pudo contactar con el broker Mosquitto")
            
    return redirect(url_for('index'))

@app.route('/audio/en_vivo')
def reproducir_audio_ram():
    # Buffer a wav para reproducir en el navegador
    if ULTIMO_AUDIO_RAM["pcm_bytes"] is None:
        return "No hay capturas de audio recientes en memoria", 404
        
    try:
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)       # 1 canal (Mono)
            wav_file.setsampwidth(1)       # 1 byte = 8 bits PCM
            wav_file.setframerate(8000)    # 8000 Hz
            wav_file.writeframes(ULTIMO_AUDIO_RAM["pcm_bytes"])
            
        wav_buffer.seek(0)
        return send_file(
            wav_buffer, 
            mimetype='audio/wav', 
            as_attachment=False, 
            download_name='alerta_llanto.wav'
        )
    except Exception as e:
        logging.error(f"Error generando WAV {str(e)}")
        return "Error interno al procesar el audio", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)