"""Medicion del enlace RF extremo a extremo - Modulo 3, Practicas 9 y 10.

Compara lo que el nodo DICE que transmitio con lo que la plataforma RECIBIO.
Se ejecuta en la PC, con el sistema de servicios levantado (broker y puente).

DOS FUENTES, UN SOLO RELOJ
  1. La bitacora del nodo por USB (--nodo-serial COM5) o por archivo
     (--nodo-log nodo_1.log, para el banco): secuencia, estado, si hubo
     acuse, intentos de radio, reintentos por software y tiempos.
  2. La telemetria en el broker (campus/telemetria/<nodo>/ambiente), con
     la secuencia en diag.secuencia (concentrador v3).
Las dos se sellan con el reloj de ESTA computadora, asi que su diferencia no
depende de sincronizar relojes.

QUE REPORTA
  - Entrega: tramas que llegaron a la plataforma / tramas que el nodo emitio,
    con intervalo de Wilson al 95 % y veredicto contra el objetivo.
  - Exito al primer intento: la fraccion de tramas que no necesito ningun
    reintento. Con ARQ la entrega puede ser 100 % aunque el canal este
    malo: esta cifra es la que delata la interferencia.
  - Antiguedad del estado: cuanto tarda la plataforma en conocer lo que el
    nodo transmitio. Si una trama se pierde, cuenta hasta la siguiente que
    llega. Es la contribucion del enlace al retardo de alarma (RNF-01).
  - Fluctuacion del ciclo: desviacion del tiempo entre transmisiones,
    descontada la transmision. Es el parametro sigma de practica09/medio.py.

Uso:
    python medir_enlace.py --nodo-serial COM5 --tramas 300 --etiqueta AP1-RF76
    python medir_enlace.py --tramas 300                     # sin bitacora
    python medir_enlace.py --nodo-log ../banco/corridas/x/nodo_1.log --tramas 60
"""
import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import threading
import time

import paho.mqtt.client as mqtt

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import medio  # noqa: E402

LINEA = re.compile(
    r"^\[(\d+)\].*?\s(normal|vigilancia|prealarma|alarma)\s+T\dH\dF\d\s+"
    r"(ACK|SIN ACK) int=(\d+) sw=(\d+) tx_us=(\d+) ciclo_us=(\d+)")
BANNER = "=== Nodo detector"


class Medicion:
    def __init__(self):
        self.lock = threading.Lock()
        self.nodo = {}          # seq -> dict de la bitacora
        self.plataforma = {}    # seq -> t de recepcion
        self.reinicios = 0

    def reiniciar(self):
        with self.lock:
            self.nodo.clear()
            self.plataforma.clear()
            self.reinicios += 1


def parsear(linea, t_llegada, baudios):
    """Convierte una linea de bitacora en un registro, o None."""
    m = LINEA.match(linea)
    if not m:
        return None
    tx_us = int(m.group(6))
    # La linea se imprime DESPUES de transmitir y tarda en cruzar el puerto
    # serie: (caracteres + 2) * 10 bits / baudios. Se descuentan ambos.
    t_serie = (len(linea) + 2) * 10.0 / baudios
    return {"seq": int(m.group(1)), "estado": m.group(2),
            "ack": m.group(3) == "ACK", "int": int(m.group(4)),
            "sw": int(m.group(5)), "tx_us": tx_us,
            "ciclo_us": int(m.group(7)),
            "t_gen": t_llegada - t_serie - tx_us / 1e6}


def leer_serial(puerto, baudios, med, parar):
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = puerto, baudios, 1
    s.dtr = False             # evita, en lo posible, reiniciar el ESP32
    s.rts = False
    s.open()
    while not parar.is_set():
        crudo = s.readline()
        t = time.perf_counter()
        procesar(crudo.decode("utf-8", "ignore").strip(), t, baudios, med)
    s.close()


def leer_archivo(ruta, med, parar):
    """Sigue un archivo que otro proceso escribe (como tail -f)."""
    while not os.path.exists(ruta) and not parar.is_set():
        time.sleep(0.2)
    with open(ruta) as f:
        f.seek(0, os.SEEK_END)
        while not parar.is_set():
            linea = f.readline()
            if not linea:
                time.sleep(0.01)
                continue
            procesar(linea.strip(), time.perf_counter(), 1e12, med)


def procesar(linea, t, baudios, med):
    if linea.startswith(BANNER) and med.nodo:
        print("  AVISO: el nodo se reinicio; la medicion recomienza.")
        med.reiniciar()
        return
    r = parsear(linea, t, baudios)
    if r is None:
        return
    with med.lock:
        if med.nodo and r["seq"] < max(med.nodo):
            print("  AVISO: la secuencia retrocedio (reinicio); recomienza.")
            med.nodo.clear()
            med.plataforma.clear()
            med.reinicios += 1
        med.nodo[r["seq"]] = r


def resumen(med, objetivo, etiqueta, con_bitacora):
    with med.lock:
        nodo = dict(med.nodo)
        plat = dict(med.plataforma)
    print()
    print("=" * 70)
    print("  MEDICION DEL ENLACE   {}".format(etiqueta or ""))
    print("=" * 70)
    fila = {"etiqueta": etiqueta}

    if con_bitacora:
        seqs = sorted(nodo)
        if not seqs:
            print("  Sin bitacora del nodo: revise el puerto o el archivo.")
            return fila
        n = len(seqs)
        entregadas = sum(1 for s in seqs if s in plat)
        print("  Tramas emitidas por el nodo   : {:5d}   (secuencias {}..{})".format(
            n, seqs[0], seqs[-1]))
    else:
        # Sin bitacora, lo emitido se estima por el rango de secuencias:
        # una perdida al principio o al final no se puede ver.
        seqs = sorted(plat)
        if not seqs:
            print("  No llego telemetria con diag.secuencia.")
            print("  Requiere el concentrador v3 y el puente corriendo.")
            return fila
        n = seqs[-1] - seqs[0] + 1
        entregadas = len(seqs)
        print("  Tramas emitidas (estimadas)   : {:5d}   (secuencias {}..{})".format(
            n, seqs[0], seqs[-1]))

    b, a = medio.wilson(entregadas, n)
    v = medio.veredicto(entregadas, n, objetivo)
    print("  Entregadas a la plataforma    : {:5d}   {:6.2%}   IC 95 % [{:.2%}, {:.2%}]".format(
        entregadas, entregadas / n, b, a))
    print("    veredicto contra {:.0%}       : {}".format(objetivo, v))
    if v == "no concluyente" and entregadas == n:
        print("    (sin perdidas hacen falta {} tramas para afirmarlo)".format(
            medio.tramas_para_demostrar(objetivo)))
    fila.update({"emitidas": n, "entregadas": entregadas,
                 "entrega": round(entregadas / n, 5), "ic_bajo": round(b, 5),
                 "ic_alto": round(a, 5), "veredicto": v})

    if con_bitacora:
        regs = [nodo[s] for s in seqs]
        uno = sum(1 for r in regs if r["ack"] and r["int"] == 1)
        b1, a1 = medio.wilson(uno, n)
        ints = [r["int"] for r in regs]
        print("  Exito al primer intento       : {:5d}   {:6.2%}   IC 95 % [{:.2%}, {:.2%}]".format(
            uno, uno / n, b1, a1))
        print("  Intentos de radio por trama   : media {:.2f}   maximo {}".format(
            statistics.mean(ints), max(ints)))
        print("  Tramas con reintento software : {:5d}".format(
            sum(1 for r in regs if r["sw"] > 0)))
        print("  Tramas sin acuse en el nodo   : {:5d}   (de ellas llegaron {})".format(
            sum(1 for r in regs if not r["ack"]),
            sum(1 for r in regs if not r["ack"] and r["seq"] in plat)))

        # Antiguedad del estado: desde que el nodo transmite la trama k hasta
        # que llega a la plataforma la k o, si se perdio, la siguiente.
        edades = []
        siguiente = math.inf
        for s in reversed(seqs):
            if s in plat:
                siguiente = min(siguiente, plat[s])
            if siguiente < math.inf:
                edades.append((siguiente - nodo[s]["t_gen"]) * 1000)
        if edades:
            print("  Antiguedad del estado (ms)    : mediana {:.0f}   p95 {:.0f}   maximo {:.0f}".format(
                medio.percentil(edades, 50), medio.percentil(edades, 95),
                max(edades)))
        # Fluctuacion natural del ciclo: ciclo - transmision anterior
        netos = []
        for s0, s1 in zip(seqs, seqs[1:]):
            if s1 == s0 + 1 and nodo[s1]["ciclo_us"] > 0:
                netos.append(nodo[s1]["ciclo_us"] - nodo[s0]["tx_us"])
        if len(netos) > 2:
            print("  Ciclo sin la transmision (us) : mediana {:.0f}   desviacion {:.0f}".format(
                statistics.median(netos), statistics.pstdev(netos)))
        fila.update({"primer_intento": round(uno / n, 5),
                     "intentos_media": round(statistics.mean(ints), 3),
                     "edad_p50_ms": round(medio.percentil(edades, 50), 1) if edades else "",
                     "edad_p95_ms": round(medio.percentil(edades, 95), 1) if edades else "",
                     "edad_max_ms": round(max(edades), 1) if edades else "",
                     "sigma_ciclo_us": round(statistics.pstdev(netos), 1)
                     if len(netos) > 2 else ""})
    if med.reinicios:
        print("  AVISO: hubo {} reinicio(s); solo cuenta el ultimo tramo.".format(
            med.reinicios))
    return fila


def main():
    ap = argparse.ArgumentParser(description="Medicion del enlace RF")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--nodo", default="d01", help="identificador en la plataforma")
    ap.add_argument("--nodo-serial", help="puerto USB del nodo detector")
    ap.add_argument("--nodo-log", help="archivo de bitacora (banco de pruebas)")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--tramas", type=int, default=300)
    ap.add_argument("--segundos", type=float, default=None,
                    help="limite de tiempo; si se alcanza antes, se reporta")
    ap.add_argument("--objetivo", type=float, default=0.99)
    ap.add_argument("--etiqueta", default="")
    ap.add_argument("--csv", default="resultados_enlace.csv",
                    help="archivo al que se agrega una fila; 'no' para omitir")
    a = ap.parse_args()

    med = Medicion()
    parar = threading.Event()

    def al_conectar(c, u, flags, motivo, props=None):
        c.subscribe("campus/telemetria/{}/ambiente".format(a.nodo), qos=1)

    def al_recibir(c, u, msg):
        t = time.perf_counter()
        try:
            d = json.loads(msg.payload.decode())
            seq = d["diag"]["secuencia"]
        except (ValueError, KeyError, TypeError):
            return
        with med.lock:
            med.plataforma.setdefault(seq, t)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id="medir-enlace-{}".format(os.getpid()))
    c.on_connect = al_conectar
    c.on_message = al_recibir
    try:
        c.connect(a.broker, 1883, 30)
    except OSError as e:
        sys.exit("No se alcanza el broker {} ({})".format(a.broker, e))
    c.loop_start()

    con_bitacora = bool(a.nodo_serial or a.nodo_log)
    if a.nodo_serial:
        hilo = threading.Thread(target=leer_serial, daemon=True,
                                args=(a.nodo_serial, a.baudios, med, parar))
        hilo.start()
    elif a.nodo_log:
        hilo = threading.Thread(target=leer_archivo, daemon=True,
                                args=(a.nodo_log, med, parar))
        hilo.start()

    fuente = "bitacora del nodo" if con_bitacora else "plataforma (sin bitacora)"
    print("Midiendo {} tramas de {} ({}). Ctrl-C para terminar antes.".format(
        a.tramas, a.nodo, fuente))
    t0 = time.time()
    ultimo = -1
    try:
        while True:
            with med.lock:
                n = len(med.nodo) if con_bitacora else len(med.plataforma)
            if n != ultimo and n % 25 == 0 and n:
                print("  {} tramas...".format(n), flush=True)
                ultimo = n
            if n >= a.tramas:
                break
            if a.segundos and time.time() - t0 > a.segundos:
                print("  Limite de tiempo alcanzado.")
                break
            time.sleep(0.2)
        time.sleep(2.0)       # margen para las que van en camino
    except KeyboardInterrupt:
        pass
    parar.set()
    c.loop_stop()
    c.disconnect()

    fila = resumen(med, a.objetivo, a.etiqueta, con_bitacora)
    if a.csv and a.csv != "no" and len(fila) > 1:
        nuevo = not os.path.exists(a.csv)
        campos = ["etiqueta", "emitidas", "entregadas", "entrega", "ic_bajo",
                  "ic_alto", "veredicto", "primer_intento", "intentos_media",
                  "edad_p50_ms", "edad_p95_ms", "edad_max_ms", "sigma_ciclo_us"]
        with open(a.csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            if nuevo:
                w.writeheader()
            w.writerow(fila)
        print("\n  Fila agregada a {}".format(a.csv))


if __name__ == "__main__":
    main()
