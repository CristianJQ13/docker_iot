from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import logging, os
import aiomqtt
import ssl

token = os.environ["TB_TOKEN"]
# ID del dispositivo inyectado por Docker
dispositivo_id = os.environ.get("DISPOSITIVO_ID", "ID_DESCONOCIDO")

logging.basicConfig(format='%(asctime)s - TelegramBot - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Función publicación MQTT
async def publicar_mqtt(sub_topic, mensaje):
    """Crea una conexión TLS, publica el mensaje y cierra la conexión"""
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()
    
    try:
        async with aiomqtt.Client(
            os.environ["SERVIDOR"],
            username=os.environ["MQTT_USR"],
            password=os.environ["MQTT_PASS"],
            port=int(os.environ["PUERTO_MQTTS"]),
            tls_context=tls_context,
        ) as client:
            topico = f"{dispositivo_id}/{sub_topic}"
            await client.publish(topico, payload=str(mensaje))
            logging.info(f"MQTT Publicado -> {topico}: {mensaje}")
            return True
    except Exception as e:
        logging.error(f"Error publicando en MQTT: {e}")
        return False

# Comandos de control
async def cmd_setpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        valor = context.args[0]
        if await publicar_mqtt("setpoint", valor):
            await update.message.reply_text(f"Setpoint actualizado a {valor}°C")
        else:
            await update.message.reply_text("Error enviando comando al broker.")
    else:
        await update.message.reply_text("Uso correcto: /setpoint <valor>")

async def cmd_periodo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        valor = context.args[0]
        if await publicar_mqtt("periodo", valor):
            await update.message.reply_text(f"Período de lectura actualizado a {valor} segundos.")
        else:
            await update.message.reply_text("Error enviando comando al broker.")
    else:
        await update.message.reply_text("Uso correcto: /periodo <segundos>")

async def cmd_modo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ["auto", "manual"]:
        valor = context.args[0]
        if await publicar_mqtt("modo", valor):
            await update.message.reply_text(f"Modo de termostato cambiado a: {valor}")
        else:
            await update.message.reply_text("Error enviando comando al broker.")
    else:
        await update.message.reply_text("Uso correcto: /modo <auto|manual>")

async def cmd_rele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ["0", "1"]:
        valor = context.args[0]
        estado = "ENCENDIDO" if valor == "0" else "APAGADO"
        if await publicar_mqtt("rele", valor):
            await update.message.reply_text(f"Comando de relé enviado. Intención: {estado}")
        else:
            await update.message.reply_text("Error enviando comando al broker.")
    else:
        await update.message.reply_text("Uso correcto: /rele <0|1> (Solo funciona si estás en modo manual)")

async def cmd_destello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await publicar_mqtt("destello", "1"):
        await update.message.reply_text("Orden de destello enviada al LED de la placa TZZZZZ.")
    else:
        await update.message.reply_text("Error enviando comando al broker.")

# Funciones de lectura
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("se conectó: " + str(update.message.from_user.id))
    nombre = update.message.from_user.first_name if update.message.from_user.first_name else ""
    apellido = update.message.from_user.last_name if update.message.from_user.last_name else ""
    
    await context.bot.send_message(
        update.message.chat.id, 
        text=f"Bienvenido al Bot {nombre} {apellido}.\n\nPara controlar tu Pico podés usar:\n/setpoint <valor>\n/periodo <valor>\n/modo <auto|manual>\n/rele <0|1>\n/destello"
    )

def main():
    application = Application.builder().token(token).build()
    
    # Manejadores base
    application.add_handler(CommandHandler('start', start))
    
    # Manejadores de control
    application.add_handler(CommandHandler('setpoint', cmd_setpoint))
    application.add_handler(CommandHandler('periodo', cmd_periodo))
    application.add_handler(CommandHandler('modo', cmd_modo))
    application.add_handler(CommandHandler('rele', cmd_rele))
    application.add_handler(CommandHandler('destello', cmd_destello))

    # Manejadores de lectura
    application.run_polling()

if __name__ == '__main__':
    main()