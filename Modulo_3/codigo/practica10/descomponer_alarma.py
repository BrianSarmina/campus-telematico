"""Latencia de alarma descompuesta - Modulo 3, Practica 10. Se ejecuta en la PC.

El instrumento del Modulo 1 (medir_latencia_alarma.py) mide la latencia
TOTAL, del estimulo a la alerta. Este la parte en tres tramos, para saber a
quien culpar si RNF-01 no se cumple:

    t0         la persona aplica el estimulo y oprime Enter
    t_umbral   primera trama con dtemp >= umbral de subida (4 C/min)
    t_estado   primera trama con el estado buscado (vigilancia o mas)
    t_alerta   la alerta llega al broker

    sensor y pendiente  = t_umbral - t0        fisica + ventana de 60 s
    persistencia        = t_estado - t_umbral  6 s, cuantizados al periodo
    enlace y plataforma = t_alerta - t_estado  radio, serie, puente, broker

Necesita la bitacora del nodo (USB) y el broker. Usa el mismo reloj para las
dos, como medir_enlace.py.

Uso:
    python descomponer_alarma.py --nodo-serial COM5 --repeticiones 3
    python descomponer_alarma.py --nodo-log nodo_1.log --marca-banco   # banco
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
import threading
import time

import paho.mqtt.client as mqtt

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "practica09"))
import medir_enlace  # noqa: E402

ORDEN = ["normal", "vigilancia", "prealarma", "alarma"]
DTEMP = re.compile(r"d=([+-]?\d+\.\d+) C/min")
UMBRAL_DTEMP = 4.0      # deteccion.py del Modulo 1: UMBRAL_DTEMP_SUBIDA


class Registro:
    def __init__(self):
        self.lock = threading.Lock()
        self.lineas = []          # (t_gen, estado, dtemp)
        self.alertas = []         # (t, estado)
        self.marcas = []          # t de "[banco] estimulo"
        self.estado = None


def seguir(fuente, reg, baudios, parar):
    def procesar(linea, t):
        if linea.startswith("[banco] estimulo"):
            with reg.lock:
                reg.marcas.append(t)
            return
        r = medir_enlace.parsear(linea, t, baudios)
        m = DTEMP.search(linea)
        if r and m:
            with reg.lock:
                reg.lineas.append((r["t_gen"], r["estado"], float(m.group(1))))
                reg.estado = r["estado"]

    if fuente[0] == "serial":
        import serial
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = fuente[1], baudios, 1
        s.dtr = s.rts = False
        s.open()
        while not parar.is_set():
            crudo = s.readline()
            procesar(crudo.decode("utf-8", "ignore").strip(), time.perf_counter())
    else:
        while not os.path.exists(fuente[1]):
            time.sleep(0.2)
        with open(fuente[1]) as f:
            f.seek(0, os.SEEK_END)
            while not parar.is_set():
                linea = f.readline()
                if not linea:
                    time.sleep(0.01)
                    continue
                procesar(linea.strip(), time.perf_counter())


def main():
    ap = argparse.ArgumentParser(description="Latencia de alarma descompuesta")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--nodo", default="d01")
    ap.add_argument("--nodo-serial")
    ap.add_argument("--nodo-log")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--umbral", default="vigilancia", choices=ORDEN[1:])
    ap.add_argument("--requisito", type=float, default=15.0)
    ap.add_argument("--espera", type=float, default=90.0,
                    help="segundos maximos por repeticion")
    ap.add_argument("--marca-banco", action="store_true",
                    help="t0 = linea '[banco] estimulo' en lugar de Enter")
    ap.add_argument("--csv", default="latencia_descompuesta.csv")
    a = ap.parse_args()
    if not (a.nodo_serial or a.nodo_log):
        ap.error("hace falta la bitacora del nodo: --nodo-serial o --nodo-log")

    reg = Registro()
    parar = threading.Event()
    fuente = ("serial", a.nodo_serial) if a.nodo_serial else ("log", a.nodo_log)
    threading.Thread(target=seguir, args=(fuente, reg, a.baudios, parar),
                     daemon=True).start()

    def al_recibir(c, u, msg):
        t = time.perf_counter()
        try:
            d = json.loads(msg.payload.decode())
            if d.get("nodo") == a.nodo and d.get("estado") in ORDEN:
                with reg.lock:
                    reg.alertas.append((t, d["estado"]))
        except (ValueError, AttributeError):
            pass

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id="descomponer-{}".format(os.getpid()))
    c.on_connect = lambda cl, u, f, rc, p=None: cl.subscribe("campus/alertas/#", 1)
    c.on_message = al_recibir
    c.connect(a.broker, 1883, 30)
    c.loop_start()

    k_umbral = ORDEN.index(a.umbral)
    filas = []
    print("=" * 74)
    print("  LATENCIA DE ALARMA DESCOMPUESTA   umbral: {}   requisito: {:.0f} s".format(
        a.umbral, a.requisito))
    print("=" * 74)
    for i in range(1, a.repeticiones + 1):
        print("\n--- Repeticion {} de {} ---".format(i, a.repeticiones))
        t_lim = time.time() + 180
        while time.time() < t_lim:
            with reg.lock:
                listo = reg.estado == "normal"
            if listo:
                break
            print("  Esperando a que el nodo vuelva a normal...", flush=True)
            time.sleep(5)
        if a.marca_banco:
            with reg.lock:
                n0 = len(reg.marcas)
            print("  Esperando la marca del estimulo del banco...", flush=True)
            while True:
                with reg.lock:
                    if len(reg.marcas) > n0:
                        t0 = reg.marcas[-1]
                        break
                time.sleep(0.05)
        else:
            input("  Enter, y ENSEGUIDA aplique la secadora a 40 cm... ")
            t0 = time.perf_counter()
        print("  Cronometro en marcha. Mantenga el estimulo 20 s.")

        t_umbral = t_estado = t_alerta = None
        while time.perf_counter() - t0 < a.espera:
            with reg.lock:
                lin = [x for x in reg.lineas if x[0] >= t0 - 0.05]
                ale = [x for x in reg.alertas if x[0] >= t0]
            if t_umbral is None:
                t_umbral = next((x[0] for x in lin if x[2] >= UMBRAL_DTEMP), None)
            if t_estado is None:
                t_estado = next((x[0] for x in lin
                                 if ORDEN.index(x[1]) >= k_umbral), None)
            if t_alerta is None:
                t_alerta = next((x[0] for x in ale
                                 if ORDEN.index(x[1]) >= k_umbral), None)
            if t_alerta is not None and t_estado is not None:
                break
            time.sleep(0.05)
        print("  Retire el estimulo.")
        if None in (t_umbral, t_estado, t_alerta):
            print("  INCOMPLETA en {:.0f} s: umbral={} estado={} alerta={}".format(
                a.espera, t_umbral is not None, t_estado is not None,
                t_alerta is not None))
            continue
        f = {"rep": i, "sensor_y_pendiente_s": t_umbral - t0,
             "persistencia_s": t_estado - t_umbral,
             "enlace_y_plataforma_s": t_alerta - t_estado,
             "total_s": t_alerta - t0}
        filas.append(f)
        print("  sensor y pendiente   {:6.2f} s".format(f["sensor_y_pendiente_s"]))
        print("  persistencia         {:6.2f} s".format(f["persistencia_s"]))
        print("  enlace y plataforma  {:6.3f} s".format(f["enlace_y_plataforma_s"]))
        print("  TOTAL                {:6.2f} s".format(f["total_s"]))

    parar.set()
    c.loop_stop()
    c.disconnect()
    if not filas:
        print("\nSin repeticiones completas.")
        return
    print("\n" + "=" * 74)
    print("  {:<24} {:>10} {:>10} {:>10}".format("Tramo", "mediana", "minimo",
                                               "maximo"))
    print("  " + "-" * 58)
    for clave, nombre in (("sensor_y_pendiente_s", "Sensor y pendiente"),
                          ("persistencia_s", "Persistencia"),
                          ("enlace_y_plataforma_s", "Enlace y plataforma"),
                          ("total_s", "TOTAL")):
        v = [f[clave] for f in filas]
        print("  {:<24} {:>9.2f}s {:>9.2f}s {:>9.2f}s".format(
            nombre, statistics.median(v), min(v), max(v)))
    peor = max(f["total_s"] for f in filas)
    print("\n  Peor total {:.2f} s contra {:.0f} s: {}".format(
        peor, a.requisito, "CUMPLE" if peor < a.requisito else "NO CUMPLE"))
    print("  Con {} repeticiones esto es una prueba, no una estadistica.".format(
        len(filas)))
    if a.csv and a.csv != "no":
        nuevo = not os.path.exists(a.csv)
        with open(a.csv, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]))
            if nuevo:
                w.writeheader()
            w.writerows(filas)
        print("  Repeticiones agregadas a {}".format(a.csv))


if __name__ == "__main__":
    main()
