"""Caracterizacion del enlace del robot - Modulo 2, Practica 5.

Mide lo que el punto de acceso entrega de verdad: retardo, varianza y perdida.
Se ejecuta EN LA COMPUTADORA, ya conectada a la red del robot.

QUE MIDE Y POR QUE

El Modulo 1 midio el enlace de radiofrecuencia por tasa de entrega. Aqui se
mide un enlace distinto con metricas distintas, porque el trafico es otro: el
video no tolera retardo pero si tolera perdida, al reves que la alarma.

Las tres cifras que salen de aqui alimentan el presupuesto de retardo de
RNF-02 en la semana 6, y sustituyen a las estimaciones del Modulo 1.

LA CIFRA QUE IMPORTA NO ES LA MEDIANA

Un enlace inalambrico casi siempre cumple en la mediana. Lo que decide si la
teleoperacion se siente bien es el percentil 95: son los cuadros que llegan
tarde, y el operador los percibe como tirones. Un enlace con mediana de 3 ms y
percentil 99 de 200 ms es peor para teleoperar que uno constante de 20 ms.

Uso:
    python verificar_enlace.py --pi 10.42.0.1
    python verificar_enlace.py --pi 10.42.0.1 --n 200 --capacidad
"""
import argparse
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time


def comprobar_ruta(destino):
    """Verifica que la computadora alcance a la Pi, y por que interfaz."""
    if shutil.which("ip"):
        salida = subprocess.run(["ip", "route", "get", destino],
                                capture_output=True, text=True).stdout
        m = re.search(r"dev (\S+).*src (\S+)", salida)
        if m:
            return m.group(1), m.group(2)
    return None, None


def medir_tcp(destino, puerto, n, intervalo):
    """Mide el RTT abriendo conexiones TCP, sin depender de ping.

    Util en dos casos: cuando ping no esta disponible, y cuando el destino
    responde a ping pero el servicio que interesa no esta escuchando. Lo
    segundo importa aqui: que la Pi responda al ping no garantiza que el
    servidor de video o el broker esten arriba.
    """
    rtts, fallos = [], 0
    for _ in range(n):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        t0 = time.perf_counter()
        try:
            s.connect((destino, puerto))
            rtts.append((time.perf_counter() - t0) * 1000.0)
        except OSError:
            fallos += 1
        finally:
            s.close()
        time.sleep(intervalo)
    return rtts, fallos


def medir_ping(destino, n, intervalo):
    """Devuelve la lista de RTT en ms y el numero de paquetes perdidos."""
    if not shutil.which("ping"):
        return None, None

    # -i puede requerir privilegios por debajo de 0.2 s en Linux
    cmd = ["ping", "-c", str(n), "-i", str(intervalo), destino]
    print("  Enviando {} paquetes cada {:.2f} s...".format(n, intervalo))
    r = subprocess.run(cmd, capture_output=True, text=True)

    rtts = [float(x) for x in re.findall(r"time=([\d.]+)\s*ms", r.stdout)]
    m = re.search(r"(\d+) packets transmitted, (\d+) received", r.stdout)
    enviados, recibidos = (int(m.group(1)), int(m.group(2))) if m else (n, len(rtts))
    return rtts, enviados - recibidos


def medir_capacidad(destino):
    """Requiere 'iperf3 -s' corriendo en la Raspberry Pi."""
    if not shutil.which("iperf3"):
        print("  iperf3 no esta instalado. Omitiendo la medicion de capacidad.")
        return None
    print("  Midiendo capacidad con iperf3 durante 10 s...")
    r = subprocess.run(["iperf3", "-c", destino, "-t", "10", "-f", "m"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  iperf3 fallo. Verifique que en la Pi corra: iperf3 -s")
        return None
    m = re.findall(r"([\d.]+)\s+Mbits/sec", r.stdout)
    return float(m[-1]) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="10.42.0.1")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--intervalo", type=float, default=0.2)
    ap.add_argument("--capacidad", action="store_true")
    ap.add_argument("--tcp", type=int, metavar="PUERTO",
                    help="Medir por conexion TCP a este puerto en lugar de ping")
    ap.add_argument("--csv", default="enlace_robot.csv")
    a = ap.parse_args()

    print("=" * 68)
    print("  CARACTERIZACION DEL ENLACE DEL ROBOT")
    print("=" * 68)

    # ---------------- Ruta ----------------
    iface, origen = comprobar_ruta(a.pi)
    if iface:
        print("  Se alcanza {} por la interfaz {} (origen {})".format(
            a.pi, iface, origen))
        if not origen.startswith("10.42.0."):
            print()
            print("  AVISO: la direccion de origen no esta en 10.42.0.0/24.")
            print("  Puede estar llegando por la red institucional en lugar")
            print("  de por la red del robot. Verifique a que Wi-Fi esta")
            print("  conectado.")
    else:
        print("  Destino: {}".format(a.pi))
    print("=" * 68)
    print()

    # ---------------- Retardo ----------------
    if a.tcp:
        print("  Midiendo por conexion TCP al puerto {}...".format(a.tcp))
        rtts, perdidos = medir_tcp(a.pi, a.tcp, a.n, a.intervalo)
    else:
        rtts, perdidos = medir_ping(a.pi, a.n, a.intervalo)
        if rtts is None:
            print("  No se encontro el comando ping.")
            print("  Reintentando por conexion TCP al puerto 22 (SSH)...")
            rtts, perdidos = medir_tcp(a.pi, 22, a.n, a.intervalo)

    if not rtts:
        print("\n  Sin respuesta. Comprobaciones, en orden:")
        print("    1. La computadora esta conectada a la red del robot.")
        print("    2. En la Pi: nmcli connection show --active")
        print("    3. La Pi responde en 10.42.0.1")
        print("    4. Si uso --tcp, que ese puerto este escuchando en la Pi.")
        return

    r = sorted(rtts)
    p50 = statistics.median(r)
    p95 = r[min(int(0.95 * len(r)), len(r) - 1)]
    p99 = r[min(int(0.99 * len(r)), len(r) - 1)]
    jitter = statistics.pstdev(r) if len(r) > 1 else 0.0

    print()
    print("  RETARDO DE IDA Y VUELTA")
    print("  " + "-" * 50)
    print("  Paquetes enviados  : {}".format(a.n))
    print("  Perdidos           : {}  ({:.1f} %)".format(
        perdidos, 100.0 * perdidos / a.n))
    print("  Minimo             : {:7.2f} ms".format(min(r)))
    print("  Mediana (p50)      : {:7.2f} ms".format(p50))
    print("  Percentil 95       : {:7.2f} ms".format(p95))
    print("  Percentil 99       : {:7.2f} ms".format(p99))
    print("  Maximo             : {:7.2f} ms".format(max(r)))
    print("  Jitter (desv. tip.): {:7.2f} ms".format(jitter))

    # ---------------- Capacidad ----------------
    ancho = None
    if a.capacidad:
        print()
        ancho = medir_capacidad(a.pi)
        if ancho:
            print("  Capacidad medida   : {:7.1f} Mbit/s".format(ancho))

    # ---------------- Interpretacion ----------------
    print()
    print("  INTERPRETACION")
    print("  " + "-" * 50)

    razon = p99 / p50 if p50 > 0 else 0
    if razon > 10:
        print("  El percentil 99 es {:.0f} veces la mediana. El enlace es".format(razon))
        print("  inestable: el problema es la VARIANZA, no la capacidad.")
        print("  Causas habituales: interferencia en el canal, la Pi saturada")
        print("  por la codificacion de video, o distancia excesiva.")
    elif razon > 3:
        print("  El percentil 99 es {:.0f} veces la mediana. Hay varianza".format(razon))
        print("  apreciable pero manejable. Anotela: reaparece al anadir el")
        print("  video en la Practica 6.")
    else:
        print("  El enlace es estable: el percentil 99 esta cerca de la")
        print("  mediana. Es el mejor punto de partida posible.")

    print()
    print("  APORTE AL PRESUPUESTO DE RNF-02")
    print("  El retardo de red en un sentido es aproximadamente la mitad del")
    print("  de ida y vuelta: {:.2f} ms en la mediana, {:.2f} ms en p95.".format(
        p50 / 2, p95 / 2))
    print("  Sustituya con estos numeros las estimaciones del Modulo 1 en")
    print("  presupuesto_retardo.py, y vuelva a evaluar si RNF-02 se cumple.")

    if ancho:
        print()
        print("  DIMENSIONAMIENTO DEL VIDEO")
        for fps, kb in ((15, 35), (30, 35)):
            mbps = fps * kb * 8 / 1000.0
            print("    {:>2} fps a {} kB por cuadro -> {:5.1f} Mbit/s  "
                  "({:.0f} % del enlace)".format(
                      fps, kb, mbps, 100.0 * mbps / ancho))
        print("  Por encima del 70 % el retardo crece de forma no lineal:")
        print("  es la misma regla del Modulo 1, aplicada a este enlace.")

    with open(a.csv, "w", encoding="utf-8") as f:
        f.write("muestra,rtt_ms\n")
        for k, v in enumerate(rtts, 1):
            f.write("{},{:.3f}\n".format(k, v))
    print()
    print("  Mediciones en: {}".format(a.csv))


if __name__ == "__main__":
    main()
