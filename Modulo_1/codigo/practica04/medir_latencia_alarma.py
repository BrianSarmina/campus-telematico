"""Medicion de la latencia de alarma - Modulo 1, Practica 4.

Verifica el requisito RNF-01: menos de 5 s entre la deteccion y el aviso en
consola, en el percentil 95.

QUE MIDE EXACTAMENTE
El cronometro arranca cuando el operador declara que aplico el estimulo, y se
detiene cuando llega la alerta por MQTT. Por tanto mide la cadena completa:

    sensor -> algoritmo -> radio -> concentrador -> serie -> puente -> broker

Incluye el tiempo de respuesta fisica del sensor, que en el MQ-2 no es
despreciable. Eso es deliberado: el requisito es sobre el sistema completo tal
como lo percibe el operador, no sobre la parte electronica.

PROTOCOLO (el mismo que fija el programa general)
  1. Registrar la temperatura de partida y esperar tres lecturas estables
  2. Marcar el instante de inicio  -> lo hace este programa
  3. Aplicar la secadora a 40 cm durante 20 s
  4. Registrar el instante de la alarma -> lo hace este programa
  5. Retirar el estimulo y esperar el restablecimiento
  6. Repetir cinco veces y reportar mediana y percentil 95

Uso:
    python medir_latencia_alarma.py
    python medir_latencia_alarma.py --repeticiones 5 --umbral vigilancia
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

ORDEN = ["normal", "vigilancia", "prealarma", "alarma"]

estado_actual = {}
eventos = []          # (t_recepcion, nodo, estado)


def al_conectar(cliente, userdata, flags, motivo, propiedades=None):
    cliente.subscribe("campus/alertas/#", qos=1)
    cliente.subscribe("campus/telemetria/+/ambiente", qos=1)


def al_recibir(cliente, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    nodo = d.get("nodo")
    estado = d.get("estado")
    if nodo and estado:
        if estado_actual.get(nodo) != estado:
            eventos.append((time.perf_counter(), nodo, estado))
        estado_actual[nodo] = estado


def esperar_reposo(timeout=120):
    """Espera a que todos los nodos vuelvan a normal antes de la siguiente
    repeticion. Sin esto, la segunda medicion arrancaria desde un estado ya
    elevado y saldria artificialmente baja."""
    inicio = time.time()
    while time.time() - inicio < timeout:
        if estado_actual and all(e == "normal" for e in estado_actual.values()):
            return True
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--repeticiones", type=int, default=5)
    ap.add_argument("--umbral", default="vigilancia",
                    choices=["vigilancia", "prealarma", "alarma"],
                    help="Estado que cuenta como deteccion")
    ap.add_argument("--requisito", type=float, default=5.0, help="segundos")
    ap.add_argument("--csv", default="latencia_alarma.csv")
    a = ap.parse_args()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="medidor")
    cliente.on_connect = al_conectar
    cliente.on_message = al_recibir
    try:
        cliente.connect(a.broker, 1883, 60)
    except OSError as e:
        sys.exit("No se pudo conectar al broker: {}".format(e))
    cliente.loop_start()
    time.sleep(1.5)

    print("=" * 70)
    print("  MEDICION DE LATENCIA DE ALARMA")
    print("=" * 70)
    print("  Umbral de deteccion : {}".format(a.umbral))
    print("  Requisito RNF-01    : {:.1f} s en el percentil 95".format(a.requisito))
    print("  Repeticiones        : {}".format(a.repeticiones))
    print("=" * 70)

    if not estado_actual:
        print("\n  AVISO: no se ha recibido ningun mensaje todavia.")
        print("  Verifique que el puente serie este en ejecucion.")

    umbral_idx = ORDEN.index(a.umbral)
    latencias = []

    for i in range(1, a.repeticiones + 1):
        print("\n--- Repeticion {} de {} ---".format(i, a.repeticiones))

        if i > 1:
            print("  Esperando a que el sistema vuelva a reposo...")
            if not esperar_reposo():
                print("  AVISO: no volvio a normal. El resultado puede no ser valido.")

        temps = [d for d in estado_actual.values()]
        print("  Estado actual de los nodos: {}".format(
            estado_actual if estado_actual else "sin datos"))
        input("  Enter, y ENSEGUIDA aplique la secadora a 40 cm... ")

        t_inicio = time.perf_counter()
        marca = len(eventos)
        print("  Cronometro en marcha. Mantenga el estimulo 20 s.")

        detectado = None
        while time.perf_counter() - t_inicio < 60:
            for t_ev, nodo, estado in eventos[marca:]:
                if ORDEN.index(estado) >= umbral_idx:
                    detectado = (t_ev - t_inicio, nodo, estado)
                    break
            if detectado:
                break
            time.sleep(0.05)

        if detectado:
            lat, nodo, estado = detectado
            latencias.append(lat)
            print("  DETECTADO en {:.2f} s  (nodo {}, estado {})".format(
                lat, nodo, estado))
        else:
            print("  SIN DETECCION en 60 s.")
            print("  Revise: distancia del estimulo, umbrales del algoritmo,")
            print("  y que el enlace de radiofrecuencia este entregando.")

        print("  Retire el estimulo.")

    cliente.loop_stop()
    cliente.disconnect()

    # ---------------------- Resultados ----------------------
    print("\n" + "=" * 70)
    print("  RESULTADOS")
    print("=" * 70)

    if not latencias:
        print("  No se registro ninguna deteccion. Nada que reportar.")
        return

    lat = sorted(latencias)
    p95 = lat[min(int(0.95 * len(lat)), len(lat) - 1)]

    print("  Detecciones     : {} de {}".format(len(lat), a.repeticiones))
    print("  Minimo          : {:.2f} s".format(min(lat)))
    print("  Mediana         : {:.2f} s".format(statistics.median(lat)))
    print("  Media           : {:.2f} s".format(statistics.mean(lat)))
    print("  Percentil 95    : {:.2f} s".format(p95))
    print("  Maximo          : {:.2f} s".format(max(lat)))
    if len(lat) > 1:
        print("  Desviacion tipica: {:.2f} s".format(statistics.pstdev(lat)))

    print("\n  Requisito RNF-01: p95 < {:.1f} s".format(a.requisito))
    print("  VEREDICTO: " + ("CUMPLE" if p95 < a.requisito else "NO CUMPLE"))

    if len(lat) < 5:
        print("\n  ADVERTENCIA: con menos de 5 muestras el percentil 95 no es")
        print("  representativo. Se reporta por completitud, no como evidencia.")

    with open(a.csv, "w", encoding="utf-8") as f:
        f.write("repeticion,latencia_s\n")
        for k, v in enumerate(latencias, 1):
            f.write("{},{:.3f}\n".format(k, v))
    print("\n  Mediciones guardadas en: {}".format(a.csv))
    print("  Adjuntar a la bitacora como evidencia de RNF-01.")


if __name__ == "__main__":
    main()
