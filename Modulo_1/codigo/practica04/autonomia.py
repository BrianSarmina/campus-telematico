"""Presupuesto de energia del nodo - Practica 4 (se ejecuta en la PC).

Calcula la autonomia del nodo en funcion del periodo de muestreo y contrasta
esa decision con la resolucion temporal del fenomeno medido.

IMPORTANTE: los valores de corriente DEBEN medirse con el multimetro en el
nodo real. Los que vienen por omision son de la hoja de datos del ESP32 y
sirven solo como punto de partida; el consumo real depende de la tarjeta
(los reguladores y los LED de las DevKit consumen mucho mas de lo esperado).

Uso:
    python autonomia.py
    python autonomia.py --activo 145 --dormido 22 --capacidad 2500
"""
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Constantes de tiempo tipicas del fenomeno medido, en segundos.
# Muestrear mucho mas rapido que esto es desperdiciar energia; muestrear
# mucho mas lento es perder el fenomeno.
FENOMENOS = {
    "Temperatura de un aula": 600,
    "Humedad relativa": 600,
    "CO2 con ocupacion variable": 120,
    "Ruido ambiental": 1,
}


def calcular(periodo_s, i_activo_ma, i_dormido_ua, t_activo_s,
             capacidad_mah, eficiencia):
    if periodo_s <= t_activo_s:
        return None, None      # no alcanza a dormir
    ciclo = t_activo_s / periodo_s
    i_media_ma = i_activo_ma * ciclo + (i_dormido_ua / 1000.0) * (1 - ciclo)
    horas = (capacidad_mah * eficiencia) / i_media_ma
    return i_media_ma, horas / 24.0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--capacidad", type=float, default=2000.0, help="mAh")
    ap.add_argument("--activo", type=float, default=120.0,
                    help="Corriente en operacion, mA (MEDIR)")
    ap.add_argument("--dormido", type=float, default=10.0,
                    help="Corriente en sueno profundo, uA (MEDIR)")
    ap.add_argument("--tactivo", type=float, default=4.0,
                    help="Segundos despierto por ciclo (MEDIR)")
    ap.add_argument("--eficiencia", type=float, default=0.75)
    a = ap.parse_args()

    print("\n" + "=" * 72)
    print("  PRESUPUESTO DE ENERGIA DEL NODO")
    print("=" * 72)
    print(f"  Bateria             : {a.capacidad:.0f} mAh")
    print(f"  Corriente activa    : {a.activo:.1f} mA")
    print(f"  Corriente dormido   : {a.dormido:.1f} uA")
    print(f"  Tiempo despierto    : {a.tactivo:.1f} s por ciclo")
    print(f"  Eficiencia asumida  : {a.eficiencia:.0%}")
    print("-" * 72)
    print(f"{'Periodo':>12}{'Ciclo trabajo':>16}{'I media':>12}"
          f"{'Autonomia':>14}{'Muestras/dia':>14}")
    print("-" * 72)

    periodos = [10, 30, 60, 120, 300, 900, 1800, 3600]
    autonomias = []
    for p in periodos:
        i, dias = calcular(p, a.activo, a.dormido, a.tactivo,
                           a.capacidad, a.eficiencia)
        if i is None:
            print(f"{p:>10} s  {'periodo menor al tiempo despierto':>50}")
            autonomias.append(0)
            continue
        autonomias.append(dias)
        print(f"{p:>10} s {a.tactivo / p:>15.1%}{i:>10.3f} mA"
              f"{dias:>11.1f} d{86400 / p:>14.0f}")

    print("-" * 72)

    # ---------------- Sin sueno profundo (siempre encendido) ----------------
    horas_siempre = (a.capacidad * a.eficiencia) / a.activo
    print(f"\n  Sin sueno profundo (DORMIR=False): {horas_siempre:.1f} horas "
          f"({horas_siempre / 24:.2f} dias)")
    print("  Este es el modo de desarrollo. La diferencia con el modo dormido")
    print("  es de dos a tres ordenes de magnitud.")

    # ---------------- Contraste con el fenomeno ----------------
    print("\n" + "=" * 72)
    print("  ELECCION DEL PERIODO SEGUN EL FENOMENO, NO SEGUN LA BATERIA")
    print("=" * 72)
    print("  Criterio: muestrear al menos 5 veces por constante de tiempo.")
    print(f"\n{'Fenomeno':<32}{'Const. tiempo':>16}{'Periodo max.':>16}")
    print("-" * 72)
    for nombre, tau in FENOMENOS.items():
        print(f"{nombre:<32}{tau:>13} s{tau / 5:>13.0f} s")

    print("\n  Para temperatura y humedad ambientales, un periodo de 60-120 s")
    print("  es suficiente. Muestrear cada 10 s no aporta informacion nueva")
    print("  y reduce la autonomia en un orden de magnitud.")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(periodos, autonomias, "o-", color="#002D72", lw=2)
    ax.axvspan(60, 120, alpha=0.15, color="green",
               label="Rango recomendado (60-120 s)")
    ax.set_xscale("log")
    ax.set_xlabel("Periodo de muestreo (s)")
    ax.set_ylabel("Autonomia (dias)")
    ax.set_title(f"Autonomia con bateria de {a.capacidad:.0f} mAh")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    fig.savefig("autonomia.png", dpi=140)
    print("\n  Grafica guardada: autonomia.png")
