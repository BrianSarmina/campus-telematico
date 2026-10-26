"""machine de MicroPython sobre CPython, para el banco de pruebas.

Solo implementa lo que usan el nodo, el concentrador y el escaner. Los
valores de los sensores salen de escenario.py.

Si existe BANCO_ARRANQUE (instante absoluto de time.perf_counter), el
proceso espera hasta ese instante al importar este modulo: varios nodos
arrancan a la vez, como tras un corte de energia.
"""
import os
import time

import escenario

_t = os.environ.get("BANCO_ARRANQUE")
if _t:
    while time.perf_counter() < float(_t):
        time.sleep(0.0002)

# Pines con significado en el firmware
_PIN_MQ2 = 34
_PIN_FLAMA = 35
_NIVEL_ACTIVO_FLAMA = int(os.environ.get("BANCO_FLAMA_NIVEL_ACTIVO", "0"))


class Pin:
    IN, OUT, OPEN_DRAIN = 1, 3, 7
    PULL_UP, PULL_DOWN = 1, 2

    def __init__(self, ident, mode=-1, pull=-1, value=None):
        self.id = ident
        self._v = 0 if value is None else value

    def init(self, mode=-1, pull=-1, value=None):
        if value is not None:
            self._v = value

    def value(self, v=None):
        if v is not None:
            self._v = v
            return None
        if self.id == _PIN_FLAMA:
            activa = escenario.flama_activa()
            return _NIVEL_ACTIVO_FLAMA if activa else 1 - _NIVEL_ACTIVO_FLAMA
        return self._v

    def __call__(self, v=None):
        return self.value(v)

    def on(self):
        self._v = 1

    def off(self):
        self._v = 0


class ADC:
    ATTN_0DB, ATTN_2_5DB, ATTN_6DB, ATTN_11DB = 0, 1, 2, 3
    WIDTH_9BIT, WIDTH_10BIT, WIDTH_11BIT, WIDTH_12BIT = 0, 1, 2, 3

    def __init__(self, pin, atten=None):
        self.pin = pin.id if isinstance(pin, Pin) else pin

    def atten(self, a):
        pass

    def width(self, w):
        pass

    def read(self):
        if self.pin == _PIN_MQ2:
            return escenario.humo_adc()
        return 0

    def read_u16(self):
        return self.read() << 4


class I2C:
    def __init__(self, ident=0, scl=None, sda=None, freq=400000):
        pass

    def scan(self):
        return [0x76]


class SoftSPI:
    MSB, LSB = 0, 1

    def __init__(self, *a, **k):
        pass

    def init(self, *a, **k):
        pass


SPI = SoftSPI


def unique_id():
    return os.environ.get("BANCO_ID", "banco").encode()[:6].ljust(6, b"\0")


def reset():
    os._exit(1)


def freq(f=None):
    return 240000000
