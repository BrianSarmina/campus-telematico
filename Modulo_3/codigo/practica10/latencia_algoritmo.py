"""Latencia del algoritmo de deteccion ante una rampa termica - Practica 10.

Corre deteccion.py, el archivo REAL del nodo (Modulo 1), con rampas de
temperatura sinteticas y el periodo de muestreo del nodo en estado normal
(5 s mas 0.17 s de lectura de sensores). Mide el tiempo desde que empieza la
rampa hasta la primera muestra en VIGILANCIA.

No incluye la respuesta fisica del sensor ni la red: es solo lo que cuesta
el ALGORITMO. Sirve para explicar el resultado de la prueba de RNF-01 con la
secadora (descomponer_alarma.py), cuyo tramo "sensor y pendiente" mezcla la
fisica y la ventana de 60 s de la pendiente.

QUE SE VA A VER
  - La persistencia de 6 s se evalua en las muestras: hacen falta tres
    muestras seguidas sobre el umbral, separadas por 6 s o mas. Con un
    periodo de 5.17 s eso son 2 periodos = 10.34 s, no 6.
  - La pendiente se estima por regresion sobre 60 s: tarda en reconocer una
    rampa que acaba de empezar.

Uso:
    python latencia_algoritmo.py
    python latencia_algoritmo.py --periodo 1.17     # muestreo de 1 s
"""
import argparse
import os
import random
import statistics
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
M1 = os.environ.get("CAMPUS_MODULO1", os.path.normpath(
    os.path.join(AQUI, "..", "..", "..", "Modulo_1", "codigo", "practica04")))
sys.path.insert(0, os.path.join(M1, "nodo_detector"))
import deteccion as d  # noqa: E402


def latencia(rampa_c_min, periodo, fase, semilla):
    rng = random.Random(semilla)
    det = d.Detector()
    t0 = 120.0 + fase
    t = 0.0
    while t < 600:
        temp = 23.0 + rng.gauss(0, 0.05) + rampa_c_min / 60.0 * max(0.0, t - t0)
        r = det.evaluar(t, temp, 320, 95)
        if t >= t0 and r["estado"] >= d.VIGILANCIA:
            return t - t0
        t += periodo
    return None


def main():
    ap = argparse.ArgumentParser(description="Latencia del algoritmo")
    ap.add_argument("--periodo", type=float, default=5.17,
                    help="segundos entre muestras (5 s + 0.17 s de lectura)")
    ap.add_argument("--repeticiones", type=int, default=40)
    a = ap.parse_args()
    print("Algoritmo del Modulo 1: umbral {} C/min, persistencia {} s,".format(
        d.UMBRAL_DTEMP_SUBIDA, d.PERSISTENCIA_TERMICO_S))
    print("ventana de 60 s. Muestreo cada {} s. {} fases al azar.\n".format(
        a.periodo, a.repeticiones))
    print("{:>16} {:>10} {:>10} {:>10}".format(
        "Rampa (C/min)", "mediana", "minimo", "maximo"))
    for rampa in (6, 12, 30, 60, 120):
        v = [latencia(rampa, a.periodo, random.Random(k).uniform(0, a.periodo), k)
             for k in range(a.repeticiones)]
        v = [x for x in v if x is not None]
        print("{:>16} {:>9.1f}s {:>9.1f}s {:>9.1f}s".format(
            rampa, statistics.median(v), min(v), max(v)))
    n = -(-d.PERSISTENCIA_TERMICO_S // a.periodo)
    print("\nPersistencia efectiva: {:.0f} periodos x {} s = {:.2f} s".format(
        n, a.periodo, n * a.periodo))
    print("La rampa real de la secadora en el sensor NO se conoce: la")
    print("prueba de la Practica 10 la mide indirectamente.")


if __name__ == "__main__":
    main()
