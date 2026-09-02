"""Caracterizacion de trafico a partir de una captura - Practica 2.

Calcula las metricas que describen el perfil de un flujo: tasa de paquetes,
distribucion de tamanos, ancho de banda medio y pico, factor de rafaga y
estadistica del tiempo entre llegadas. Genera dos histogramas.

Uso:
    python analiza_captura.py telemetria.pcap --etiqueta "MQTT telemetria"
    python analiza_captura.py video.pcap --etiqueta "Video" --filtro "udp"

Si pyshark falla (requiere tshark instalado), usar --modo tshark para
procesar con una llamada directa a tshark, que es mas rapida.
"""
import argparse
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")            # backend sin ventana: necesario por SSH
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def cargar_con_tshark(ruta, filtro=None):
    """Extrae tiempo y longitud con tshark. Mas rapido que pyshark."""
    cmd = ["tshark", "-r", ruta, "-T", "fields",
           "-e", "frame.time_epoch", "-e", "frame.len"]
    if filtro:
        cmd += ["-Y", filtro]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"tshark fallo:\n{r.stderr}")
    filas = []
    for linea in r.stdout.splitlines():
        partes = linea.split("\t")
        if len(partes) == 2 and partes[0] and partes[1]:
            filas.append({"t": float(partes[0]), "bytes": int(partes[1])})
    return pd.DataFrame(filas)


def cargar_con_pyshark(ruta, filtro=None):
    import pyshark
    cap = pyshark.FileCapture(ruta, display_filter=filtro,
                              keep_packets=False, only_summaries=True)
    filas = [{"t": float(p.time), "bytes": int(p.length)} for p in cap]
    cap.close()
    return pd.DataFrame(filas)


def caracterizar(df, etiqueta):
    df = df.sort_values("t").reset_index(drop=True)
    df["dt"] = df["t"].diff()

    duracion = df["t"].iloc[-1] - df["t"].iloc[0]
    if duracion <= 0:
        sys.exit("La captura no tiene duracion util.")

    total_bytes = df["bytes"].sum()
    tasa_pps = len(df) / duracion
    ancho_bps = total_bytes * 8 / duracion

    # Tasa por ventanas de 1 s: revela las rafagas que la media esconde
    ventanas = df.groupby(df["t"].astype(int))["bytes"].sum() * 8
    pico_bps = ventanas.max()
    factor_rafaga = pico_bps / ventanas.mean() if ventanas.mean() else 0

    print(f"\n{'=' * 58}")
    print(f"  PERFIL DE TRAFICO: {etiqueta}")
    print(f"{'=' * 58}")
    print(f"  Duracion de la captura   : {duracion:10.2f} s")
    print(f"  Paquetes                 : {len(df):10d}")
    print(f"  Bytes totales            : {total_bytes:10d}")
    print(f"  Tasa media de paquetes   : {tasa_pps:10.2f} paq/s")
    print(f"  Tamano medio de paquete  : {df['bytes'].mean():10.1f} B")
    print(f"  Tamano minimo / maximo   : {df['bytes'].min():5d} / "
          f"{df['bytes'].max():d} B")
    print(f"  Ancho de banda medio     : {ancho_bps / 1000:10.2f} kbit/s")
    print(f"  Ancho de banda pico (1 s): {pico_bps / 1000:10.2f} kbit/s")
    print(f"  Factor de rafaga         : {factor_rafaga:10.2f}")
    print(f"  Tiempo entre llegadas    : media {df['dt'].mean() * 1000:.2f} ms, "
          f"desv {df['dt'].std() * 1000:.2f} ms")

    cv = df["dt"].std() / df["dt"].mean() if df["dt"].mean() else 0
    print(f"  Coef. de variacion (CV)  : {cv:10.2f}")
    if cv < 0.3:
        print("     -> Llegadas casi DETERMINISTAS (periodicas).")
        print("        El modelo de Poisson NO aplica bien aqui.")
    elif 0.7 < cv < 1.3:
        print("     -> Llegadas compatibles con un proceso de POISSON (CV ~ 1).")
    else:
        print("     -> Llegadas con RAFAGAS marcadas (CV > 1).")

    return {
        "etiqueta": etiqueta, "paquetes": len(df), "duracion_s": round(duracion, 2),
        "tasa_pps": round(tasa_pps, 2), "tam_medio_B": round(df["bytes"].mean(), 1),
        "bw_medio_kbps": round(ancho_bps / 1000, 2),
        "bw_pico_kbps": round(pico_bps / 1000, 2),
        "factor_rafaga": round(factor_rafaga, 2), "cv": round(cv, 2),
    }


def graficar(df, etiqueta):
    nombre = etiqueta.replace(" ", "_").replace("/", "-")
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))

    ax[0].hist(df["bytes"], bins=40, color="#002D72", edgecolor="white")
    ax[0].set_xlabel("Tamano de paquete (B)")
    ax[0].set_ylabel("Frecuencia")
    ax[0].set_title("Distribucion de tamanos")

    dt_ms = df["dt"].dropna() * 1000
    ax[1].hist(dt_ms[dt_ms < dt_ms.quantile(0.99)], bins=40,
               color="#B08D57", edgecolor="white")
    ax[1].set_xlabel("Tiempo entre llegadas (ms)")
    ax[1].set_title("Distribucion de llegadas")

    ventanas = df.groupby(df["t"].astype(int))["bytes"].sum() * 8 / 1000
    ax[2].plot(range(len(ventanas)), ventanas.values, color="#006E3C")
    ax[2].axhline(ventanas.mean(), ls="--", color="red", label="Media")
    ax[2].set_xlabel("Tiempo (s)")
    ax[2].set_ylabel("kbit/s")
    ax[2].set_title("Tasa por segundo")
    ax[2].legend()

    fig.suptitle(f"Perfil de trafico: {etiqueta}", fontsize=13)
    fig.tight_layout()
    salida = f"perfil_{nombre}.png"
    fig.savefig(salida, dpi=140)
    print(f"\n  Grafica guardada: {salida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("captura", help="Archivo .pcap o .pcapng")
    ap.add_argument("--etiqueta", default="flujo")
    ap.add_argument("--filtro", default=None, help="Filtro de visualizacion de Wireshark")
    ap.add_argument("--modo", choices=["tshark", "pyshark"], default="tshark")
    ap.add_argument("--csv", default="perfiles.csv")
    a = ap.parse_args()

    df = (cargar_con_tshark if a.modo == "tshark" else cargar_con_pyshark)(
        a.captura, a.filtro)

    if df.empty:
        sys.exit("La captura no contiene paquetes que cumplan el filtro.")

    fila = caracterizar(df, a.etiqueta)
    graficar(df, a.etiqueta)

    # Acumula los perfiles en un CSV para la tabla comparativa del informe
    try:
        previo = pd.read_csv(a.csv)
        salida = pd.concat([previo[previo["etiqueta"] != a.etiqueta],
                            pd.DataFrame([fila])], ignore_index=True)
    except FileNotFoundError:
        salida = pd.DataFrame([fila])
    salida.to_csv(a.csv, index=False)
    print(f"  Perfil acumulado en: {a.csv}")
