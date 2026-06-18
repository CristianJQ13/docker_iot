import asyncio, ssl, certifi, logging, os, aiomysql, json, traceback
import aiomqtt

# Configuración del log para ver qué pasa en cada momento
logging.basicConfig(format='%(asctime)s - cliente mqtt - %(levelname)s:%(message)s', level=logging.INFO, datefmt='%d/%m/%Y %H:%M:%S %z')

async def main():
    # Configuración de seguridad TLS (importante para tu servidor)
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()

    async with aiomqtt.Client(
        hostname=os.environ["SERVIDOR"],
        # username=os.environ["MQTT_USR"],
        # password=os.environ["MQTT_PASS"],
        port=int(os.environ["PUERTO_MQTTS"]),
        tls_context=tls_context,
    ) as client:
        # Suscripción al tópico definido en tu .env
        await client.subscribe(os.environ['TOPICO'])
        print("Escuchando mensajes...")
        
        async for message in client.messages:
            payload_str = message.payload.decode("utf-8")
            logging.info(f"RECIBIDO -> {message.topic}: {payload_str}")
        
            # Si el mensaje NO empieza con '{', es un comando (como setpoint/destello)
            # Lo ignoro para la BD
            if not payload_str.strip().startswith('{'):
                logging.info("Es un comando. Ignorando para BD.")
                continue 
            
            # Si llega acá, es un JSON válido (telemetría de la Raspberry Pico)
            try:
                datos = json.loads(payload_str)
                dispositivo = str(message.topic).split('/')[-1]
                sql = "INSERT INTO `mediciones` (`sensor_id`, `temperatura`, `humedad`) VALUES (%s, %s, %s)"
                
                # Conexión a MariaDB
                conn = await aiomysql.connect(
                    host=os.environ["MARIADB_SERVER"], port=3306,
                    user=os.environ["MARIADB_USER"],
                    password=os.environ["MARIADB_USER_PASS"],
                    db=os.environ["MARIADB_DB"]
                )
                
                async with conn.cursor() as cur:
                    await cur.execute(sql, (dispositivo, datos['temperatura'], datos['humedad']))
                    await conn.commit()
                conn.close()
                logging.info("Datos guardados en BD exitosamente.")
                
            except Exception as e:
                logging.error(f"Error procesando JSON: {e}")

if __name__ == "__main__":
    asyncio.run(main())