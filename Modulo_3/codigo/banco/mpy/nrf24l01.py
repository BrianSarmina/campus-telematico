"""Sustituto del controlador nRF24L01 para el banco de pruebas.

Misma interfaz que el controlador oficial de micropython-lib que usa el
firmware real (NRF24L01(spi, cs, ce, channel, payload_size), send, recv,
any, open_tx_pipe, open_rx_pipe, start_listening, stop_listening,
reg_read, reg_write). En lugar de hablar con un radio por SPI, cada intento
de transmision se envia por UDP al proceso aire.py, que decide si choca, si
la interferencia lo destruye y a quien se entrega.

Lo que reproduce:
  - el reintento automatico con SETUP_RETR (ARC y ARD) y el contador
    ARC_CNT de OBSERVE_TX, que el firmware v3 lee;
  - OSError("send failed") al agotar los reintentos, como el controlador;
  - el filtro de duplicados por hardware (PID): los reintentos de una misma
    llamada a send() se entregan una sola vez;
  - el registro RPD (0x09), con un modelo ilustrativo de Wi-Fi para el
    escaner: BANCO_WIFI="1" o "1,11", BANCO_WIFI_OCUPACION=0.4.

Lo que NO reproduce: la temporizacion fina. Cada intento espera la decision
del aire (unos milisegundos), mas lento que el radio real.
"""
import json
import os
import random
import socket
import time

CONFIG = 0x00
SETUP_RETR = 0x04
RF_CH = 0x05
OBSERVE_TX = 0x08
RPD = 0x09

_h, _p = os.environ.get("BANCO_AIRE", "127.0.0.1:47000").split(":")
_AIRE = (_h, int(_p))


def _p_wifi(canal):
    """Probabilidad de leer RPD = 1 en un canal (modelo ilustrativo)."""
    cadena = os.environ.get("BANCO_WIFI", "").strip()
    if not cadena:
        return 0.002
    ocup = float(os.environ.get("BANCO_WIFI_OCUPACION", "0.4"))
    f = 2400 + canal
    p = 0.002
    for w in cadena.split(","):
        centro = 2407 + 5 * int(w)
        d = abs(f - centro)
        if d <= 9:
            p = max(p, ocup)
        elif d <= 11:
            p = max(p, ocup * 0.5)
        elif d <= 20:
            p = max(p, ocup * 0.05)
    return p


class NRF24L01:
    def __init__(self, spi, cs, ce, channel=46, payload_size=16):
        assert payload_size <= 32
        self.spi, self.cs, self.ce = spi, cs, ce
        self.payload_size = payload_size
        self.regs = {CONFIG: 0x0C, SETUP_RETR: (6 << 4) | 8,
                     RF_CH: min(channel, 125), OBSERVE_TX: 0}
        self.dir_tx = None
        self.dir_rx = None
        self.escuchando = False
        self.envio = 0
        self.cola = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.puerto = self.sock.getsockname()[1]

    # ------------------------------------------------------------ registros
    def reg_read(self, reg):
        if reg == RPD:
            return 1 if random.random() < _p_wifi(self.regs[RF_CH]) else 0
        return self.regs.get(reg, 0)

    def reg_write(self, reg, value):
        self.regs[reg] = value & 0xFF
        if reg == RF_CH:
            self.regs[OBSERVE_TX] &= 0x0F      # escribir RF_CH borra PLOS_CNT
            if self.escuchando:
                self._registrar()
        return 0x0E

    def set_channel(self, channel):
        self.reg_write(RF_CH, min(channel, 125))

    def set_power_speed(self, power, speed):
        pass

    def set_crc(self, length):
        pass

    def flush_rx(self):
        self.cola = []

    def flush_tx(self):
        pass

    # ------------------------------------------------------------ tuberias
    def open_tx_pipe(self, address):
        assert len(address) == 5
        self.dir_tx = bytes(address)

    def open_rx_pipe(self, pipe_id, address):
        assert len(address) == 5
        self.dir_rx = bytes(address)

    def _enviar_aire(self, msg):
        msg["puerto"] = self.puerto
        self.sock.sendto(json.dumps(msg).encode(), _AIRE)

    def _registrar(self):
        if self.dir_rx is not None:
            self._enviar_aire({"tipo": "rx", "canal": self.regs[RF_CH],
                               "dir": self.dir_rx.hex()})

    def start_listening(self):
        self.escuchando = True
        self._registrar()

    def stop_listening(self):
        if self.escuchando:
            self._enviar_aire({"tipo": "rx_fin"})
        self.escuchando = False

    # ------------------------------------------------------------ recepcion
    def _drenar(self):
        self.sock.setblocking(False)
        try:
            while True:
                datos, _ = self.sock.recvfrom(4096)
                m = json.loads(datos.decode())
                if m.get("tipo") == "trama":
                    self.cola.append(bytes.fromhex(m["carga"]))
        except (BlockingIOError, OSError):
            pass
        finally:
            self.sock.setblocking(True)

    def any(self):
        self._drenar()
        return bool(self.cola)

    def recv(self):
        self._drenar()
        return self.cola.pop(0) if self.cola else bytes(self.payload_size)

    # ------------------------------------------------------------ transmision
    def _intento(self, carga, k):
        self._enviar_aire({"tipo": "tx", "canal": self.regs[RF_CH],
                           "dir": self.dir_tx.hex(), "carga": carga.hex(),
                           "envio": self.envio, "intento": k,
                           "t": time.perf_counter()})
        limite = time.perf_counter() + 0.2
        self.sock.settimeout(0.2)
        try:
            while time.perf_counter() < limite:
                datos, _ = self.sock.recvfrom(4096)
                m = json.loads(datos.decode())
                if (m.get("tipo") == "res" and m.get("envio") == self.envio
                        and m.get("intento") == k):
                    return m["ok"]
        except (socket.timeout, OSError):
            pass
        finally:
            self.sock.settimeout(None)
        return False

    def send(self, buf, timeout=500):
        carga = bytes(buf) + bytes(max(0, self.payload_size - len(buf)))
        retr = self.regs[SETUP_RETR]
        arc, ard_us = retr & 0x0F, ((retr >> 4) + 1) * 250
        time.sleep(0.0015)                     # encendido, como send_start()
        self.envio += 1
        for k in range(arc + 1):
            if self._intento(carga, k):
                self.regs[OBSERVE_TX] = (self.regs[OBSERVE_TX] & 0xF0) | k
                return
            if k < arc:
                time.sleep(ard_us / 1e6)
        plos = min(15, (self.regs[OBSERVE_TX] >> 4) + 1)
        self.regs[OBSERVE_TX] = (plos << 4) | arc
        raise OSError("send failed")
