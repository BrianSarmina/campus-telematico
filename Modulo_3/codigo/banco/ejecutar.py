"""Ejecuta un firmware MicroPython REAL en la PC, sobre los sustitutos de mpy/.

El codigo que corre es el mismo archivo main.py que se copia al ESP32; solo
cambian los modulos de hardware (machine, utime, nrf24l01, bme280), que aqui
son simulados. Asi se verifica la logica del firmware sin placa.

Uso:
    python ejecutar.py --firmware ../firmware/nodo_detector \\
        --extra ../../../Modulo_1/codigo/practica04/nodo_detector \\
        --config '{"ID_NODO": 2, "PRECALENTADO_S": 5}'

--extra agrega directorios donde buscar modulos que el firmware importa y
no estan en --firmware (deteccion.py y formato_trama.py del Modulo 1).
--config sobreescribe variables de config.py sin tocar el archivo.
"""
import argparse
import json
import os
import runpy
import signal
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware", required=True)
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--config", default="{}")
    a = ap.parse_args()

    fw = os.path.abspath(a.firmware)
    extras = [os.path.abspath(e) for e in a.extra]
    cambios = json.loads(a.config)

    # config.py del firmware + cambios, en un directorio temporal propio
    tmp = tempfile.mkdtemp(prefix="banco_")
    origen = os.path.join(fw, "config.py")
    texto = open(origen).read() if os.path.exists(origen) else ""
    for k, v in cambios.items():
        if isinstance(v, str) and k == "DIRECCION":
            texto += "\n{} = {!r}\n".format(k, v.encode())
        else:
            texto += "\n{} = {!r}\n".format(k, v)
    with open(os.path.join(tmp, "config.py"), "w") as f:
        f.write(texto)

    # Orden: sustitutos de hardware, config, firmware, extras
    sys.path[:0] = [os.path.join(AQUI, "mpy"), tmp, fw] + extras
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        runpy.run_path(os.path.join(fw, "main.py"), run_name="__main__")
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
