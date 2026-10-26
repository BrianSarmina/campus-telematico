"""Concentrador de radiofrecuencia, version 3 - Modulo 3. MicroPython/ESP32.

Es el gateway del Modulo 1 (Practica 4) con la contabilidad corregida para
el firmware v3 del nodo:

  1. DUPLICADOS. El reintento por software del nodo vuelve a llamar a
     send(): para el radio es un paquete nuevo y su filtro de duplicados por
     hardware (PID) no lo descarta. Si la primera copia llego y se perdio el
     acuse, la misma secuencia llega dos veces. El concentrador la descarta y
     la cuenta; antes se publicaba dos veces.
  2. REINICIO DEL NODO. Un nodo que se reinicia vuelve a la secuencia 0. La
     version del Modulo 1 lo contaba como un salto de 65 000 tramas perdidas
     y la tasa de entrega se desplomaba sin que se hubiera perdido nada. Un
     retroceso de la secuencia se trata como reinicio, sin contar perdidas.
  3. La secuencia viaja en diag.secuencia, para que la plataforma pueda
     medir la entrega extremo a extremo (practica09/medir_enlace.py). diag
     es un objeto abierto en el ICD v1.0: agregar claves no cambia la huella.

La salida por USB sigue siendo una linea JSON por mensaje, igual que antes:
el puente serie del Modulo 1 no cambia.

ARCHIVOS EN EL DISPOSITIVO
    Del Modulo 1, sin cambios: nrf24l01.py, formato_trama.py
    De este directorio:        config.py, main.py
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

# Estado por nodo
ultima_seq = {}
recibidos = {}
perdidos = {}
duplicados = {}
reinicios = {}


def iniciar_radio():
    spi = machine.SoftSPI(sck=machine.Pin(PIN_SCK), mosi=machine.Pin(PIN_MOSI),
                          miso=machine.Pin(PIN_MISO))
    csn = machine.Pin(PIN_CSN, mode=machine.Pin.OUT, value=1)
    ce = machine.Pin(PIN_CE, mode=machine.Pin.OUT, value=0)
    radio = NRF24L01(spi, csn, ce, channel=CANAL_RF, payload_size=ft.TAMANO)
    radio.open_rx_pipe(1, DIRECCION)
    radio.start_listening()
    return radio


def contabilizar(mensaje):
    """Clasifica la trama por su secuencia. Devuelve el mensaje o None.

    None significa "duplicado": no se publica. La secuencia es de 16 bits;
    el salto se calcula modulo 2^16. Un salto hacia atras (mayor que la mitad
    del espacio) solo puede venir de un reinicio del nodo, porque el nodo no
    emite una trama nueva hasta terminar con la anterior.
    """
    nodo = mensaje["nodo"]
    seq = mensaje["secuencia"]
    anterior = ultima_seq.get(nodo)

    if anterior is not None:
        salto = (seq - anterior) & 0xFFFF
        if salto == 0:
            duplicados[nodo] = duplicados.get(nodo, 0) + 1
            return None
        if salto >= 0x8000:
            reinicios[nodo] = reinicios.get(nodo, 0) + 1
            print(ujson.dumps({"evento": "reinicio_nodo", "nodo": nodo,
                               "secuencia_previa": anterior,
                               "secuencia": seq}))
        elif salto > 1:
            perdidos[nodo] = perdidos.get(nodo, 0) + (salto - 1)

    ultima_seq[nodo] = seq
    recibidos[nodo] = recibidos.get(nodo, 0) + 1
    total = recibidos[nodo] + perdidos.get(nodo, 0)
    d = mensaje["diag"]
    d["secuencia"] = seq
    d["recibidos"] = recibidos[nodo]
    d["perdidos"] = perdidos.get(nodo, 0)
    d["duplicados"] = duplicados.get(nodo, 0)
    d["tasa_entrega"] = round(recibidos[nodo] / total, 4)
    return mensaje


def main():
    radio = iniciar_radio()
    print(ujson.dumps({"evento": "concentrador_listo", "version": 3,
                       "canal": CANAL_RF, "tamano_trama": ft.TAMANO}))
    ultimo_latido = utime.ticks_ms()

    while True:
        while radio.any():
            trama = radio.recv()
            try:
                mensaje = ft.desempaquetar(trama)
            except Exception as e:
                print(ujson.dumps({"evento": "trama_invalida",
                                   "detalle": str(e)}))
                continue
            mensaje["ts_rx_ms"] = utime.ticks_ms()
            mensaje = contabilizar(mensaje)
            if mensaje is None:
                continue
            if mensaje["estado_num"] >= 2:
                for _ in range(3):
                    led.value(1)
                    utime.sleep_ms(30)
                    led.value(0)
                    utime.sleep_ms(30)
            else:
                led.value(1)
                utime.sleep_ms(15)
                led.value(0)
            print(ujson.dumps(mensaje))

        if utime.ticks_diff(utime.ticks_ms(), ultimo_latido) > LATIDO_S * 1000:
            print(ujson.dumps({
                "evento": "latido",
                "nodos": len(recibidos),
                "recibidos": sum(recibidos.values()),
                "perdidos": sum(perdidos.values()),
                "duplicados": sum(duplicados.values()),
                "reinicios": sum(reinicios.values()),
            }))
            ultimo_latido = utime.ticks_ms()

        utime.sleep_ms(20)


main()
