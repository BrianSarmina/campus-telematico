"""Servicio de ingesta - Modulo 2, Practica 7. Se ejecuta en la computadora.

Suscribe la telemetria y las alertas, las valida contra el contrato y las
guarda en la base de datos.

LA VALIDACION ES UNA BARRERA, IGUAL QUE EN EL ROBOT
Un mensaje que no cumple el contrato no entra a la base. Se cuenta, se
registra el motivo y se descarta. La alternativa, guardar lo que llegue y
limpiar despues, convierte cada consulta futura en una sospecha.

POR QUE LA INGESTA ES UN PROCESO APARTE DE LA API
  - Si la API se cae, la ingesta sigue guardando: no se pierden datos.
  - Si la ingesta se cae, la API sigue sirviendo lo que ya existe.
  - Cada proceso tiene una sola razon para cambiar.
Es la misma separacion que en el Modulo 1 hubo entre concentrador y puente.

Uso:
    python ingesta.py
    python ingesta.py --broker localhost --bd campus.db
"""
import argparse
import json
import sys
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, "../contrato")
import contrato_mensajes as ct
import modelo_datos as md

cuenta = {"telemetria": 0, "alerta": 0, "duplicados": 0, "rechazados": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto", type=int, default=1883)
    ap.add_argument("--bd", default=md.RUTA_BD)
    ap.add_argument("--silencioso", action="store_true")
    a = ap.parse_args()

    con = md.conectar(a.bd)

    def al_conectar(c, u, flags, motivo, props=None):
        c.subscribe("campus/telemetria/+/ambiente", qos=ct.QOS["telemetria"])
        c.subscribe("campus/alertas/#", qos=ct.QOS["alerta"])
        print("Conectado al broker. Suscrito a telemetria y alertas.")

    def al_recibir(c, u, m):
        try:
            msg = json.loads(m.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            cuenta["rechazados"] += 1
            return

        # El topico decide el tipo, no el contenido. Es la leccion del
        # suscriptor del Modulo 1, que fallo por distinguir por un campo.
        tipo = "alerta" if m.topic.startswith("campus/alertas/") else "telemetria"

        errores = ct.validar(tipo, msg)
        if errores:
            cuenta["rechazados"] += 1
            print("  RECHAZADO {} en {}: {}".format(tipo, m.topic, errores[0][:70]))
            return

        if tipo == "telemetria":
            nuevo = md.guardar_telemetria(con, msg)
        else:
            nuevo = md.guardar_alerta(con, msg)
            if nuevo:
                print("  *** ALERTA {} en {}: {} ***".format(
                    msg["severidad"].upper(), msg["nodo"], msg["transicion"]))

        if nuevo:
            cuenta[tipo] += 1
        else:
            cuenta["duplicados"] += 1

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ingesta")
    cliente.on_connect = al_conectar
    cliente.on_message = al_recibir
    cliente.reconnect_delay_set(min_delay=1, max_delay=10)
    cliente.will_set(ct.TOPICOS["estado"].format(componente="ingesta"),
                     json.dumps({"estado": "offline", "motivo": "inesperado"}),
                     qos=1, retain=True)
    try:
        cliente.connect(a.broker, a.puerto, keepalive=30)
    except OSError as e:
        sys.exit("No se pudo conectar al broker {}:{} ({})".format(
            a.broker, a.puerto, e))
    cliente.publish(ct.TOPICOS["estado"].format(componente="ingesta"),
                    json.dumps({"estado": "online"}), qos=1, retain=True)
    cliente.loop_start()

    print("Guardando en {}. Ctrl-C para detener.\n".format(a.bd))
    try:
        while True:
            time.sleep(30)
            if not a.silencioso:
                print("[{}] telemetria={} alertas={} duplicados={} rechazados={}"
                      .format(time.strftime("%H:%M:%S"), cuenta["telemetria"],
                              cuenta["alerta"], cuenta["duplicados"],
                              cuenta["rechazados"]))
    except KeyboardInterrupt:
        print("\nResumen: {}".format(cuenta))
        cliente.publish(ct.TOPICOS["estado"].format(componente="ingesta"),
                        json.dumps({"estado": "offline", "motivo": "normal"}),
                        qos=1, retain=True)
        time.sleep(0.5)
        cliente.loop_stop()
        cliente.disconnect()


if __name__ == "__main__":
    main()
