"""Generador de carga Wi-Fi - Modulo 3, Practicas 9 y 10.

Ocupa el canal del punto de acceso del robot con trafico UDP a una tasa
fija, para estudiar la coexistencia con el enlace nRF24L01. Es Python puro:
corre igual en Windows, Linux y la Raspberry Pi, sin instalar iperf3.

Dos papeles:
  --servidor        en la Raspberry Pi: recibe y mide lo que llega
  --cliente HOST    en la computadora: envia a la Pi a --mbps durante
                    --segundos

Lo que importa para el experimento es el tiempo de aire que ocupa la carga,
no que llegue todo: si el servidor recibe menos de lo enviado, el canal ya
esta saturado. Anote la tasa que reporta el SERVIDOR, que es la medida.

Uso:
    python3 carga_wifi.py --servidor                    # en la Pi
    python carga_wifi.py --cliente 10.42.0.1 --mbps 15 --segundos 600
"""
import argparse
import signal
import socket
import time

PUERTO = 5202


def servidor(puerto):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", puerto))
    s.settimeout(1.0)
    print("Servidor de carga en UDP {} (Ctrl-C para terminar)".format(puerto))
    total_b, total_p = 0, 0
    ventana_b, t_vent = 0, time.time()
    t0 = None
    try:
        while True:
            try:
                datos, _ = s.recvfrom(65535)
            except socket.timeout:
                datos = None
            ahora = time.time()
            if datos:
                if t0 is None:
                    t0 = ahora
                total_b += len(datos)
                total_p += 1
                ventana_b += len(datos)
            if ahora - t_vent >= 2.0:
                if ventana_b:
                    print("  recibido {:6.2f} Mbit/s".format(
                        ventana_b * 8 / (ahora - t_vent) / 1e6), flush=True)
                ventana_b, t_vent = 0, ahora
    except KeyboardInterrupt:
        pass
    if t0:
        dur = time.time() - t0
        print("\nRecibidos {} paquetes, {:.1f} MB, media {:.2f} Mbit/s".format(
            total_p, total_b / 1e6, total_b * 8 / dur / 1e6))


def cliente(destino, puerto, mbps, segundos, tam):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    carga = bytes(tam)
    intervalo = tam * 8 / (mbps * 1e6)       # segundos entre paquetes
    print("Enviando a {}:{} a {} Mbit/s durante {} s ({} B por paquete)".format(
        destino, puerto, mbps, segundos, tam))
    t0 = time.perf_counter()
    siguiente = t0
    enviados = 0
    t_vent, env_vent = t0, 0
    try:
        while True:
            ahora = time.perf_counter()
            if ahora - t0 >= segundos:
                break
            if ahora < siguiente:
                if siguiente - ahora > 0.002:
                    time.sleep(siguiente - ahora - 0.001)
                continue
            try:
                s.sendto(carga, (destino, puerto))
                enviados += 1
                env_vent += 1
            except OSError:
                time.sleep(0.001)           # buffer lleno: el canal no da mas
            siguiente += intervalo
            if siguiente < ahora - 0.05:     # no acumular deuda
                siguiente = ahora
            if ahora - t_vent >= 2.0:
                print("  enviado {:6.2f} Mbit/s".format(
                    env_vent * tam * 8 / (ahora - t_vent) / 1e6), flush=True)
                t_vent, env_vent = ahora, 0
    except KeyboardInterrupt:
        pass
    dur = time.perf_counter() - t0
    print("\nEnviados {} paquetes en {:.0f} s: {:.2f} Mbit/s".format(
        enviados, dur, enviados * tam * 8 / dur / 1e6))


def _interrumpir(*_):
    raise KeyboardInterrupt


def main():
    # SIGTERM (kill) termina igual que Ctrl-C: con el resumen
    signal.signal(signal.SIGTERM, _interrumpir)
    ap = argparse.ArgumentParser(description="Generador de carga Wi-Fi")
    ap.add_argument("--servidor", action="store_true")
    ap.add_argument("--cliente", metavar="HOST")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--mbps", type=float, default=15.0)
    ap.add_argument("--segundos", type=float, default=600.0)
    ap.add_argument("--tam", type=int, default=1400)
    a = ap.parse_args()
    if a.servidor:
        servidor(a.puerto)
    elif a.cliente:
        cliente(a.cliente, a.puerto, a.mbps, a.segundos, a.tam)
    else:
        ap.error("indique --servidor o --cliente HOST")


if __name__ == "__main__":
    main()
