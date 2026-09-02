"""Publicador MQTT - Modulo 1, Practica 1.

Simula un nodo detector de incendios publicando por MQTT. En la Practica 4
este programa se sustituye por el nodo real, que transmite por radiofrecuencia
y llega al broker a traves del concentrador y el puente serie. El FORMATO DEL
MENSAJE es el mismo, y por eso el suscriptor no cambia.

Uso:
    python publicador.py                             # nodo d01, cada 5 s
    python publicador.py --nodo d02 --periodo 2
    python publicador.py --broker 192.168.50.10
    python publicador.py --escenario incendio        # provoca una escalada
"""
import argparse
import json
import math
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

ORDEN = ["normal", "vigilancia", "prealarma", "alarma"]
SEVERIDAD = {"vigilancia": "baja", "prealarma": "alta", "alarma": "critica"}


def leer_sensores(t0, escenario):
    """Telemetria sintetica con estructura realista.

    Se incluye una deriva lenta ademas del ruido. Esto importa: un generador
    puramente aleatorio no permitiria despues distinguir una anomalia real de
    la variacion normal del fenomeno.
    """
    t = time.time() - t0
    deriva = 1.5 * math.sin(2 * math.pi * (t / 60.0) / 30.0)

    if escenario == "incendio" and t > 30:
        d = t - 30
        temp = 23.0 + deriva + min(d * 0.5, 25.0) + random.gauss(0, 0.15)
        dtemp = min(d * 0.35, 12.0)
        humo = int(320 + min(d * 55, 2900) + random.gauss(0, 15))
        flama = int(95 + min(d * 85, 3500) + random.gauss(0, 10))
    else:
        temp = 23.0 + deriva + random.gauss(0, 0.2)
        dtemp = random.gauss(0, 0.3)
        humo = int(320 + random.gauss(0, 12))
        flama = int(95 + random.gauss(0, 8))

    # Regla multicriterio simplificada, equivalente a la del nodo real
    ind = sum([dtemp > 4.0, humo > 720, flama > 695])
    estado = ORDEN[min(ind, 3)]
    if ind == 2 and escenario == "incendio" and (time.time() - t0) > 70:
        estado = "alarma"

    return {
        "temperatura_c": round(temp, 2),
        "humedad_pct": round(50.0 - deriva * 1.5 + random.gauss(0, 0.8), 2),
        "presion_hpa": round(780.0 + random.gauss(0, 0.4), 2),
        "dtemp_c_min": round(dtemp, 2),
        "humo_adc": humo,
        "flama_adc": flama,
    }, estado


def main():
    ap = argparse.ArgumentParser(description="Simulador de nodo detector")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto", type=int, default=1883)
    ap.add_argument("--nodo", default="d01")
    ap.add_argument("--periodo", type=float, default=5.0)
    ap.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--escenario", default="normal",
                    choices=["normal", "incendio"])
    args = ap.parse_args()

    t_datos = "campus/telemetria/{}/ambiente".format(args.nodo)
    t_estado = "campus/estado/{}".format(args.nodo)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                          client_id="pub-{}".format(args.nodo))

    # Last Will and Testament: el broker publica esto si el cliente desaparece
    # SIN despedirse (cable desconectado, corte de energia). Es la unica forma
    # de distinguir "se apago bien" de "se cayo", y en un sistema de seguridad
    # esa diferencia importa: un detector caido es un area sin vigilancia.
    cliente.will_set(t_estado,
                     json.dumps({"estado": "offline", "motivo": "inesperado"}),
                     qos=1, retain=True)

    print("Conectando a {}:{} ...".format(args.broker, args.puerto))
    cliente.connect(args.broker, args.puerto, keepalive=30)
    cliente.loop_start()
    cliente.publish(t_estado, json.dumps({"estado": "online"}),
                    qos=1, retain=True)

    print("Publicando en {} cada {} s (QoS {})".format(
        t_datos, args.periodo, args.qos))
    print("Escenario: {}".format(args.escenario))
    print("Ctrl-C para detener.\n")

    t0 = time.time()
    n = 0
    estado_previo = None
    try:
        while True:
            medidas, estado = leer_sensores(t0, args.escenario)
            mensaje = {
                "version": "1.0",
                "nodo": args.nodo,
                "ts": datetime.now(timezone.utc).isoformat(),
                "calidad": "valida",
                "estado": estado,
                "medidas": medidas,
            }
            info = cliente.publish(t_datos, json.dumps(mensaje), qos=args.qos)
            info.wait_for_publish(timeout=5)
            n += 1

            # La alerta se publica solo al CAMBIAR de estado, no en cada
            # mensaje: repetirla continuamente produce fatiga de alarmas.
            if estado != estado_previo and estado in SEVERIDAD:
                sev = SEVERIDAD[estado]
                cliente.publish(
                    "campus/alertas/{}/{}".format(sev, args.nodo),
                    json.dumps({"version": "1.0", "nodo": args.nodo,
                                "ts": mensaje["ts"], "estado": estado,
                                "severidad": sev,
                                "transicion": "{} -> {}".format(
                                    estado_previo or "desconocido", estado),
                                "medidas": medidas}),
                    qos=1)
                print("  *** ALERTA {} : {} -> {} ***".format(
                    sev.upper(), estado_previo or "inicio", estado))
            estado_previo = estado

            print("[{:04d}] {:5.1f} C  d={:+5.2f}  humo={:4d}  flama={:4d}"
                  "  {}".format(n, medidas["temperatura_c"],
                                medidas["dtemp_c_min"], medidas["humo_adc"],
                                medidas["flama_adc"], estado))
            time.sleep(args.periodo)

    except KeyboardInterrupt:
        print("\nDetenido. Mensajes publicados: {}".format(n))
        cliente.publish(t_estado,
                        json.dumps({"estado": "offline", "motivo": "normal"}),
                        qos=1, retain=True)
        time.sleep(0.5)
        cliente.loop_stop()
        cliente.disconnect()


if __name__ == "__main__":
    main()
