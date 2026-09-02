"""Nodo detector de incendios - Modulo 1, Practica 4. MicroPython sobre ESP32.

Lee tres sensores, decide localmente si hay un evento y transmite por
radiofrecuencia una trama binaria de 18 bytes.

ARCHIVOS QUE DEBEN ESTAR EN EL DISPOSITIVO
    bme280.py      controlador del sensor de temperatura
    deteccion.py   algoritmo multicriterio
    formato_trama.py  contrato de la trama
    nrf24l01.py    controlador de la radio (ver LEEME para obtenerlo)
    config.py      credenciales y parametros
    main.py        este archivo

CONEXIONADO

    BME280 (I2C)          ESP32
    ------------          -----
    VCC            ->     3V3
    GND            ->     GND
    SCL            ->     GPIO22
    SDA            ->     GPIO21

    MQ-2 (analogico)      ESP32
    ----------------      -----
    VCC            ->     5V (VIN)   el calefactor necesita 5 V
    GND            ->     GND
    AO             ->     GPIO34     entrada solo-lectura, ideal para ADC

    Sensor de flama IR    ESP32
    ------------------    -----
    VCC            ->     3V3
    GND            ->     GND
    AO             ->     GPIO35     entrada solo-lectura

    nRF24L01              ESP32
    --------              -----
    GND            ->     GND
    VCC            ->     3.3 V DEL REGULADOR EXTERNO (ver advertencia)
    CE             ->     GPIO27
    CSN            ->     GPIO26
    SCK            ->     GPIO25
    MOSI           ->     GPIO33
    MISO           ->     GPIO32
    IRQ            ->     sin conectar

ADVERTENCIA DE ALIMENTACION
    El nRF24L01 debe alimentarse de un regulador AMS1117-3.3 independiente,
    con capacitores de 10 uF y 100 nF entre VCC y GND lo mas cerca posible
    del modulo. Alimentarlo del pin 3V3 del ESP32 produce fallos
    intermitentes que parecen errores de codigo y no lo son.

ADVERTENCIA DEL MQ-2
    El sensor necesita 24 a 48 horas de precalentamiento inicial la primera
    vez que se energiza, y unos 60 segundos cada arranque posterior. Antes de
    eso sus lecturas no son fiables. El nodo lo indica con la bandera
    PRECALENTANDO y el concentrador la propaga.
"""
import machine
import utime
import ubinascii

from nrf24l01 import NRF24L01
import bme280
import deteccion
import formato_trama as ft

try:
    from config import ID_NODO, PERIODO_S, CANAL_RF, DIRECCION, PRECALENTADO_S
except ImportError:
    ID_NODO = 1
    PERIODO_S = 5
    CANAL_RF = 76
    DIRECCION = b"FUEGO"
    PRECALENTADO_S = 60

# ----------------------------- Pines --------------------------------
PIN_SCL, PIN_SDA = 22, 21
PIN_MQ2, PIN_FLAMA = 34, 35
PIN_CE, PIN_CSN = 27, 26
PIN_SCK, PIN_MOSI, PIN_MISO = 25, 33, 32
PIN_LED = 2

led = machine.Pin(PIN_LED, machine.Pin.OUT)


def parpadear(veces=1, ms=60):
    for _ in range(veces):
        led.value(1); utime.sleep_ms(ms)
        led.value(0); utime.sleep_ms(ms)


def iniciar_sensores():
    i2c = machine.I2C(0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA),
                      freq=100000)
    print("Dispositivos I2C:", [hex(d) for d in i2c.scan()])
    sensor = bme280.BME280(i2c=i2c)

    # ADC de 12 bits (0..4095) con atenuacion de 11 dB para leer hasta ~3.3 V
    mq2 = machine.ADC(machine.Pin(PIN_MQ2))
    mq2.atten(machine.ADC.ATTN_11DB)
    mq2.width(machine.ADC.WIDTH_12BIT)

    flama = machine.ADC(machine.Pin(PIN_FLAMA))
    flama.atten(machine.ADC.ATTN_11DB)
    flama.width(machine.ADC.WIDTH_12BIT)

    return sensor, mq2, flama


def iniciar_radio():
    spi = machine.SoftSPI(sck=machine.Pin(PIN_SCK),
                          mosi=machine.Pin(PIN_MOSI),
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


def main():
    print("\n=== Nodo detector {} ===".format(ID_NODO))
    parpadear(1, 200)

    sensor, mq2, flama = iniciar_sensores()
    print("Sensores listos.")

    radio = iniciar_radio()
    print("Radio lista. Canal {}, direccion {}".format(CANAL_RF, DIRECCION))

    detector = deteccion.Detector()
    secuencia = 0
    fallos_tx = 0
    flags_base = ft.FLAG_REINICIO
    t_arranque = utime.ticks_ms()

    print("\nPrecalentando el MQ-2 durante {} s...".format(PRECALENTADO_S))
    print("Las lecturas de humo no son fiables hasta que termine.\n")

    while True:
        t_s = utime.ticks_diff(utime.ticks_ms(), t_arranque) / 1000.0
        flags = flags_base

        # ---------------- Lectura de sensores ----------------
        try:
            temp, presion, humedad = sensor.leer()
        except OSError as e:
            print("Fallo del sensor termico:", e)
            temp, presion, humedad = 0.0, 0.0, 0.0
            flags |= ft.FLAG_TERMICO_FALLA

        humo_adc = promediar_adc(mq2)
        flama_adc = promediar_adc(flama)

        precalentando = t_s < PRECALENTADO_S
        if precalentando:
            flags |= ft.FLAG_PRECALENTANDO

        # ---------------- Decision en el borde ----------------
        # Durante el precalentamiento se evalua solo el canal termico:
        # forzar el humo a su linea base evita alarmas espurias.
        r = detector.evaluar(
            t_s, temp,
            detector.base_humo if (precalentando and detector.base_humo)
            else humo_adc,
            flama_adc)

        estado = r["estado"]

        # ---------------- Transmision ----------------
        trama = ft.empaquetar(ID_NODO, secuencia, temp, humedad, presion,
                              humo_adc, flama_adc, r["dtemp"], estado, flags)

        led.value(1)
        try:
            radio.send(trama)
            entregado = True
            flags_base &= ~ft.FLAG_REINICIO   # ya se anuncio el reinicio
        except OSError:
            entregado = False
            fallos_tx += 1
        led.value(0)

        ind = r["indicadores"]
        print("[{:04d}] {:5.1f} C  d={:+5.2f} C/min  humo={:4d}  flama={:4d}"
              "  {:<10} T{}H{}F{}  {}".format(
                  secuencia, temp, r["dtemp"], humo_adc, flama_adc,
                  r["nombre"],
                  1 if ind["termico"] else 0,
                  1 if ind["humo"] else 0,
                  1 if ind["flama"] else 0,
                  "ACK" if entregado else "SIN ACK"))

        secuencia += 1

        # ---------------- Periodo adaptativo ----------------
        # En estado normal se transmite cada PERIODO_S. Durante un evento se
        # acelera a 1 s: la alarma necesita latencia baja y ese es el momento
        # en que el trafico rutinario deja de importar.
        # Esta decision es la que hace que RNF-01 sea alcanzable.
        if estado >= deteccion.PREALARMA:
            utime.sleep(1)
        elif estado == deteccion.VIGILANCIA:
            utime.sleep(2)
        else:
            utime.sleep(PERIODO_S)


main()
