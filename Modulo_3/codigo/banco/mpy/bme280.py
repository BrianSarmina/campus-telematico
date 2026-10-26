"""Sustituto del controlador BME280 para el banco: lee escenario.py."""
import random

import escenario


class BME280:
    def __init__(self, i2c=None, direccion=None, **kw):
        self.direccion = 0x76

    def leer(self):
        """(temperatura C, presion hPa, humedad %), como el controlador real."""
        return (escenario.temperatura(),
                780.0 + random.gauss(0, 0.3),
                48.0 + random.gauss(0, 0.5))
