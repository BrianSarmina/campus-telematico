"""Suscriptor MQTT - Practica 1.

Recibe la telemetria de todos los nodos, mide el retardo entre la emision
y la recepcion, y acumula estadistica. Al detenerlo con Ctrl-C imprime un
resumen que se usa como evidencia en la bitacora.

ADVERTENCIA SOBRE EL RETARDO MEDIDO: se calcula restando la marca de tiempo
del emisor a la del receptor. Si ambos relojes no estan sincronizados (NTP),
el valor incluye el desfase entre relojes y puede salir incluso negativo.
Con emisor y receptor en la misma maquina el problema no existe.

Uso:
    python suscriptor.py
    python suscriptor.py --broker 192.168.1.100 --filtro "campus/#"
"""
import argparse
import csv
import json
import signal
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

retardos = defaultdict(list)
contador = defaultdict(int)
registros = []
malformados = 0
ARCHIVO_CSV = "mediciones_p1.csv"


def al_conectar(cliente, userdata, flags, motivo, propiedades=None):
    if motivo == 0:
        print(f"Conectado al broker. Suscribiendo a {userdata['filtro']}\n")
        cliente.subscribe(userdata["filtro"], qos=1)
    else:
        print(f"ERROR de conexion, codigo {motivo}")


def al_desconectar(cliente, userdata, flags, motivo, propiedades=None):
    if motivo != 0:
        print(f"\n[!] Desconexion inesperada (codigo {motivo}). Reintentando...")


def al_recibir(cliente, userdata, msg):
    global malformados
    ahora = datetime.now(timezone.utc)

    try:
        datos = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        malformados += 1
        print(f"[MALFORMADO] {msg.topic}: {msg.payload[:60]!r}")
        return

    # ENRUTADO POR TOPICO, no por la presencia de un campo.
    #
    # La version anterior de este programa decidia mirando si existia la clave
    # "estado". Al agregar el estado de deteccion a la telemetria del nodo, esa
    # heuristica empezo a clasificar la telemetria como mensaje de conexion y
    # el suscriptor dejo de contar mensajes, en silencio.
    #
    # Es la clase de fallo que el Documento de Control de Interfaces previene:
    # el topico forma parte del contrato, el contenido de un campo no.
    if msg.topic.startswith("campus/estado/"):
        marca = "CONECTADO" if datos.get("estado") == "online" else "DESCONECTADO"
        print(f">>> {msg.topic}: {marca} ({datos.get('motivo', '-')})", flush=True)
        return

    if msg.topic.startswith("campus/alertas/"):
        print(f"*** ALERTA {datos.get('severidad','?').upper()} en "
              f"{datos.get('nodo','?')}: {datos.get('transicion','?')} ***",
              flush=True)
        return

    if not msg.topic.startswith("campus/telemetria/"):
        return

    nodo = datos.get("nodo", "?")
    contador[nodo] += 1

    if "ts" in datos:
        emitido = datetime.fromisoformat(datos["ts"])
        retardo_ms = (ahora - emitido).total_seconds() * 1000
        retardos[nodo].append(retardo_ms)
        m = datos.get("medidas", {})
        registros.append({
            "recibido": ahora.isoformat(), "emitido": datos["ts"],
            "nodo": nodo, "retardo_ms": round(retardo_ms, 3),
            **{k: v for k, v in m.items()},
        })
        print(f"{nodo} | retardo {retardo_ms:7.2f} ms | "
              f"T {m.get('temperatura_c', '-'):>6} C  "
              f"d {m.get('dtemp_c_min', '-'):>6}  "
              f"humo {m.get('humo_adc', '-'):>4}  "
              f"{datos.get('estado', ''):<10}", flush=True)


def resumen():
    print("\n" + "=" * 64)
    print("  RESUMEN DE LA SESION")
    print("=" * 64)
    if not contador:
        print("  No se recibio ningun mensaje de telemetria.")
        print("  Verificar: broker en ejecucion, publicador activo, topico correcto.")
        return

    print(f"{'Nodo':<8}{'Mensajes':>10}{'Media':>10}{'Mediana':>10}"
          f"{'Minimo':>10}{'Maximo':>10}")
    print("-" * 64)
    for nodo in sorted(contador):
        r = retardos[nodo]
        if r:
            print(f"{nodo:<8}{contador[nodo]:>10}{statistics.mean(r):>9.2f}"
                  f"{statistics.median(r):>10.2f}{min(r):>10.2f}{max(r):>10.2f}")
        else:
            print(f"{nodo:<8}{contador[nodo]:>10}{'sin ts':>10}")
    print("-" * 64)
    print(f"Mensajes malformados: {malformados}")
    print("\nValores de referencia (emisor y receptor en la misma maquina):")
    print("  Retardo tipico en red local: 1 a 15 ms")
    print("  Un retardo negativo indica relojes NO sincronizados, no un error.")

    if registros:
        campos = sorted({k for r in registros for k in r})
        with open(ARCHIVO_CSV, "w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(registros)
        print(f"\nMediciones exportadas a: {ARCHIVO_CSV}")
        print("Adjuntar este archivo como evidencia en la bitacora.")


def terminar(signum=None, marco=None):
    """Se ejecuta con Ctrl-C (SIGINT) o al recibir SIGTERM.

    Se usa un manejador explicito y no un try/except KeyboardInterrupt
    porque loop_forever() de paho no siempre propaga la excepcion, y el
    resumen es la evidencia que se entrega en la bitacora: no puede
    depender de un comportamiento incierto de la biblioteca.
    """
    resumen()
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Suscriptor MQTT con medicion de retardo")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto", type=int, default=1883)
    ap.add_argument("--filtro", default="campus/#",
                    help="Filtro de suscripcion. + = un nivel, # = varios")
    ap.add_argument("--csv", default="mediciones_p1.csv",
                    help="Archivo de salida con las mediciones")
    args = ap.parse_args()
    ARCHIVO_CSV = args.csv

    signal.signal(signal.SIGINT, terminar)
    signal.signal(signal.SIGTERM, terminar)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sub-monitor",
                          userdata={"filtro": args.filtro})
    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar
    cliente.on_message = al_recibir

    cliente.connect(args.broker, args.puerto, 60)
    cliente.loop_forever()
