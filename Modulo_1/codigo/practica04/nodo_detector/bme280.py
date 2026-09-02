"""Controlador BME280 para MicroPython - Practica 4.

Sensor Bosch BME280: temperatura, presion y humedad relativa por I2C.
Implementa la compensacion en punto flotante descrita en la hoja de datos
(seccion 4.2.3). Se usa la version flotante y no la entera porque el ESP32
tiene unidad de punto flotante y el codigo resulta mucho mas legible.

Copiar al ESP32 antes de main.py:
    mpremote connect /dev/ttyUSB0 fs cp bme280.py :bme280.py

Uso:
    from machine import I2C, Pin
    import bme280
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
    sensor = bme280.BME280(i2c=i2c)
    t, p, h = sensor.leer()          # grados C, hPa, % HR
"""
import time
from ustruct import unpack, unpack_from

# Direcciones I2C posibles. El modulo GY-BME280 suele venir en 0x76.
DIR_PRINCIPAL = 0x76
DIR_ALTERNA = 0x77

# Registros
REG_ID = 0xD0
REG_RESET = 0xE0
REG_CTRL_HUM = 0xF2
REG_STATUS = 0xF3
REG_CTRL_MEAS = 0xF4
REG_CONFIG = 0xF5
REG_DATOS = 0xF7        # 8 bytes: presion(3) temperatura(3) humedad(2)

ID_BME280 = 0x60        # el BMP280 (sin humedad) responde 0x58

# Sobremuestreo: 1 = x1, 2 = x2, 3 = x4, 4 = x8, 5 = x16
# Mas sobremuestreo reduce el ruido pero aumenta el tiempo de conversion
# y el consumo. x1 es suficiente para telemetria ambiental.
OSS_X1 = 1
OSS_X2 = 2
OSS_X4 = 3


class BME280:

    def __init__(self, i2c, direccion=None, oss_t=OSS_X2, oss_p=OSS_X2,
                 oss_h=OSS_X2):
        self.i2c = i2c
        self.direccion = direccion if direccion is not None else self._detectar()

        chip = self.i2c.readfrom_mem(self.direccion, REG_ID, 1)[0]
        if chip == 0x58:
            raise OSError("Se detecto un BMP280 (0x58): NO mide humedad. "
                          "Verifique que el modulo sea BME280.")
        if chip != ID_BME280:
            raise OSError("ID de chip inesperado: 0x{:02X}. "
                          "Revise el cableado I2C.".format(chip))

        self._leer_calibracion()

        # ctrl_hum debe escribirse ANTES que ctrl_meas: el cambio no surte
        # efecto hasta que se escribe ctrl_meas. Es el error mas comun al
        # implementar este sensor desde cero.
        self.i2c.writeto_mem(self.direccion, REG_CTRL_HUM, bytes([oss_h]))
        # modo 3 = normal (medicion continua)
        ctrl_meas = (oss_t << 5) | (oss_p << 2) | 3
        self.i2c.writeto_mem(self.direccion, REG_CTRL_MEAS, bytes([ctrl_meas]))
        # config: t_standby 500 ms, filtro IIR x4
        self.i2c.writeto_mem(self.direccion, REG_CONFIG, bytes([(4 << 5) | (2 << 2)]))
        time.sleep_ms(100)

        self.t_fine = 0.0

    def _detectar(self):
        dispositivos = self.i2c.scan()
        for direccion in (DIR_PRINCIPAL, DIR_ALTERNA):
            if direccion in dispositivos:
                return direccion
        raise OSError("No se encontro un BME280 en 0x76 ni 0x77. "
                      "Dispositivos en el bus: {}".format(
                          [hex(d) for d in dispositivos]))

    def _leer_calibracion(self):
        """Lee los coeficientes de fabrica grabados en el sensor."""
        cal1 = self.i2c.readfrom_mem(self.direccion, 0x88, 26)
        cal2 = self.i2c.readfrom_mem(self.direccion, 0xE1, 7)

        (self.dig_T1, self.dig_T2, self.dig_T3,
         self.dig_P1, self.dig_P2, self.dig_P3, self.dig_P4, self.dig_P5,
         self.dig_P6, self.dig_P7, self.dig_P8, self.dig_P9,
         _, self.dig_H1) = unpack("<HhhHhhhhhhhhBB", cal1)

        self.dig_H2, self.dig_H3 = unpack_from("<hB", cal2, 0)
        e4, e5, e6 = cal2[3], cal2[4], cal2[5]
        self.dig_H4 = (e4 << 4) | (e5 & 0x0F)
        if self.dig_H4 > 2047:
            self.dig_H4 -= 4096
        self.dig_H5 = (e6 << 4) | (e5 >> 4)
        if self.dig_H5 > 2047:
            self.dig_H5 -= 4096
        self.dig_H6 = unpack_from("<b", cal2, 6)[0]

    def leer(self):
        """Devuelve (temperatura_C, presion_hPa, humedad_%HR) como flotantes."""
        d = self.i2c.readfrom_mem(self.direccion, REG_DATOS, 8)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        adc_h = (d[6] << 8) | d[7]

        # ---------------- Temperatura (hoja de datos 4.2.3) ----------------
        var1 = (adc_t / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        var2 = ((adc_t / 131072.0 - self.dig_T1 / 8192.0) ** 2) * self.dig_T3
        self.t_fine = var1 + var2
        temperatura = self.t_fine / 5120.0

        # ---------------- Presion ----------------
        var1 = self.t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.dig_P6 / 32768.0
        var2 = var2 + var1 * self.dig_P5 * 2.0
        var2 = var2 / 4.0 + self.dig_P4 * 65536.0
        var1 = (self.dig_P3 * var1 * var1 / 524288.0 + self.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.dig_P1

        if var1 == 0.0:
            presion = 0.0                    # evita division entre cero
        else:
            p = 1048576.0 - adc_p
            p = (p - var2 / 4096.0) * 6250.0 / var1
            var1 = self.dig_P9 * p * p / 2147483648.0
            var2 = p * self.dig_P8 / 32768.0
            presion = (p + (var1 + var2 + self.dig_P7) / 16.0) / 100.0   # Pa -> hPa

        # ---------------- Humedad ----------------
        h = self.t_fine - 76800.0
        h = ((adc_h - (self.dig_H4 * 64.0 + self.dig_H5 / 16384.0 * h)) *
             (self.dig_H2 / 65536.0 * (1.0 + self.dig_H6 / 67108864.0 * h *
              (1.0 + self.dig_H3 / 67108864.0 * h))))
        h = h * (1.0 - self.dig_H1 * h / 524288.0)
        humedad = max(0.0, min(100.0, h))

        return temperatura, presion, humedad

    def altitud(self, presion_nivel_mar=1013.25):
        """Altitud estimada por la formula barometrica internacional.

        Util para validar la lectura: en Cuautitlan Izcalli (~2250 m) la
        presion debe rondar 770-785 hPa. Si el sensor reporta ~1013 hPa
        esta devolviendo un valor por omision, no una medida real.
        """
        _, presion, _ = self.leer()
        return 44330.0 * (1.0 - (presion / presion_nivel_mar) ** 0.1903)

    def __repr__(self):
        return "BME280(direccion=0x{:02X})".format(self.direccion)
