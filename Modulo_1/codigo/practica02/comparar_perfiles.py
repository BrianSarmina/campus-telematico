"""Tabla comparativa de perfiles de trafico - Practica 2.

Lee el CSV acumulado por analiza_captura.py y produce la tabla comparativa
que se entrega en el informe, mas una grafica de barras.

Uso:
    python comparar_perfiles.py
    python comparar_perfiles.py --csv perfiles.csv
"""
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

COLUMNAS = {
    "etiqueta": "Flujo",
    "tasa_pps": "Paq/s",
    "tam_medio_B": "Tam. medio (B)",
    "bw_medio_kbps": "BW medio (kbit/s)",
    "bw_pico_kbps": "BW pico (kbit/s)",
    "factor_rafaga": "F. rafaga",
    "cv": "CV",
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="perfiles.csv")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    tabla = df[list(COLUMNAS)].rename(columns=COLUMNAS)

    print("\n" + "=" * 78)
    print("  COMPARATIVA DE PERFILES DE TRAFICO")
    print("=" * 78)
    print(tabla.to_string(index=False))
    print("=" * 78)

    # Version LaTeX lista para pegar en el informe
    print("\nTabla en formato LaTeX (pegar en el informe):\n")
    print(tabla.to_latex(index=False, float_format="%.2f"))

    # Comparacion visual: la escala logaritmica es indispensable porque
    # el video suele estar tres ordenes de magnitud por encima.
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    x = np.arange(len(df))
    ancho = 0.35

    ax[0].bar(x - ancho / 2, df["bw_medio_kbps"], ancho, label="Medio",
              color="#002D72")
    ax[0].bar(x + ancho / 2, df["bw_pico_kbps"], ancho, label="Pico",
              color="#B08D57")
    ax[0].set_xticks(x)
    ax[0].set_xticklabels(df["etiqueta"], rotation=15, ha="right")
    ax[0].set_ylabel("kbit/s")
    ax[0].set_yscale("log")
    ax[0].set_title("Ancho de banda (escala logaritmica)")
    ax[0].legend()

    ax[1].bar(x, df["factor_rafaga"], color="#006E3C")
    ax[1].axhline(1.0, ls="--", color="grey", label="Flujo constante")
    ax[1].set_xticks(x)
    ax[1].set_xticklabels(df["etiqueta"], rotation=15, ha="right")
    ax[1].set_ylabel("Pico / media")
    ax[1].set_title("Factor de rafaga")
    ax[1].legend()

    fig.tight_layout()
    fig.savefig("comparativa_perfiles.png", dpi=140)
    print("\nGrafica guardada: comparativa_perfiles.png")

    print("\nPREGUNTA PARA EL INFORME: si ambos flujos comparten un enlace,")
    print("cual dimensiona la capacidad, el ancho de banda medio o el pico?")
