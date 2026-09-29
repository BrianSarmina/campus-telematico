"""Medicion de la latencia de video - Modulo 2, Practica 6.

Completa el presupuesto de RNF-02. Junto con medir_lazo_control.py da el
retardo total que percibe el operador:

    latencia de video  +  latencia del lazo de control  =  lo que se siente

COMO SE MIDE SIN SINCRONIZAR RELOJES

El servidor estampa cada cuadro con el instante de captura segun el reloj
monotono de la Raspberry Pi. Comparar ese sello con el reloj de la computadora
no serviria: son relojes distintos y la diferencia entre ellos es arbitraria.

Lo que se hace es medir el DESFASE una vez, consultando /metricas y anotando
cuanto tarda la respuesta. Ese ida y vuelta acota el error de la conversion.
Despues cada cuadro se convierte a la referencia de la computadora.

El metodo tiene un error del orden del RTT medido en la Practica 5, y eso se
declara en el informe. Es una medicion util con su incertidumbre acotada, no
una cifra exacta.

Uso:
    python medir_video.py --pi 10.42.0.1
    python medir_video.py --pi 10.42.0.1 --n 200 --control lazo_control.csv
"""
import argparse
import json
import re
import statistics
import sys
import time
import socket
import urllib.request


def estimar_desfase(base, muestras=7):
    """Estima el desfase entre el reloj monotono de la Pi y el de la PC.

    Se toman varias muestras y se conserva la del ida y vuelta mas corto: es
    la que tiene menor incertidumbre, porque el error maximo esta acotado por
    la mitad del RTT. Es el mismo principio que usa NTP.
    """
    mejor_rtt = float("inf")
    mejor_desfase = 0.0
    for _ in range(muestras):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(base + "/metricas", timeout=3) as r:
                d = json.loads(r.read().decode())
        except OSError as e:
            sys.exit("No se pudo consultar {}/metricas ({}).\n"
                     "Verifique que servidor_video.py este en ejecucion."
                     .format(base, e))
        t1 = time.perf_counter()
        rtt = t1 - t0
        if rtt < mejor_rtt:
            mejor_rtt = rtt
            # Se supone simetria: la respuesta se genero a la mitad del RTT
            mejor_desfase = d["t_servidor"] - (t0 + rtt / 2.0)
    return mejor_desfase, mejor_rtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="10.42.0.1")
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--n", type=int, default=150, help="cuadros a medir")
    ap.add_argument("--calentamiento", type=int, default=10,
                    help="Cuadros iniciales que se descartan (transitorio)")
    ap.add_argument("--requisito", type=float, default=150.0, help="ms")
    ap.add_argument("--control", help="CSV de medir_lazo_control.py, para sumar")
    ap.add_argument("--csv", default="latencia_video.csv")
    a = ap.parse_args()

    base = "http://{}:{}".format(a.pi, a.puerto)

    print("=" * 66)
    print("  LATENCIA DEL VIDEO")
    print("=" * 66)
    print("  Servidor: {}".format(base))

    desfase, rtt = estimar_desfase(base)
    print("  Desfase de relojes estimado: {:+.3f} s".format(desfase))
    print("  Incertidumbre del metodo   : +/- {:.2f} ms".format(rtt * 1000 / 2))
    print("=" * 66)
    print("\n  Descartando {} cuadros de calentamiento...".format(a.calentamiento))
    print("  Midiendo {} cuadros...\n".format(a.n))

    latencias = []
    tamanos = []
    t_llegadas = []
    descartados = [0]

    # SE USA UN SOCKET CRUDO Y NO urllib PARA EL FLUJO
    #
    # urllib entrega los datos a traves de un lector con buffer propio, y no
    # permite saber si quedan datos pendientes. Para medir latencia hace falta
    # poder DRENAR la cola y quedarse con el cuadro mas reciente, que es lo que
    # hace un reproductor de video real: un cuadro viejo no sirve de nada.
    #
    # Sin ese drenado, lo que se mide es la cola que el propio instrumento
    # acumulo al arrancar, no el retardo del enlace.
    try:
        sock = socket.create_connection((a.pi, a.puerto), timeout=10)
        sock.sendall(("GET /video HTTP/1.1\r\nHost: {}\r\n"
                      "Connection: close\r\n\r\n").format(a.pi).encode())
    except OSError as e:
        sys.exit("No se pudo abrir el flujo de video: {}".format(e))

    class Flujo:
        """Adaptador minimo con drenado no bloqueante."""

        def __init__(self, s):
            self.s = s

        def read(self, n):
            self.s.settimeout(10)
            return self.s.recv(n)

        def drenar(self):
            """Lee todo lo pendiente sin bloquear. Devuelve los bytes."""
            self.s.settimeout(0.0)
            trozos = []
            try:
                while True:
                    c = self.s.recv(262144)
                    if not c:
                        break
                    trozos.append(c)
            except (BlockingIOError, socket.timeout, OSError):
                pass
            return b"".join(trozos)

        def close(self):
            self.s.close()

    flujo = Flujo(sock)

    # Descartar cabeceras HTTP de la respuesta
    cab = b""
    while b"\r\n\r\n" not in cab:
        cab += flujo.read(1)
    del cab

    # Drenado inicial: descartar todo lo acumulado durante el arranque
    time.sleep(0.5)
    flujo.drenar()
    print("  Cola inicial descartada.\n")

    buffer = b""
    while len(latencias) < a.n:
        trozo = flujo.read(65536)
        if not trozo:
            break
        buffer += trozo
        # Quedarse siempre con lo mas reciente: si mientras se procesaba
        # llegaron mas datos, se incorporan antes de medir.
        buffer += flujo.drenar()

        # DRENAR TODOS los cuadros completos que haya en el buffer.
        #
        # Este bucle interno es imprescindible y su ausencia fue un fallo
        # real de este programa. Una lectura puede traer mas de un cuadro;
        # si solo se extrae uno por lectura, el consumidor va mas lento que
        # el productor y el buffer crece sin limite. La latencia medida
        # entonces no es la del enlace, sino la de la cola que uno mismo
        # esta formando: crecia de 67 ms a mas de 1200 ms en cuatro
        # segundos, en bucle local.
        #
        # Es un error clasico al analizar flujos y conviene senalarlo: el
        # instrumento de medicion introducia el retardo que pretendia medir.
        while len(latencias) < a.n:
            fin = buffer.find(b"\r\n\r\n")
            if fin < 0:
                break
            cabecera = buffer[:fin].decode("latin-1", "ignore")
            m_len = re.search(r"Content-Length:\s*(\d+)", cabecera)
            m_cap = re.search(r"X-Captura:\s*([\d.]+)", cabecera)
            if not (m_len and m_cap):
                buffer = buffer[fin + 4:]
                continue

            largo = int(m_len.group(1))
            inicio = fin + 4
            if len(buffer) < inicio + largo:
                break          # el cuadro aun no llego completo

            t_llegada = time.perf_counter()
            t_captura_pi = float(m_cap.group(1))
            # Pasar el sello de la Pi a la referencia de la computadora
            t_captura_pc = t_captura_pi - desfase
            buffer = buffer[inicio + largo:]

            # DESCARTE DEL TRANSITORIO DE ARRANQUE
            #
            # Al abrir el flujo, los buffers de la pila HTTP y del socket ya
            # contienen cuadros producidos antes de que el lector arrancara.
            # Medirlos da latencias de mas de un segundo que despues decrecen
            # a medida que el cliente drena esa cola inicial: no describen el
            # enlace, describen el arranque del propio instrumento.
            #
            # Un reproductor de video real tiene el mismo transitorio y lo
            # resuelve descartando cuadros viejos. Aqui se descartan los
            # primeros y se mide el regimen permanente.
            descartados[0] += 1
            if descartados[0] <= a.calentamiento:
                continue

            latencias.append((t_llegada - t_captura_pc) * 1000.0)
            tamanos.append(largo)
            t_llegadas.append(t_llegada)

            if len(latencias) % 30 == 0:
                print("  {}/{} cuadros".format(len(latencias), a.n))

    flujo.close()

    if not latencias:
        print("\n  No se recibio ningun cuadro completo.")
        return

    lat = sorted(latencias)
    p50 = statistics.median(lat)
    p95 = lat[min(int(0.95 * len(lat)), len(lat) - 1)]
    p99 = lat[min(int(0.99 * len(lat)), len(lat) - 1)]

    duracion = t_llegadas[-1] - t_llegadas[0]
    fps = (len(latencias) - 1) / duracion if duracion > 0 else 0
    tam_medio = statistics.mean(tamanos)
    mbps = fps * tam_medio * 8 / 1e6

    print("\n" + "=" * 66)
    print("  RESULTADOS")
    print("=" * 66)
    print("  Cuadros medidos    : {}".format(len(lat)))
    print("  Cuadros por segundo: {:7.1f}".format(fps))
    print("  Tamano medio       : {:7.0f} bytes".format(tam_medio))
    print("  Ancho de banda     : {:7.2f} Mbit/s".format(mbps))
    print()
    print("  Latencia minima    : {:7.1f} ms".format(min(lat)))
    print("  Mediana (p50)      : {:7.1f} ms".format(p50))
    print("  Percentil 95       : {:7.1f} ms".format(p95))
    print("  Percentil 99       : {:7.1f} ms".format(p99))
    print("  Maxima             : {:7.1f} ms".format(max(lat)))

    # Deteccion de acumulacion: si la latencia crece de forma sostenida, el
    # consumidor va mas lento que el productor y lo que se mide es la cola.
    mitad = len(latencias) // 2
    if mitad >= 5:
        deriva = statistics.mean(latencias[mitad:]) - statistics.mean(latencias[:mitad])
        if deriva > 50:
            print("\n  AVISO: LA LATENCIA CRECE {:.0f} ms ENTRE LA PRIMERA Y LA".format(deriva))
            print("  SEGUNDA MITAD DE LA MEDICION. Hay acumulacion: el consumidor")
            print("  no alcanza al productor y lo medido incluye una cola propia.")
            print("  Baje los fps o la resolucion, o revise si la Pi esta saturada.")
            print("  Un flujo estable da una deriva cercana a cero.")

    print("\n  DESCOMPOSICION APROXIMADA")
    espera = 1000.0 / fps if fps > 0 else 0
    print("  Espera al siguiente cuadro (1/fps) : {:7.1f} ms".format(espera))
    print("  Resto (captura, JPEG, red, decod.) : {:7.1f} ms".format(
        max(p50 - espera, 0)))
    print("  La espera al siguiente cuadro suele ser el componente dominante.")
    print("  Por eso SUBIR los fps reduce la latencia, mientras el enlace no")
    print("  se sature. Es el resultado contraintuitivo del Modulo 1, ahora")
    print("  medido en lugar de estimado.")

    # ---------------- Presupuesto total ----------------
    total_p95 = p95
    if a.control:
        try:
            with open(a.control, encoding="utf-8") as f:
                ctrl = sorted(float(l.split(",")[1])
                              for l in f.readlines()[1:] if "," in l)
            if ctrl:
                c95 = ctrl[min(int(0.95 * len(ctrl)), len(ctrl) - 1)]
                total_p95 = p95 + c95
                print("\n  PRESUPUESTO TOTAL DE RNF-02")
                print("  " + "-" * 50)
                print("  Latencia de video      (p95): {:7.1f} ms".format(p95))
                print("  Lazo de control        (p95): {:7.1f} ms".format(c95))
                print("  " + "-" * 50)
                print("  TOTAL que percibe el operador: {:7.1f} ms".format(
                    total_p95))
        except OSError:
            print("\n  No se pudo leer {}".format(a.control))

    print("\n  Requisito RNF-02: p95 < {:.0f} ms".format(a.requisito))
    print("  VEREDICTO       : " +
          ("CUMPLE" if total_p95 < a.requisito else "NO CUMPLE"))

    if total_p95 >= a.requisito:
        print("\n  QUE PROBAR ANTES DE RENEGOCIAR EL REQUISITO")
        print("    1. Subir los fps: reduce la espera al siguiente cuadro.")
        print("    2. Bajar la resolucion o la calidad JPEG: menos bytes por")
        print("       cuadro, menos tiempo de transmision.")
        print("    3. Verificar que la Pi no este saturada: si el fps real")
        print("       queda por debajo del pedido, el cuello es el procesador,")
        print("       no la red, y ninguna mejora de enlace va a ayudar.")

    with open(a.csv, "w", encoding="utf-8") as f:
        f.write("cuadro,latencia_ms,bytes\n")
        for k, (v, b) in enumerate(zip(latencias, tamanos), 1):
            f.write("{},{:.2f},{}\n".format(k, v, b))
    print("\n  Mediciones en: {}".format(a.csv))


if __name__ == "__main__":
    main()
