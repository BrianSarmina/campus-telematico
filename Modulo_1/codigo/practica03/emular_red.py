"""Emulacion de escenarios de red degradada - Practica 3.

Aplica disciplinas netem a una interfaz y mide el efecto sobre el RTT y la
perdida. Sirve para comprobar que el modelo teorico predice lo que ocurre.

REQUIERE LINUX y privilegios de superusuario:
    sudo python emular_red.py
    sudo python emular_red.py --interfaz eth0 --destino 192.168.1.100

En Windows debe ejecutarse dentro de WSL2. En macOS no hay netem; usar
la maquina virtual del laboratorio.

SEGURIDAD: si el programa se interrumpe de forma abrupta, la disciplina
puede quedar aplicada y la red seguira degradada. Para restaurar:
    sudo tc qdisc del dev <interfaz> root
"""
import argparse
import os
import re
import subprocess
import sys
import time

ESCENARIOS = {
    "ideal": None,
    "lan_buena": "delay 5ms 1ms",
    "wifi_cargado": "delay 40ms 15ms distribution normal loss 1%",
    "movil_4g": "delay 80ms 25ms distribution normal loss 2%",
    "movil_3g": "delay 150ms 50ms distribution normal loss 4%",
    "degradado": "delay 250ms 80ms distribution normal loss 8%",
}


def requiere_root():
    if os.geteuid() != 0:
        sys.exit("Se requieren privilegios de superusuario. Use: sudo python "
                 + os.path.basename(__file__))


def limpiar(interfaz):
    subprocess.run(["tc", "qdisc", "del", "dev", interfaz, "root"],
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


def aplicar(interfaz, parametros):
    limpiar(interfaz)
    if parametros:
        r = subprocess.run(["tc", "qdisc", "add", "dev", interfaz, "root",
                            "netem"] + parametros.split(),
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"   ERROR al aplicar netem: {r.stderr.strip()}")
            print("   Verificar que el modulo sch_netem este disponible:")
            print("     sudo modprobe sch_netem")
            return False
    return True


def medir(destino, n=20):
    """Devuelve (rtt_medio_ms, jitter_ms, perdida_pct) usando ping."""
    r = subprocess.run(["ping", "-c", str(n), "-i", "0.2", "-q", destino],
                       capture_output=True, text=True)
    salida = r.stdout

    perdida = re.search(r"([\d.]+)% packet loss", salida)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", salida)

    return (float(rtt.group(2)) if rtt else None,
            float(rtt.group(4)) if rtt else None,
            float(perdida.group(1)) if perdida else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interfaz", default="lo", help="Interfaz de red (lo, eth0, wlan0)")
    ap.add_argument("--destino", default="127.0.0.1")
    ap.add_argument("--paquetes", type=int, default=20)
    a = ap.parse_args()

    requiere_root()

    print(f"\nInterfaz: {a.interfaz}   Destino: {a.destino}")
    print("=" * 72)
    print(f"{'Escenario':<16}{'Configuracion netem':<32}"
          f"{'RTT (ms)':>10}{'Jitter':>8}{'Perdida':>9}")
    print("-" * 72)

    resultados = []
    try:
        for nombre, params in ESCENARIOS.items():
            if not aplicar(a.interfaz, params):
                continue
            time.sleep(1)
            rtt, jitter, perdida = medir(a.destino, a.paquetes)
            desc = params if params else "(sin degradacion)"
            print(f"{nombre:<16}{desc:<32}"
                  f"{rtt if rtt is not None else 0:>10.2f}"
                  f"{jitter if jitter is not None else 0:>8.2f}"
                  f"{perdida if perdida is not None else 0:>8.1f}%")
            resultados.append((nombre, rtt, jitter, perdida))
    finally:
        limpiar(a.interfaz)
        print("-" * 72)
        print("Disciplinas retiradas. La interfaz quedo en su estado original.")

    print("\nOBSERVACION: sobre la interfaz de bucle local (lo) el retardo")
    print("configurado se aplica DOS VECES (ida y vuelta), por lo que el RTT")
    print("medido es aproximadamente el doble del valor de 'delay'.")
