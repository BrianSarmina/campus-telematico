"""Escenario fisico del banco de pruebas: que "miden" los sensores simulados.

Lo usan machine.py (MQ-2 y D0 de la flama) y bme280.py (temperatura). Se
configura con variables de entorno, una por proceso de nodo:

    BANCO_ESCENARIO   normal | secadora | flama | incendio   (normal)
    BANCO_INICIO_S    segundos desde el arranque del nodo en que empieza el
                      estimulo (30)
    BANCO_SEMILLA     semilla del ruido (el ID del nodo si no se da)

Los valores son ILUSTRATIVOS: reproducen la forma de cada estimulo para
ejercitar el firmware, no la fisica de un sensor real.
"""
import math
import os
import random
import time

T0 = time.perf_counter()
ESCENARIO = os.environ.get("BANCO_ESCENARIO", "normal")
INICIO_S = float(os.environ.get("BANCO_INICIO_S", "30"))
_rng = random.Random(int(os.environ.get("BANCO_SEMILLA", "1")))

# Marca en la bitacora del nodo el instante exacto del estimulo. En el
# laboratorio ese instante lo marca la persona con Enter; en el banco lo
# marca esta linea (practica10/descomponer_alarma.py --marca-banco).
if ESCENARIO != "normal":
    import threading
    _m = threading.Timer(INICIO_S, lambda: print(
        "[banco] estimulo {}".format(ESCENARIO), flush=True))
    _m.daemon = True
    _m.start()


def ahora():
    return time.perf_counter() - T0


def temperatura():
    t = ahora() - INICIO_S
    base = 23.0 + _rng.gauss(0, 0.05)
    if ESCENARIO in ("secadora", "incendio") and t > 0:
        # Rampa de 0.2 C/s durante 60 s; despues se enfria con tau = 60 s
        if t < 60:
            return base + 0.2 * t
        return base + 12.0 * math.exp(-(t - 60) / 60.0)
    return base


def humo_adc():
    t = ahora() - INICIO_S
    base = 320 + _rng.gauss(0, 10)
    if ESCENARIO == "incendio" and t > 0:
        return int(min(4095, base + min(t * 40, 2500)))
    return int(base)


def flama_activa():
    t = ahora() - INICIO_S
    if ESCENARIO == "incendio" and t > 0:
        return True
    if ESCENARIO == "flama" and 0 < t < 20:
        return True
    return False
