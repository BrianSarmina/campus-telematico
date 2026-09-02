"""Simulacion de colas y validacion analitica - Practica 3.

Modela el gateway como un servidor unico con cola. Compara tres modelos:

  M/M/1  llegadas de Poisson, servicio exponencial  -> W = 1/(mu - lambda)
  M/D/1  llegadas de Poisson, servicio DETERMINISTA -> Wq = rho/(2 mu (1-rho))
  D/D/1  todo determinista                          -> sin espera si rho < 1

El caso M/D/1 es el mas parecido al gateway real: procesar un mensaje JSON
toma casi siempre el mismo tiempo. Su espera es LA MITAD que en M/M/1, lo
que significa que dimensionar con M/M/1 es conservador.

Uso:
    python cola_mm1.py
    python cola_mm1.py --mu 200 --clientes 40000
"""
import argparse
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import simpy


def simular(lmbda, mu, n_clientes=20000, servicio="exponencial", semilla=42):
    """Simula una cola de un servidor y devuelve el tiempo medio en sistema."""
    random.seed(semilla)
    env = simpy.Environment()
    servidor = simpy.Resource(env, capacity=1)
    tiempos = []

    def cliente(env, llegada):
        with servidor.request() as req:
            yield req
            if servicio == "exponencial":
                yield env.timeout(random.expovariate(mu))
            else:                                   # determinista
                yield env.timeout(1.0 / mu)
            tiempos.append(env.now - llegada)

    def generador(env):
        for _ in range(n_clientes):
            yield env.timeout(random.expovariate(lmbda))
            env.process(cliente(env, env.now))

    env.process(generador(env))
    env.run()

    # Se descarta el primer 10 %: el sistema arranca vacio y ese transitorio
    # sesga la media hacia abajo. Omitir esto es el error mas comun.
    corte = len(tiempos) // 10
    return statistics.mean(tiempos[corte:])


def w_teorico_mm1(lmbda, mu):
    return 1.0 / (mu - lmbda)


def w_teorico_md1(lmbda, mu):
    rho = lmbda / mu
    return rho / (2 * mu * (1 - rho)) + 1.0 / mu     # espera + servicio


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mu", type=float, default=100.0,
                    help="Capacidad de servicio del gateway (mensajes/s)")
    ap.add_argument("--clientes", type=int, default=20000)
    ap.add_argument("--requisito", type=float, default=150.0,
                    help="Requisito de retardo en ms")
    a = ap.parse_args()

    rhos = np.arange(0.10, 0.96, 0.05)
    sim_mm1, teo_mm1, sim_md1, teo_md1 = [], [], [], []

    print(f"\nCapacidad de servicio mu = {a.mu:.0f} mensajes/s")
    print(f"{'rho':>6}{'lambda':>10}{'W_sim MM1':>12}{'W_teo MM1':>12}"
          f"{'err':>8}{'W_sim MD1':>12}{'W_teo MD1':>12}")
    print("-" * 74)

    for rho in rhos:
        lmbda = rho * a.mu
        s1 = simular(lmbda, a.mu, a.clientes, "exponencial") * 1000
        t1 = w_teorico_mm1(lmbda, a.mu) * 1000
        s2 = simular(lmbda, a.mu, a.clientes, "determinista") * 1000
        t2 = w_teorico_md1(lmbda, a.mu) * 1000
        sim_mm1.append(s1); teo_mm1.append(t1)
        sim_md1.append(s2); teo_md1.append(t2)
        print(f"{rho:>6.2f}{lmbda:>10.1f}{s1:>12.2f}{t1:>12.2f}"
              f"{abs(s1 - t1) / t1:>7.1%}{s2:>12.2f}{t2:>12.2f}")

    # Carga maxima admisible segun el requisito, usando el modelo M/M/1
    w_req = a.requisito / 1000.0
    lmbda_max = a.mu - 1.0 / w_req
    print("-" * 74)
    print(f"\nRequisito de retardo: {a.requisito:.0f} ms")
    print(f"Carga maxima admisible (M/M/1): lambda = {lmbda_max:.1f} mensajes/s")
    print(f"  equivale a rho = {lmbda_max / a.mu:.3f}")
    print(f"Con nodos que publican cada 60 s: {lmbda_max * 60:.0f} nodos como maximo")
    print("\nADVERTENCIA: operar a rho > 0.7 deja el sistema sin margen. "
          "Un pico de trafico dispara el retardo de forma no lineal.")

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))

    ax[0].plot(rhos, teo_mm1, "-", color="#002D72", label="M/M/1 analitico")
    ax[0].plot(rhos, sim_mm1, "o", color="#002D72", ms=4, label="M/M/1 simulado")
    ax[0].plot(rhos, teo_md1, "-", color="#006E3C", label="M/D/1 analitico")
    ax[0].plot(rhos, sim_md1, "s", color="#006E3C", ms=4, label="M/D/1 simulado")
    ax[0].axhline(a.requisito, ls="--", color="red",
                  label=f"Requisito {a.requisito:.0f} ms")
    ax[0].set_xlabel("Utilizacion rho"); ax[0].set_ylabel("Retardo medio (ms)")
    ax[0].set_title("Validacion del modelo")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)

    ax[1].plot(rhos, teo_mm1, "-", color="#002D72", lw=2)
    ax[1].axvline(0.7, ls=":", color="orange", lw=2, label="Limite practico 0.7")
    ax[1].axhline(a.requisito, ls="--", color="red")
    ax[1].set_yscale("log")
    ax[1].set_xlabel("Utilizacion rho"); ax[1].set_ylabel("Retardo medio (ms), log")
    ax[1].set_title("El retardo se dispara cuando rho tiende a 1")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3, which="both")

    fig.tight_layout()
    fig.savefig("validacion_colas.png", dpi=140)
    print("\nGrafica guardada: validacion_colas.png")
