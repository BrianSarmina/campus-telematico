"""Visor del escaner de espectro - Modulo 3, Practica 9. Se ejecuta en la PC.

Lee los barridos que imprime escaner/main.py (cargado en el concentrador),
acumula la fraccion de lecturas con RPD = 1 por canal y la muestra contra
el mapa de canales Wi-Fi.

MAPA DE FRECUENCIAS
  nRF24L01, canal k : 2400 + k MHz, ancho util de 1 MHz a 250 kbps
  Wi-Fi,    canal n : centro en 2407 + 5n MHz, ocupa unos 22 MHz
     canal 1  -> 2401-2423 MHz      canal 6 -> 2426-2448 MHz
     canal 11 -> 2451-2473 MHz
  El enlace del proyecto usa el canal 76 (2476 MHz); la P9 prueba tambien
  el 70 (2470 MHz), que cae DENTRO del Wi-Fi del canal 11.

La fraccion medida se usa como 'ocupacion' en modelo_colisiones.py y en
simular_prioridad.py: es el puente entre la medicion y el modelo.

Uso:
    python ver_espectro.py --puerto COM4 --barridos 5 --etiqueta AP-canal-1
    python ver_espectro.py --archivo barridos.txt
    python ver_espectro.py --simular --canal-wifi 11      # sin hardware
"""
import argparse
import csv
import json
import os
import random
import sys
import time

CANALES = 126
WIFI = {1: 2412, 6: 2437, 11: 2462}
NRF = {70: "P9", 76: "proyecto"}
NIVELES = [(0.50, "@"), (0.30, "#"), (0.15, "="), (0.05, ":"), (0.01, ".")]


def barridos_serial(puerto, n):
    import serial
    with serial.Serial(puerto, 115200, timeout=30) as s:
        time.sleep(2)
        hechos = 0
        while hechos < n:
            linea = s.readline().decode("utf-8", "ignore").strip()
            if not linea:
                print("  (esperando barridos; el primero tarda unos segundos)")
                continue
            try:
                m = json.loads(linea)
            except ValueError:
                continue
            if m.get("evento") == "espectro":
                hechos += 1
                print("  barrido {} de {} ({} ms)".format(
                    hechos, n, m.get("duracion_ms", "?")))
                yield m


def barridos_archivo(ruta, n):
    hechos = 0
    for linea in open(ruta, encoding="utf-8", errors="ignore"):
        try:
            m = json.loads(linea.strip())
        except ValueError:
            continue
        if m.get("evento") == "espectro":
            hechos += 1
            yield m
            if hechos >= n:
                return


def barridos_simulados(canal_wifi, ocupacion, n, muestras=60, semilla=1):
    """Mismo modelo ilustrativo que el banco (banco/mpy/nrf24l01.py)."""
    rng = random.Random(semilla)
    centro = 2407 + 5 * canal_wifi
    for b in range(n):
        cuentas = []
        for k in range(CANALES):
            d = abs(2400 + k - centro)
            p = (ocupacion if d <= 9 else ocupacion * 0.5 if d <= 11
                 else ocupacion * 0.05 if d <= 20 else 0.0) + 0.002
            cuentas.append(sum(1 for _ in range(muestras) if rng.random() < p))
        yield {"evento": "espectro", "barrido": b, "muestras": muestras,
               "cuentas": cuentas}


def acumular(fuente):
    total = [0] * CANALES
    muestras = 0
    n = 0
    for m in fuente:
        for k, c in enumerate(m["cuentas"][:CANALES]):
            total[k] += c
        muestras += m["muestras"]
        n += 1
    if n == 0:
        return None, 0
    return [t / muestras for t in total], n


def promedio(fr, a, b):
    sel = fr[max(0, a):min(CANALES, b + 1)]
    return sum(sel) / len(sel) if sel else 0.0


def dibujar_texto(fr):
    fila = ""
    for f in fr:
        c = " "
        for umbral, simbolo in NIVELES:
            if f >= umbral:
                c = simbolo
                break
        fila += c
    eje = "".join("|" if k % 10 == 0 else "-" for k in range(CANALES))
    marcas = [" "] * CANALES
    for k in NRF:
        marcas[k] = "^"
    print("  " + fila)
    print("  " + eje)
    print("  " + "".join(marcas))
    print("  canal 0 = 2400 MHz; una marca | cada 10 MHz; ^ = nRF 70 y 76")
    print("  escala: ' ' <1 %  '.' 1-5 %  ':' 5-15 %  '=' 15-30 %  "
          "'#' 30-50 %  '@' >50 %")


def grafica(fr, archivo, titulo):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (sin matplotlib: se omite la grafica)")
        return
    fig, ax = plt.subplots(figsize=(8, 3.6))
    frecs = [2400 + k for k in range(CANALES)]
    ax.bar(frecs, [100 * f for f in fr], width=1.0, color="#002D72")
    for n, c in WIFI.items():
        ax.axvspan(c - 11, c + 11, color="#B08D57", alpha=0.18)
        ax.text(c, 101, "Wi-Fi {}".format(n), ha="center", va="bottom",
                fontsize=8, color="#7a5c2e")
    for k, nombre in NRF.items():
        ax.axvline(2400 + k, color="#B00020", lw=1, ls="--")
        ax.text(2400 + k + 0.6, 60 if k == 70 else 80, "nRF {}\n({})".format(
            k, nombre), fontsize=7, color="#B00020")
    ax.set_xlim(2398, 2527)
    ax.set_ylim(0, 112)
    ax.set_xlabel("Frecuencia (MHz)")
    ax.set_ylabel("Lecturas con RPD = 1 (%)")
    ax.set_title(titulo, fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(archivo, dpi=150)
    print("  Grafica: {}".format(archivo))


def main():
    ap = argparse.ArgumentParser(description="Visor del escaner de espectro")
    ap.add_argument("--puerto", help="puerto USB del concentrador con el escaner")
    ap.add_argument("--archivo", help="archivo con las lineas JSON del escaner")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--canal-wifi", type=int, default=1)
    ap.add_argument("--ocupacion", type=float, default=0.4,
                    help="solo con --simular")
    ap.add_argument("--barridos", type=int, default=5)
    ap.add_argument("--etiqueta", default="")
    ap.add_argument("--png", default="espectro.png", help="'no' para omitir")
    ap.add_argument("--csv", default="espectro.csv", help="'no' para omitir")
    a = ap.parse_args()

    if a.puerto:
        fuente = barridos_serial(a.puerto, a.barridos)
        origen = "medido en {}".format(a.puerto)
    elif a.archivo:
        fuente = barridos_archivo(a.archivo, a.barridos)
        origen = "archivo {}".format(os.path.basename(a.archivo))
    elif a.simular:
        fuente = barridos_simulados(a.canal_wifi, a.ocupacion, a.barridos)
        origen = "SIMULADO, Wi-Fi canal {}, ocupacion {:.0%}".format(
            a.canal_wifi, a.ocupacion)
    else:
        sys.exit("Indique --puerto, --archivo o --simular")

    fr, n = acumular(fuente)
    if fr is None:
        sys.exit("No se recibio ningun barrido.")

    print()
    print("=" * 70)
    print("  ESPECTRO 2.4 GHz  {}  [{}]".format(a.etiqueta, origen))
    print("  {} barridos acumulados".format(n))
    print("=" * 70)
    dibujar_texto(fr)
    print()
    print("  {:<28} {:>14}".format("Zona", "Ocupacion RPD"))
    print("  " + "-" * 44)
    for c, centro in WIFI.items():
        print("  {:<28} {:>13.1%}".format(
            "Wi-Fi canal {} ({}-{} MHz)".format(c, centro - 11, centro + 11),
            promedio(fr, centro - 11 - 2400, centro + 11 - 2400)))
    for k in NRF:
        print("  {:<28} {:>13.1%}".format(
            "nRF canal {} (+-1 canal)".format(k), promedio(fr, k - 1, k + 1)))
    print("  {:<28} {:>13.1%}".format("Fuera de Wi-Fi (85-125)",
                                       promedio(fr, 85, 125)))
    pico = max(range(CANALES), key=lambda k: fr[k])
    print("\n  Canal mas ocupado: {} ({} MHz), {:.1%}".format(
        pico, 2400 + pico, fr[pico]))
    print("  Use la ocupacion del canal del enlace como --ocupacion en los")
    print("  modelos. Es una estimacion: RPD solo ve senales > -64 dBm.")

    if a.csv and a.csv != "no":
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["canal", "mhz", "fraccion"])
            for k, v in enumerate(fr):
                w.writerow([k, 2400 + k, round(v, 4)])
        print("  Datos: {}".format(a.csv))
    if a.png and a.png != "no":
        grafica(fr, a.png, "Espectro 2.4 GHz {} [{}]".format(a.etiqueta, origen))


if __name__ == "__main__":
    main()
