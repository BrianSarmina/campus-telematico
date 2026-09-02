"""Concentrador de radiofrecuencia - Modulo 1, Practica 4. MicroPython/ESP32.

Es el gateway del sistema. Su funcion es la que define a un gateway
telematico: TRADUCIR entre dos dominios con reglas distintas.

    Entrada : tramas binarias de 18 bytes por nRF24L01 (dominio restringido)
    Salida  : lineas JSON por USB serie hacia la PC (dominio de la plataforma)

Ademas aporta lo que el nodo no puede:
    - marca de tiempo, que el nodo no tiene
    - deteccion de perdidas y desorden por numero de secuencia
    - conteo de la tasa de entrega, dato con el que se verifica RNF-03

ARCHIVOS QUE DEBEN ESTAR EN EL DISPOSITIVO
    nrf24l01.py       controlador de la radio
    formato_trama.py  contrato de la trama (el MISMO archivo que en el nodo)
    config.py
    main.py           este archivo

CONEXIONADO
    nRF24L01          ESP32
    --------          -----
    GND        ->     GND
    VCC        ->     3.3 V del regulador externo, con capacitores
    CE         ->     GPIO27
    CSN        ->     GPIO26
    SCK        ->     GPIO25
    MOSI       ->     GPIO33
    MISO       ->     GPIO32

IMPORTANTE SOBRE LA SALIDA
Todo lo que este programa imprime va al mismo puerto USB que lee el puente
en la PC. Por eso cada mensaje se emite como UNA linea de JSON valido. Los
mensajes que no son datos llevan la clave "evento" para que el puente los
distinga y no intente publicarlos como telemetria.
"""
import machine
import ujson
import utime

from nrf24l01 import NRF24L01
import formato_trama as ft

try:
    from config import CANAL_RF, DIRECCION, LATIDO_S
except ImportError:
    CANAL_RF, DIRECCION, LATIDO_S = 76, b"FUEGO", 30

PIN_CE, PIN_CSN = 27, 26
PIN_SCK, PIN_MOSI, PIN_MISO = 25, 33, 32
PIN_LED = 2

led = machine.Pin(PIN_LED, machine.Pin.OUT)

# Estado por nodo para la deteccion de perdidas
ultima_seq = {}
recibidos = {}
perdidos = {}


def iniciar_radio():
    spi = machine.SoftSPI(sck=machine.Pin(PIN_SCK),
                          mosi=machine.Pin(PIN_MOSI),
                          miso=machine.Pin(PIN_MISO))
    csn = machine.Pin(PIN_CSN, mode=machine.Pin.OUT, value=1)
    ce = machine.Pin(PIN_CE, mode=machine.Pin.OUT, value=0)

    radio = NRF24L01(spi, csn, ce, channel=CANAL_RF, payload_size=ft.TAMANO)
    radio.open_rx_pipe(1, DIRECCION)
    radio.start_listening()
    return radio


def contabilizar(mensaje):
    """Detecta perdidas y desorden por numero de secuencia.

    En un medio compartido sin deteccion de portadora las colisiones son
    inevitables. Esta cuenta es la unica forma de saber cuantas hubo, y es
    el dato con el que se verifica el requisito RNF-03.
    """
    nodo = mensaje["nodo"]
    seq = mensaje["secuencia"]

    recibidos[nodo] = recibidos.get(nodo, 0) + 1
    anterior = ultima_seq.get(nodo)

    if anterior is not None:
        salto = (seq - anterior) & 0xFFFF
        if salto == 0:
            mensaje["diag"]["duplicado"] = True
        elif salto > 1:
            perdidos[nodo] = perdidos.get(nodo, 0) + (salto - 1)

    ultima_seq[nodo] = seq
    total = recibidos[nodo] + perdidos.get(nodo, 0)
    mensaje["diag"]["recibidos"] = recibidos[nodo]
    mensaje["diag"]["perdidos"] = perdidos.get(nodo, 0)
    mensaje["diag"]["tasa_entrega"] = round(recibidos[nodo] / total, 4)
    return mensaje


def main():
    radio = iniciar_radio()
    print(ujson.dumps({"evento": "concentrador_listo",
                       "canal": CANAL_RF,
                       "tamano_trama": ft.TAMANO}))

    ultimo_latido = utime.ticks_ms()

    while True:
        if radio.any():
            while radio.any():
                trama = radio.recv()
                try:
                    mensaje = ft.desempaquetar(trama)
                except Exception as e:
                    print(ujson.dumps({"evento": "trama_invalida",
                                       "detalle": str(e)}))
                    continue

                # La marca de tiempo la pone el receptor, no el origen.
                # Es un contador desde el arranque, no una hora absoluta:
                # el puente en la PC lo sustituye por una marca UTC real.
                mensaje["ts_rx_ms"] = utime.ticks_ms()
                mensaje = contabilizar(mensaje)

                # Un parpadeo por trama normal, tres si viene un evento.
                if mensaje["estado_num"] >= 2:
                    for _ in range(3):
                        led.value(1); utime.sleep_ms(30)
                        led.value(0); utime.sleep_ms(30)
                else:
                    led.value(1); utime.sleep_ms(15); led.value(0)

                print(ujson.dumps(mensaje))

        # Latido: permite al puente distinguir "no hay nodos transmitiendo"
        # de "el concentrador se colgo". Sin esto, ambos casos se ven igual.
        if utime.ticks_diff(utime.ticks_ms(), ultimo_latido) > LATIDO_S * 1000:
            print(ujson.dumps({
                "evento": "latido",
                "nodos": len(recibidos),
                "recibidos": sum(recibidos.values()),
                "perdidos": sum(perdidos.values()),
            }))
            ultimo_latido = utime.ticks_ms()

        utime.sleep_ms(20)


main()
