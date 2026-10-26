"""utime de MicroPython sobre CPython, para el banco de pruebas.

Los contadores se reinician con el proceso, como en un ESP32 al arrancar, y
dan la vuelta en 2^30, como en el puerto ESP32: ticks_diff lo maneja igual.
"""
import time as _t

_T0 = _t.perf_counter()
_PERIODO = 1 << 30
_MITAD = _PERIODO >> 1


def ticks_ms():
    return int((_t.perf_counter() - _T0) * 1000) & (_PERIODO - 1)


def ticks_us():
    return int((_t.perf_counter() - _T0) * 1000000) & (_PERIODO - 1)


def ticks_diff(a, b):
    return ((a - b + _MITAD) & (_PERIODO - 1)) - _MITAD


def ticks_add(a, d):
    return (a + d) & (_PERIODO - 1)


def sleep(s):
    _t.sleep(s)


def sleep_ms(ms):
    if ms > 0:
        _t.sleep(ms / 1000.0)


def sleep_us(us):
    if us > 0:
        _t.sleep(us / 1000000.0)


def time():
    return int(_t.time())
