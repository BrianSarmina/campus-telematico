"""Nodo detector de incendios, version 3 - Modulo 3, Practicas 9 y 10.
MicroPython sobre ESP32.

Es el firmware del Modulo 1 (Practica 4) con dos cambios:

  1. Sensor de flama ILMM34020 por su salida DIGITAL D0 (no tiene AO). D0 se
     traduce a cuentas sinteticas (95 en reposo, 1200 activo) para no romper
     el formato de la trama ni los umbrales de deteccion.py.
  2. ACCESO AL MEDIO. Con POLITICA = "v3" (config.py) el nodo:
       - espera un tiempo aleatorio al arrancar (rompe la sincronia tras un
         corte de energia);
       - elige al azar el retardo de reintento (ARD) antes de cada trama
         (dos nodos que chocan no vuelven a chocar en el reintento);
       - fluctua su periodo +-10 % (rompe el agrupamiento entre tramas);
       - si el radio agota sus reintentos, reintenta por software con
         retroceso exponencial aleatorio: 1 vez la rutina, hasta 6 veces una
         transicion o una alarma (prioridad por persistencia).
     Con POLITICA = "v1" se comporta como el firmware del Modulo 1: es la
     linea base con la que se compara en la Practica 10.

La trama NO cambia: 18 bytes, mismo formato. Ver formato_trama.py.

ARCHIVOS QUE DEBEN ESTAR EN EL DISPOSITIVO
    Del Modulo 1, sin cambios: bme280.py, deteccion.py, formato_trama.py,
                               nrf24l01.py
    De este directorio:        config.py, main.py

    mpremote connect COM5 fs cp config.py :config.py
    mpremote connect COM5 fs cp main.py :main.py

CONEXIONADO (igual que el Modulo 1, salvo la flama)
    BME280 (I2C)   SCL -> GPIO22, SDA -> GPIO21, VCC -> 3V3
    MQ-2           AO  -> GPIO34, VCC -> 5 V (VIN)
    Flama ILMM34020  D0 -> GPIO35, VCC -> 3V3 (NO 5 V: D0 pondria 5 V en el pin)
    nRF24L01       CE 27, CSN 26, SCK 25, MOSI 33, MISO 32, VCC del regulador

LINEA DE BITACORA (la lee practica09/medir_enlace.py)
    [0012]  23.4 C  d=+0.02 C/min  humo= 318  flama=  95 ( 0/50)  normal  T0H0F0
           ACK int=1 sw=0 tx_us=4210 ciclo_us=5176021
  int      intentos de radio consumidos por la trama (1 = al primer intento)
  sw       reintentos por software usados
  tx_us    tiempo dentro de la transmision, en microsegundos
  ciclo_us tiempo desde el inicio de la transmision anterior (0 la primera)
"""
import machine
import os
import random
import utime

from nrf24l01 import NRF24L01
import bme280
import deteccion
import formato_trama as ft

try:
    from config import ID_NODO, PERIODO_S, CANAL_RF, DIRECCION, PRECALENTADO_S
except ImportError:
    ID_NODO, PERIODO_S, CANAL_RF, DIRECCION, PRECALENTADO_S = 1, 5, 76, b"FUEGO", 60
try:
    from config import POLITICA
except ImportError:
    POLITICA = "v3"
try:
    from config import PERIODO_FIJO_S
except ImportError:
    PERIODO_FIJO_S = None
try:
    from config import FLAMA_NIVEL_ACTIVO
except ImportError:
    FLAMA_NIVEL_ACTIVO = 0

# ----------------------------- Pines --------------------------------
PIN_SCL, PIN_SDA = 22, 21
PIN_MQ2, PIN_FLAMA = 34, 35
PIN_CE, PIN_CSN = 27, 26
PIN_SCK, PIN_MOSI, PIN_MISO = 25, 33, 32
PIN_LED = 2

# ------------------- Sensor de flama por D0 -------------------------
# El modulo solo entrega D0 (comparador LM393). La polaridad varia entre
# fabricantes: verifiquela con el modulo real (LEEME del Modulo 3).
FLAMA_REPOSO = 95           # cuentas sinteticas: se conserva el formato
FLAMA_ACTIVA = 1200         # y los umbrales de deteccion.py (600/300)
# Una sola lectura puede caer en un hueco: una flama parpadea y un control
# remoto emite rafagas. Se observa una ventana de 50 x 3 ms = 150 ms.
FLAMA_MUESTRAS = 50
FLAMA_PASO_MS = 3
FLAMA_MIN_ACTIVAS = 2       # descarta un unico pico espurio

# ------------------ Acceso al medio (Modulo 3) ----------------------
# Estos valores deben coincidir con POLITICA_V3 de practica09/medio.py;
# pruebas_modulo3.py lo comprueba.
SETUP_RETR = 0x04
OBSERVE_TX = 0x08
ARC = 8                     # reintentos automaticos del radio (el driver)
ARD_IDX_MIN = 3             # ARD = (k + 1) * 250 us: de 1000 us ...
ARD_IDX_MAX = 15            # ... a 4000 us, al azar antes de cada trama
SW_RUTINA = 1               # reintentos por software de una trama rutinaria
SW_PRIORIDAD = 6            # de una transicion o de una prealarma/alarma
ESPERA_SW_BASE_MS = 10      # retroceso: U(0, 10 * 2^i) ms antes del i-esimo
FLUCTUACION = 0.10          # el periodo se multiplica por U(0.9, 1.1)

V3 = POLITICA == "v3"

led = machine.Pin(PIN_LED, machine.Pin.OUT)


def parpadear(veces=1, ms=60):
    for _ in range(veces):
        led.value(1)
        utime.sleep_ms(ms)
        led.value(0)
        utime.sleep_ms(ms)


def sembrar_azar():
    """Semilla distinta en cada nodo y en cada arranque.

    os.urandom usa el generador de hardware del ESP32. Se mezcla con el
    identificador y el reloj por si el generador no estuviera disponible.
    Dos nodos con la misma semilla tomarian las mismas decisiones "al azar"
    y se sincronizarian igual que sin ellas.
    """
    s = int.from_bytes(os.urandom(4), "little")
    random.seed(s ^ (ID_NODO << 16) ^ utime.ticks_us())


def iniciar_sensores():
    i2c = machine.I2C(0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA),
                      freq=100000)
    print("Dispositivos I2C:", [hex(d) for d in i2c.scan()])
    sensor = bme280.BME280(i2c=i2c)
    mq2 = machine.ADC(machine.Pin(PIN_MQ2))
    mq2.atten(machine.ADC.ATTN_11DB)
    mq2.width(machine.ADC.WIDTH_12BIT)
    # GPIO34-39 no tienen resistencias de pull internas: el pull-up lo
    # pone el propio modulo en su salida D0.
    flama = machine.Pin(PIN_FLAMA, machine.Pin.IN)
    return sensor, mq2, flama


def iniciar_radio():
    spi = machine.SoftSPI(sck=machine.Pin(PIN_SCK), mosi=machine.Pin(PIN_MOSI),
                          miso=machine.Pin(PIN_MISO))
    csn = machine.Pin(PIN_CSN, mode=machine.Pin.OUT, value=1)
    ce = machine.Pin(PIN_CE, mode=machine.Pin.OUT, value=0)
    radio = NRF24L01(spi, csn, ce, channel=CANAL_RF, payload_size=ft.TAMANO)
    radio.open_tx_pipe(DIRECCION)
    radio.stop_listening()
    return radio


def promediar_adc(adc, n=8):
    """El ADC del ESP32 es ruidoso. Promediar reduce la dispersion."""
    total = 0
    for _ in range(n):
        total += adc.read()
        utime.sleep_ms(2)
    return total // n


def leer_flama(pin):
    """Ventana de muestreo sobre D0. Devuelve (cuentas sinteticas, activas)."""
    activas = 0
    for _ in range(FLAMA_MUESTRAS):
        if pin.value() == FLAMA_NIVEL_ACTIVO:
            activas += 1
        utime.sleep_ms(FLAMA_PASO_MS)
    cuentas = FLAMA_ACTIVA if activas >= FLAMA_MIN_ACTIVAS else FLAMA_REPOSO
    return cuentas, activas


def enviar(radio, trama, prioridad):
    """Transmite una trama segun la politica.

    Devuelve (entregada, intentos_de_radio, reintentos_sw, tx_us).
    'Entregada' significa que el concentrador confirmo con un acuse.
    """
    t0 = utime.ticks_us()
    sw_max = (SW_PRIORIDAD if prioridad else SW_RUTINA) if V3 else 0
    intentos = 0
    sw = 0
    while True:
        if V3:
            k = random.randint(ARD_IDX_MIN, ARD_IDX_MAX)
            radio.reg_write(SETUP_RETR, (k << 4) | ARC)
        try:
            radio.send(trama)
            # OBSERVE_TX, bits 3..0: retransmisiones que uso ESTA trama
            intentos += (radio.reg_read(OBSERVE_TX) & 0x0F) + 1
            return True, intentos, sw, utime.ticks_diff(utime.ticks_us(), t0)
        except OSError:
            intentos += ARC + 1             # MAX_RT: los agoto todos
            if sw >= sw_max:
                return False, intentos, sw, utime.ticks_diff(utime.ticks_us(), t0)
            # Retroceso exponencial aleatorio: una rafaga de Wi-Fi dura
            # milisegundos; esperar al azar decorrela el siguiente intento.
            utime.sleep_ms(random.randint(0, ESPERA_SW_BASE_MS << sw))
            sw += 1


def main():
    print("\n=== Nodo detector {}  firmware v3, politica {} ===".format(
        ID_NODO, POLITICA))
    parpadear(1, 200)
    sembrar_azar()

    sensor, mq2, flama = iniciar_sensores()
    print("Sensores listos. Flama por D0 en GPIO{}, nivel activo {}".format(
        PIN_FLAMA, FLAMA_NIVEL_ACTIVO))
    radio = iniciar_radio()
    print("Radio lista. Canal {}, direccion {}".format(CANAL_RF, DIRECCION))

    if V3:
        # Tras un corte de energia todos los nodos arrancan a la vez. Sin
        # esta espera transmitirian juntos y chocarian periodo tras periodo.
        espera = random.randint(0, int(PERIODO_S * 1000))
        print("Espera de arranque aleatoria: {} ms".format(espera))
        utime.sleep_ms(espera)

    detector = deteccion.Detector()
    secuencia = 0
    flags_base = ft.FLAG_REINICIO
    t_arranque = utime.ticks_ms()
    estado_previo = None
    t_envio_previo = None

    print("Precalentando el MQ-2 durante {} s...\n".format(PRECALENTADO_S))

    while True:
        t_s = utime.ticks_diff(utime.ticks_ms(), t_arranque) / 1000.0
        flags = flags_base

        try:
            temp, presion, humedad = sensor.leer()
        except OSError as e:
            print("Fallo del sensor termico:", e)
            temp, presion, humedad = 0.0, 0.0, 0.0
            flags |= ft.FLAG_TERMICO_FALLA

        humo_adc = promediar_adc(mq2)
        flama_adc, flama_activas = leer_flama(flama)

        precalentando = t_s < PRECALENTADO_S
        if precalentando:
            flags |= ft.FLAG_PRECALENTANDO

        # El canal digital tiene un reposo conocido y fijo: no hay linea base
        # que aprender. Fijarla evita que una flama presente en el arranque
        # quede como "base" y desactive el canal en silencio.
        detector.base_flama = float(FLAMA_REPOSO)
        r = detector.evaluar(
            t_s, temp,
            detector.base_humo if (precalentando and detector.base_humo)
            else humo_adc,
            flama_adc)
        estado = r["estado"]

        trama = ft.empaquetar(ID_NODO, secuencia, temp, humedad, presion,
                              humo_adc, flama_adc, r["dtemp"], estado, flags)

        # Prioridad: una transicion de estado o una prealarma/alarma
        transicion = estado_previo is not None and estado != estado_previo
        prioridad = transicion or estado >= deteccion.PREALARMA

        t_envio = utime.ticks_us()
        ciclo_us = (0 if t_envio_previo is None
                    else utime.ticks_diff(t_envio, t_envio_previo))
        t_envio_previo = t_envio

        led.value(1)
        entregada, intentos, sw, tx_us = enviar(radio, trama, prioridad)
        led.value(0)
        if entregada:
            flags_base &= ~ft.FLAG_REINICIO      # ya se anuncio el reinicio

        ind = r["indicadores"]
        print("[{:04d}] {:5.1f} C  d={:+5.2f} C/min  humo={:4d}  flama={:4d}"
              " ({:2d}/{})  {:<10} T{}H{}F{}  {} int={} sw={} tx_us={}"
              " ciclo_us={}".format(
                  secuencia, temp, r["dtemp"], humo_adc, flama_adc,
                  flama_activas, FLAMA_MUESTRAS, r["nombre"],
                  1 if ind["termico"] else 0, 1 if ind["humo"] else 0,
                  1 if ind["flama"] else 0,
                  "ACK" if entregada else "SIN ACK", intentos, sw, tx_us,
                  ciclo_us))

        secuencia = (secuencia + 1) & 0xFFFF
        estado_previo = estado

        # ---------------- Periodo adaptativo ----------------
        if PERIODO_FIJO_S is not None:
            periodo = PERIODO_FIJO_S
        elif estado >= deteccion.PREALARMA:
            periodo = 1
        elif estado == deteccion.VIGILANCIA:
            periodo = 2
        else:
            periodo = PERIODO_S
        if V3:
            periodo *= 1.0 + FLUCTUACION * (2.0 * random.random() - 1.0)
        utime.sleep_ms(int(periodo * 1000))


main()
