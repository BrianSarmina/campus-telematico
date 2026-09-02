"""Puente serie a MQTT - Modulo 1, Practica 4. Se ejecuta en la PC.

Lee las lineas JSON del concentrador por USB y las publica en el broker con
el formato que espera el resto del sistema.

ES LA PIEZA QUE CONECTA LOS DOS MUNDOS: a partir de aqui todo el proyecto
(plataforma, reglas, consola, analisis de trafico) funciona sin saber que
existe un enlace de radiofrecuencia.

TOPICOS QUE PUBLICA
    campus/telemetria/<nodo>/ambiente    QoS 1   vigilancia rutinaria
    campus/alertas/<severidad>/<nodo>    QoS 1   cambios de estado
    campus/estado/puente-rf              QoS 1, retenido

SEPARACION DE CLASES DE TRAFICO
La telemetria y la alarma van a topicos DISTINTOS a proposito. Permite que un
suscriptor se abone solo a las alarmas sin recibir el flujo rutinario, y es la
base sobre la que el Modulo 3 aplica prioridades diferenciadas.

Uso:
    python puente_serie.py --puerto /dev/ttyUSB0
    python puente_serie.py --puerto COM4 --broker 192.168.50.10
    python puente_serie.py --simular            # sin hardware
    python puente_serie.py --simular --escenario incendio

Dependencias:  pip install pyserial paho-mqtt
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

try:
    import serial
except ImportError:
    serial = None

# Severidad asociada a cada estado del nodo
SEVERIDAD = {
    "normal": None,          # no genera alerta
    "vigilancia": "baja",
    "prealarma": "alta",
    "alarma": "critica",
}


def marca_utc():
    return datetime.now(timezone.utc).isoformat()


def a_formato_plataforma(crudo):
    """Convierte el mensaje del concentrador al contrato del ICD.

    El concentrador entrega ts_rx_ms, que es el contador interno del ESP32
    desde su arranque y no sirve como marca absoluta. La PC, que si tiene
    reloj sincronizado, la sustituye por una marca UTC real. La calidad se
    declara "estimada" porque el sello sigue sin venir del nodo que midio.
    """
    return {
        "version": "1.0",
        "nodo": crudo["nodo"],
        "ts": marca_utc(),
        "calidad": "estimada",
        "estado": crudo.get("estado", "desconocido"),
        "medidas": {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in crudo["medidas"].items()},
        "diag": crudo.get("diag", {}),
    }


# =====================================================================
#  Simulador: permite probar todo el camino sin hardware
# =====================================================================
class Simulador:
    """Reproduce lo que emitiria el concentrador, incluida una escalada."""

    def __init__(self, escenario="normal"):
        self.escenario = escenario
        self.n = 0
        self.t0 = time.time()

    def siguiente(self):
        t = time.time() - self.t0
        self.n += 1

        if self.escenario == "incendio" and t > 20:
            d = t - 20
            temp = 23.0 + min(d * 0.5, 25.0)
            dtemp = min(d * 0.4, 12.0)
            humo = int(320 + min(d * 60, 2900))
            flama = int(95 + min(d * 90, 3500))
            if dtemp > 4 and humo > 700 and flama > 700:
                estado = "alarma" if d > 25 else "prealarma"
            elif dtemp > 4:
                estado = "vigilancia"
            else:
                estado = "normal"
        else:
            temp = 23.0 + random.gauss(0, 0.3)
            dtemp = random.gauss(0, 0.4)
            humo = int(320 + random.gauss(0, 12))
            flama = int(95 + random.gauss(0, 8))
            estado = "normal"

        return {
            "version": 2, "nodo": "d01", "secuencia": self.n,
            "estado": estado,
            "estado_num": ["normal", "vigilancia", "prealarma",
                           "alarma"].index(estado),
            "ts_rx_ms": int(t * 1000),
            "medidas": {
                "temperatura_c": round(temp, 2),
                "humedad_pct": round(48.0 + random.gauss(0, 1), 2),
                "presion_hpa": round(780.0 + random.gauss(0, 0.4), 2),
                "dtemp_c_min": round(dtemp, 2),
                "humo_adc": humo, "flama_adc": flama,
            },
            "diag": {"tasa_entrega": 1.0, "recibidos": self.n, "perdidos": 0},
        }


def main():
    ap = argparse.ArgumentParser(description="Puente serie a MQTT")
    ap.add_argument("--puerto", default="/dev/ttyUSB0")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto-broker", type=int, default=1883)
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--escenario", default="normal",
                    choices=["normal", "incendio"])
    ap.add_argument("--periodo", type=float, default=2.0,
                    help="Periodo del simulador, en segundos")
    ap.add_argument("--verboso", action="store_true")
    args = ap.parse_args()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="puente-rf")
    cliente.will_set("campus/estado/puente-rf",
                     json.dumps({"estado": "offline", "motivo": "inesperado"}),
                     qos=1, retain=True)
    try:
        cliente.connect(args.broker, args.puerto_broker, 60)
    except OSError as e:
        sys.exit("No se pudo conectar al broker {}:{} ({}).\n"
                 "Verifique la infraestructura: docker compose ps"
                 .format(args.broker, args.puerto_broker, e))
    cliente.loop_start()
    cliente.publish("campus/estado/puente-rf",
                    json.dumps({"estado": "online"}), qos=1, retain=True)

    # ------------------- Origen de los datos -------------------
    sim = None
    origen = None
    if args.simular:
        sim = Simulador(args.escenario)
        print("Modo simulacion, escenario: {}".format(args.escenario))
    else:
        if serial is None:
            sys.exit("Falta pyserial. Instale con: pip install pyserial")
        try:
            origen = serial.Serial(args.puerto, args.baudios, timeout=2)
        except serial.SerialException as e:
            sys.exit("No se pudo abrir {} ({}).\n"
                     "Linux: verifique pertenecer al grupo dialout.\n"
                     "Windows: revise el numero de puerto COM."
                     .format(args.puerto, e))
        time.sleep(2)          # el ESP32 se reinicia al abrir el puerto
        print("Escuchando el concentrador en {}".format(args.puerto))

    print("Telemetria -> campus/telemetria/<nodo>/ambiente")
    print("Alertas    -> campus/alertas/<severidad>/<nodo>")
    print("Ctrl-C para detener.\n")

    publicados = 0
    alertas = 0
    estado_previo = {}

    try:
        while True:
            # ----------- Obtener un mensaje -----------
            if sim is not None:
                time.sleep(args.periodo)
                crudo = sim.siguiente()
            else:
                linea = origen.readline().decode("utf-8", "ignore").strip()
                if not linea:
                    continue
                try:
                    crudo = json.loads(linea)
                except json.JSONDecodeError:
                    if args.verboso:
                        print("  [no es JSON] {}".format(linea[:70]))
                    continue

            if "evento" in crudo:
                print(">>> {}".format(crudo))
                continue
            if "medidas" not in crudo:
                continue

            mensaje = a_formato_plataforma(crudo)
            nodo = mensaje["nodo"]

            # ----------- Telemetria -----------
            cliente.publish("campus/telemetria/{}/ambiente".format(nodo),
                            json.dumps(mensaje), qos=1)
            publicados += 1

            # ----------- Alerta por cambio de estado -----------
            # Solo se publica cuando el estado CAMBIA, no en cada trama.
            # Repetir la alarma cada segundo produce fatiga de alarmas, que
            # es el problema que el Modulo 4 trata en profundidad.
            estado = mensaje["estado"]
            if estado != estado_previo.get(nodo):
                severidad = SEVERIDAD.get(estado)
                if severidad is not None:
                    alerta = {
                        "version": "1.0", "nodo": nodo, "ts": mensaje["ts"],
                        "estado": estado, "severidad": severidad,
                        "transicion": "{} -> {}".format(
                            estado_previo.get(nodo, "desconocido"), estado),
                        "medidas": mensaje["medidas"],
                    }
                    cliente.publish(
                        "campus/alertas/{}/{}".format(severidad, nodo),
                        json.dumps(alerta), qos=1)
                    alertas += 1
                    print("  *** ALERTA {} en {}: {} ***".format(
                        severidad.upper(), nodo, alerta["transicion"]))
                estado_previo[nodo] = estado

            m = mensaje["medidas"]
            d = mensaje.get("diag", {})
            print("[{:04d}] {} | {:5.1f} C  d={:+5.2f}  humo={:4d}  "
                  "flama={:4d}  {:<10} entrega {:.1%}".format(
                      publicados, nodo, m.get("temperatura_c", 0),
                      m.get("dtemp_c_min", 0), m.get("humo_adc", 0),
                      m.get("flama_adc", 0), estado,
                      d.get("tasa_entrega", 1.0)))

    except KeyboardInterrupt:
        print("\n\nMensajes publicados : {}".format(publicados))
        print("Alertas emitidas    : {}".format(alertas))
        cliente.publish("campus/estado/puente-rf",
                        json.dumps({"estado": "offline", "motivo": "normal"}),
                        qos=1, retain=True)
        time.sleep(0.5)
        cliente.loop_stop()
        cliente.disconnect()
        if origen is not None:
            origen.close()


if __name__ == "__main__":
    main()
