from flask import Flask, render_template, request, redirect, url_for, flash
from flask_mysqldb import MySQL
import os, logging, ssl
from werkzeug.middleware.proxy_fix import ProxyFix
import paho.mqtt.client as mqtt

logging.basicConfig(format='%(asctime)s - CRUD - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "clave_por_defecto")

app.config["MYSQL_USER"] = os.environ.get("MYSQL_USER", "root")
app.config["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
app.config["MYSQL_DB"] = os.environ.get("MYSQL_DB", "test")
app.config["MYSQL_HOST"] = os.environ.get("MYSQL_HOST", "localhost")
mysql = MySQL(app)

def publicar_mqtt(topico, payload):
    try:
        cliente = mqtt.Client()
        cliente.username_pw_set(
            username=os.environ.get("MQTT_USR"),
            password=os.environ.get("MQTT_PASS")
        )
    
        contexto_ssl = ssl.create_default_context()

        contexto_ssl.check_hostname = False 
        
        cliente.tls_set_context(contexto_ssl)
        
        host = os.environ.get("SERVIDOR")
        puerto = int(os.environ.get("PUERTO_MQTTS"))
        
        logging.info(f"Conectando vía MQTTS seguro a {host}:{puerto}...")
        cliente.connect(host, puerto, keepalive=60)
        
        cliente.loop_start()
        info = cliente.publish(topico, payload, qos=1)
        info.wait_for_publish(timeout=5) 
        
        cliente.loop_stop()
        cliente.disconnect()
        return True
    except Exception as e:
        logging.error(f"Error en MQTTS seguro: {str(e)}")
        try:
            cliente.loop_stop()
            cliente.disconnect()
        except:
            pass
        return False

# Rutas de interfaz
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/enviar_comando', methods=['POST'])
def enviar_comando():
    if request.method == 'POST':
        nodo_id = request.form.get('nodo_id')
        accion = request.form.get('accion') 
        
        if not nodo_id:
            flash('Error: No se especificó el ID del nodo.')
            return redirect(url_for('index'))
            
        if accion == 'destello':
            # Estructura del tópico
            topico = f"nodos/{nodo_id}/destello"
            payload = "1" # Pulso de activación
            
            if publicar_mqtt(topico, payload):
                flash(f"Comando DESTELLO enviado al nodo '{nodo_id}'")
            else:
                flash(f"Error de comunicación al enviar destello a '{nodo_id}'")
            
        elif accion == 'setpoint':
            valor_setpoint = request.form.get('setpoint_valor')
            
            if not valor_setpoint:
                flash('Error: Debes ingresar un valor para el setpoint.')
                return redirect(url_for('index'))
                
            topico = f"nodos/{nodo_id}/setpoint"
            payload = str(valor_setpoint)
            
            if publicar_mqtt(topico, payload):
                flash(f"Setpoint [{valor_setpoint}] enviado al nodo '{nodo_id}'")
            else:
                flash(f"Error de comunicación al enviar setpoint a '{nodo_id}'")
                
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)