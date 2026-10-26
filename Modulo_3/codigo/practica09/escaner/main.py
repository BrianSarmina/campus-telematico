"""Escaner de espectro con el nRF24L01+ - Modulo 3, Practica 9. MicroPython.

Se carga EN EL CONCENTRADOR en lugar de su main.py, solo durante el paso del
escaner, y despues se restaura el del concentrador.

QUE MIDE
El nRF24L01+ tiene un registro de un bit, RPD (Received Power Detector,
0x09): vale 1 si, con el radio en recepcion, entra al canal una potencia
mayor que -64 dBm. Barriendo los 126 canales (2400 a 2525 MHz) y repitiendo
la lectura muchas veces por canal, la fraccion de lecturas en 1 estima que
parte del tiempo el canal esta ocupado por una senal fuerte.

LIMITES QUE HAY QUE DECLARAR
  - Umbral fijo de -64 dBm: una senal mas debil no se ve. No es un analizador
    de espectro; es un detector de "ocupado por algo cercano".
  - Solo existe en el nRF24L01+ (con la marca "+"). En el nRF24L01 original
    el registro 0x09 es CD, con otro umbral y otro significado.
  - Cada lectura dura unos cientos de microsegundos: una trama Wi-Fi corta
    puede caer entre dos lecturas. La fraccion es una estimacion.

PROCEDIMIENTO DE LECTURA (hoja de datos del nRF24L01+)
  CE = 1 (recepcion) -> esperar 130 us de arranque + 40 us de AGC
  -> leer RPD -> CE = 0. Al bajar CE el registro se borra.

SALIDA: una linea JSON por barrido, que lee practica09/ver_espectro.py
  {"evento": "espectro", "barrido": 3, "muestras": 60, "cuentas": [...126...]}

Archivos en el dispositivo: nrf24l01.py (Modulo 1) y este main.py.
    mpremote connect COM4 fs cp escaner/main.py :main.py
"""
import machine
import ujson
import utime

from nrf24l01 import NRF24L01

PIN_CE, PIN_CSN = 27, 26
PIN_SCK, PIN_MOSI, PIN_MISO = 25, 33, 32

RF_CH = 0x05
RPD = 0x09
CANALES = 126
MUESTRAS = 60          # lecturas por canal y por barrido
ESPERA_US = 200        # >= 170 us que exige la hoja de datos


def main():
    spi = machine.SoftSPI(sck=machine.Pin(PIN_SCK), mosi=machine.Pin(PIN_MOSI),
                          miso=machine.Pin(PIN_MISO))
    csn = machine.Pin(PIN_CSN, mode=machine.Pin.OUT, value=1)
    ce = machine.Pin(PIN_CE, mode=machine.Pin.OUT, value=0)
    radio = NRF24L01(spi, csn, ce, channel=0, payload_size=32)
    radio.open_rx_pipe(1, b"ESCAN")
    radio.start_listening()          # PWR_UP y PRIM_RX; deja CE en 1
    ce(0)
    print(ujson.dumps({"evento": "escaner_listo", "canales": CANALES,
                       "muestras": MUESTRAS, "umbral_dbm": -64}))
    barrido = 0
    while True:
        t0 = utime.ticks_ms()
        cuentas = []
        for canal in range(CANALES):
            radio.reg_write(RF_CH, canal)
            n = 0
            for _ in range(MUESTRAS):
                ce(1)
                utime.sleep_us(ESPERA_US)
                n += radio.reg_read(RPD) & 1
                ce(0)
            cuentas.append(n)
        print(ujson.dumps({"evento": "espectro", "barrido": barrido,
                           "muestras": MUESTRAS, "cuentas": cuentas,
                           "duracion_ms": utime.ticks_diff(utime.ticks_ms(), t0)}))
        barrido += 1


main()
