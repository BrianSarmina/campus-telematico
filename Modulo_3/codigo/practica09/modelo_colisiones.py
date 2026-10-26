"""Modelo de colisiones del enlace RF - Modulo 3, Practica 9.

Responde, con UN solo nodo detector real, las preguntas que el hardware no
puede responder:

  1. Por que el modelo de ocupacion del Modulo 1 predijo miles de nodos.
  2. Que probabilidad tiene un intento de chocar, y si el modelo lo predice.
  3. Si los reintentos automaticos del radio (ARQ) resuelven las colisiones.
  4. Que pasa cuando los nodos se sincronizan, por diseno o por un corte de
     energia.
  5. Que mecanismo del firmware v3 corrige cada problema.
  6. Si RNF-03 (entrega >= 99 % con 3 nodos) se cumple, y bajo que politica.

Todo lo que este programa afirma sale de dos fuentes, y cada tabla dice
cual: ANALISIS (formulas) o SIMULACION (medio.py). Ninguna cifra es una
medicion de hardware.

Uso:
    python modelo_colisiones.py --rapido          # 1 minuto, para verificar
    python modelo_colisiones.py                   # completo, unos minutos
    python modelo_colisiones.py --secciones 2,3 --semillas 30
    python modelo_colisiones.py --ocupacion 0.25  # fraccion medida con el escaner
"""
import argparse
import statistics
import sys
import time

import medio as m


def titulo(n, texto):
    print()
    print("=" * 78)
    print("  {}. {}".format(n, texto))
    print("=" * 78)


def promedio_semillas(nodos, politica, duracion, semillas, base=100, **kw):
    """Perdida y fallo del primer intento, promediados sobre varias semillas.

    Devuelve (perdida_media, perdida_max, fallo_primer_intento_medio,
    intentos_por_trama_medio). La perdida se mide desde t = 10 s para no
    contar el arranque.
    """
    perd, prim, intent = [], [], []
    for s in range(semillas):
        r = m.simular(nodos, politica, duracion, semilla=base + s, **kw)
        e, g = r.entrega(desde_s=10)
        a, b = r.primer_intento()
        perd.append(1 - e / g if g else 0.0)
        prim.append(1 - a / b if b else 0.0)
        intent.append(r.intentos_por_trama())
    return (statistics.mean(perd), max(perd), statistics.mean(prim),
            statistics.mean(intent))


# --------------------------------------------------------------------------
def seccion1():
    titulo(1, "EL MODELO DE OCUPACION DEL MODULO 1   [ANALISIS]")
    t_m1 = 29 * 8 / 250e3
    # El Modulo 1 redondeo en cada paso: mu = 1075 tramas/s, lambda = 752
    mu_m1 = round(1 / round(t_m1, 5))
    n_m1 = int(0.7 * mu_m1) * 5
    t_ocu = m.T_AIRE + m.T_CONMUTACION + m.T_ACUSE
    n_exacto = m.capacidad_por_ocupacion(t_ocu, 5.0)
    print("  Modulo 1: trama de 29 B -> {:.2f} ms; rho <= 0.7; periodo 5 s".format(
        t_m1 * 1e3))
    print("            mu = {} tramas/s, lambda = {} -> N = {:,} nodos".format(
        mu_m1, int(0.7 * mu_m1), n_m1))
    print("  Con el formato exacto (trama {:.0f} us + conmutacion {:.0f} us +"
          " acuse {:.0f} us = {:.2f} ms):".format(
              m.T_AIRE * 1e6, m.T_CONMUTACION * 1e6, m.T_ACUSE * 1e6,
              t_ocu * 1e3))
    print("            N = 0.7 * 5 / {:.2f} ms = {:,.0f} nodos".format(
        t_ocu * 1e3, n_exacto))
    print()
    print("  LECTURA: los dos calculos dicen 'miles'. Los dos suponen que las")
    print("  tramas se reparten en el tiempo como clientes en una fila. En un")
    print("  medio sin deteccion de portadora no hay fila: dos tramas que se")
    print("  traslapan se destruyen aunque el canal este libre el 99 % del")
    print("  tiempo. El limite lo pone la colision, no la ocupacion.")


# --------------------------------------------------------------------------
def seccion2(semillas, duracion):
    titulo(2, "COLISION DEL PRIMER INTENTO   [ANALISIS vs SIMULACION]")
    T = 5.0
    tau_m1 = 29 * 8 / 250e3
    print("  Ventana vulnerable: Modulo 1 = 2 tramas = {:.2f} ms;".format(
        2 * tau_m1 * 1e3))
    print("  completa (trama + conmutacion + acuse, ambos lados) = {:.2f} ms".format(
        m.VENTANA_VULNERABLE * 1e3))
    print("  La simulacion usa la politica v3 (fases aleatorias que no se")
    print("  sincronizan), {} semillas de {:.0f} s.".format(semillas, duracion))
    print()
    print("  {:>6} {:>13} {:>13} {:>13} {:>13}".format(
        "Nodos", "Mod.1 (2tau)", "Ventana compl", "ALOHA Poisson", "Simulado"))
    print("  " + "-" * 62)
    filas = []
    for N in (2, 3, 10, 50, 200):
        p_m1 = 1 - (1 - 2 * tau_m1 / T) ** (N - 1)
        p_v = m.p_colision_periodica(N, T + m.T_PROCESO)
        p_a = m.p_colision_aloha(m.carga_ofrecida(N, T + m.T_PROCESO,
                                                  m.VENTANA_VULNERABLE / 2))
        _, _, prim, _ = promedio_semillas(N, m.POLITICA_V3, duracion, semillas)
        filas.append((N, p_v, prim))
        print("  {:>6} {:>12.3%} {:>12.3%} {:>12.3%} {:>12.3%}".format(
            N, p_m1, p_v, p_a, prim))
    print()
    print("  LECTURA: con la ventana completa, la formula y la simulacion")
    print("  coinciden mientras los reintentos de los demas no pesen. Con 200")
    print("  nodos la simulacion queda por encima: los reintentos ya son")
    print("  trafico, y la formula no los cuenta. Con pocos nodos y pocas")
    print("  semillas la simulacion puede dar 0 %: el evento es raro, no")
    print("  imposible. La degradacion empieza en decenas de nodos, no en miles.")
    print("  Con 3 nodos (RNF-03) el primer intento choca una vez en mil.")
    return filas


# --------------------------------------------------------------------------
def seccion3(semillas, duracion):
    titulo(3, "LO ARREGLA EL ARQ?   [SIMULACION]")
    print("  El driver reintenta hasta 8 veces, con el MISMO retardo (1750 us)")
    print("  en todos los nodos. Si los intentos fueran independientes, la")
    print("  perdida seria p^9. Para aislar el efecto del ARQ, aqui la")
    print("  fluctuacion de proceso es de 5 ms, suficiente para que los nodos")
    print("  no se agrupen (eso es la seccion 4).")
    print()
    print("  {:>6} {:>14} {:>14} {:>14} {:>14}".format(
        "Nodos", "Choca 1er int", "Pred. indep.", "Perdida v1", "Perdida v3"))
    print("  " + "-" * 66)
    for N in (10, 50, 200):
        pv1, _, p1, _ = promedio_semillas(N, m.POLITICA_V1, duracion,
                                          semillas, sigma_proceso_s=0.005)
        pv3, _, _, _ = promedio_semillas(N, m.POLITICA_V3, duracion, semillas,
                                         sigma_proceso_s=0.005)
        print("  {:>6} {:>13.3%} {:>13.2e} {:>13.3%} {:>13.3%}".format(
            N, p1, m.p_perdida_independiente(p1, m.ARC_DRIVER), pv1, pv3))
    print()
    print("  LECTURA: con el driver tal cual (v1), la perdida queda cerca de la")
    print("  probabilidad de chocar en el primer intento, no de p^9. Dos nodos")
    print("  que chocan reintentan con el mismo retardo, asi que vuelven a")
    print("  chocar en los 8 reintentos. El ARQ protege contra el ruido, no")
    print("  contra un vecino que se comporta exactamente igual. La v3 elige el")
    print("  retardo al azar antes de cada trama, y los reintentos se separan.")


# --------------------------------------------------------------------------
def seccion4(semillas, duracion):
    titulo(4, "SINCRONIA   [SIMULACION]")
    print("  a) Agrupamiento. El firmware del Modulo 1 duerme PERIODO_S DESPUES")
    print("     de transmitir. Dos nodos que chocan agotan los reintentos y se")
    print("     retrasan lo mismo (unos 24 ms), y siguen juntos. Si en su camino")
    print("     tocan a un tercero, lo arrastran. La fluctuacion del tiempo de")
    print("     proceso es la unica fuerza que los separa, y no se conoce: se")
    print("     mide en la Practica 10.")
    print()
    print("  {:>16} {:>14} {:>14} {:>14}".format(
        "Fluct. proceso", "Perdida v1", "Peor semilla", "Perdida v3"))
    print("  " + "-" * 62)
    for sig in (0.00002, 0.0002, 0.001, 0.005):
        pv1, mx, _, _ = promedio_semillas(50, m.POLITICA_V1, duracion, semillas,
                                          sigma_proceso_s=sig)
        pv3, _, _, _ = promedio_semillas(50, m.POLITICA_V3, duracion, semillas,
                                         sigma_proceso_s=sig)
        print("  {:>13.2f} ms {:>13.2%} {:>13.2%} {:>13.3%}".format(
            sig * 1e3, pv1, mx, pv3))
    print("  (50 nodos; la probabilidad de choque del primer intento es {:.1%})".format(
        m.p_colision_periodica(50, 5.0 + m.T_PROCESO)))
    print()
    print("  b) Corte de energia. Los 3 nodos de RNF-03 se encienden dentro de")
    print("     1 ms. Entrega en los primeros 2 minutos, {} semillas:".format(
        semillas))
    print()
    print("  {:>16} {:>14} {:>14}".format("Fluct. proceso", "Entrega v1",
                                          "Entrega v3"))
    print("  " + "-" * 46)
    for sig in (0.0002, 0.002):
        fila = []
        for pol in (m.POLITICA_V1, m.POLITICA_V3):
            ent = []
            for s in range(semillas):
                r = m.simular(3, pol, 120, semilla=300 + s,
                              dispersion_arranque_s=0.001, sigma_proceso_s=sig)
                e, g = r.entrega()
                ent.append(e / g)
            fila.append(statistics.mean(ent))
        print("  {:>13.2f} ms {:>13.1%} {:>13.1%}".format(sig * 1e3, *fila))
    print()
    print("  LECTURA: despues de un apagon, con el firmware del Modulo 1 los")
    print("  tres nodos pueden quedar transmitiendo juntos y chocando durante")
    print("  minutos. Es exactamente el momento en que un incendio pudo haber")
    print("  causado el apagon. La v3 espera un tiempo aleatorio al arrancar.")


# --------------------------------------------------------------------------
def seccion5(semillas, duracion):
    titulo(5, "QUE MECANISMO CORRIGE QUE   [SIMULACION]")
    base = m.POLITICA_V1
    ard = {"ard_aleatorio": True, "ard_idx": m.POLITICA_V3["ard_idx"]}
    variantes = [
        ("v1 (driver tal cual)", base),
        ("v1 + fluctuacion 10 %", dict(base, fluctuacion=0.10)),
        ("v1 + ARD aleatorio", dict(base, **ard)),
        ("v3 sin fluctuacion", dict(m.POLITICA_V3, fluctuacion=0.0)),
        ("v3 completa", m.POLITICA_V3),
    ]
    condiciones = [("50 nodos, sin interferencia", 50, 0.0),
                   ("200 nodos, Wi-Fi al 30 %", 200, 0.30)]
    for nombre_c, N, ocup in condiciones:
        print("  {}".format(nombre_c))
        print("  {:<26} {:>10} {:>13} {:>12} {:>15}".format(
            "Politica", "Perdida", "Peor semilla", "Racha max.", "Intentos/trama"))
        print("  " + "-" * 80)
        for nombre, pol in variantes:
            perd, rachas, intent = [], [], []
            for s in range(semillas):
                r = m.simular(N, pol, duracion, semilla=700 + s,
                              ocupacion_wifi=ocup)
                e, g = r.entrega(desde_s=10)
                perd.append(1 - e / g)
                rachas.append(r.racha_maxima())
                intent.append(r.intentos_por_trama())
            print("  {:<26} {:>9.3%} {:>12.3%} {:>12d} {:>15.3f}".format(
                nombre, statistics.mean(perd), max(perd), max(rachas),
                statistics.mean(intent)))
        print()
    print("  LECTURA: el ARD aleatorio es el mecanismo principal: rompe el")
    print("  choque repetido dentro de una trama, y como los nodos terminan")
    print("  de transmitir en instantes distintos, tambien los separa. La")
    print("  fluctuacion del periodo tiene un costo y un beneficio: con poca")
    print("  carga convierte un choque raro y persistente en un choque al azar")
    print("  en cada periodo, y la perdida media sube un poco; con mucha carga")
    print("  e interferencia corta las rachas largas. La racha maxima es la")
    print("  cifra que retrasa una alarma (Practica 10). El costo de no perder")
    print("  se ve en intentos por trama: es tiempo de aire.")


# --------------------------------------------------------------------------
def seccion6(horas, semillas, ocupacion, rafaga):
    titulo(6, "RNF-03: ENTREGA >= 99 % CON 3 NODOS   [ANALISIS + SIMULACION]")
    dur = horas * 3600
    print("  Analisis: probabilidad de choque del primer intento con 3 nodos")
    print("  = {:.3%}. Si las fases fueran independientes y ningun".format(
        m.p_colision_periodica(3, 5.0 + m.T_PROCESO)))
    print("  reintento recuperara el choque (v1), la perdida quedaria 10 veces")
    print("  por debajo del 1 %. La simulacion pone a prueba ese 'si'.")
    print()
    print("  Simulacion: {:.1f} h por corrida, {} semillas. El intervalo de".format(
        horas, semillas))
    print("  Wilson supone tramas independientes; en este medio no lo son, por")
    print("  eso se reporta tambien la peor semilla, y el veredicto solo es")
    print("  'cumple' si el intervalo Y la peor semilla quedan sobre el 99 %.")
    print()
    escenarios = [
        ("Regimen, sin interferencia", {}),
        ("Regimen, Wi-Fi {:.0%} rafagas {:.0f} ms".format(ocupacion, rafaga * 1e3),
         {"ocupacion_wifi": ocupacion, "rafaga_media_s": rafaga}),
        ("Tras un apagon (1 ms)", {"dispersion_arranque_s": 0.001}),
    ]
    print("  {:<34} {:>4} {:>9} {:>17} {:>9} {:>14}".format(
        "Escenario", "Pol.", "Entrega", "IC 95 % (Wilson)", "Peor", "Veredicto"))
    print("  " + "-" * 92)
    filas = []
    for nombre, kw in escenarios:
        for pol in (m.POLITICA_V1, m.POLITICA_V3):
            ent, tot, peor = 0, 0, 1.0
            d = dur if "dispersion_arranque_s" not in kw else min(dur, 600)
            for s in range(semillas):
                r = m.simular(3, pol, d, semilla=500 + s, **kw)
                e, g = r.entrega()
                ent += e
                tot += g
                peor = min(peor, e / g)
            b, a = m.wilson(ent, tot)
            v = m.veredicto(ent, tot, 0.99)
            if v == "cumple" and peor < 0.99:
                v = "no concluyente"
            filas.append((nombre, pol["nombre"], ent / tot, b, a, peor, v))
            print("  {:<34} {:>4} {:>8.3%}  [{:.4f}, {:.4f}] {:>8.2%} {:>14}".format(
                nombre, pol["nombre"], ent / tot, b, a, peor, v))
    print("  (el escenario del apagon dura 10 min: es un transitorio)")
    print()
    print("  Para demostrarlo con UN enlace real haria falta enviar {} tramas".format(
        m.tramas_para_demostrar(0.99)))
    print("  seguidas sin perder ninguna. Eso prueba el enlace, no los 3 nodos.")
    print()
    v1_reg = [f for f in filas if f[1] == "v1" and f[0].startswith("Regimen")]
    v3_ok = all(f[6] == "cumple" for f in filas if f[1] == "v3")
    print("  LECTURA:")
    if any(f[5] < 0.99 for f in v1_reg):
        print("  - En regimen la v1 cumple en promedio, pero no en todas las")
        print("    semillas: cuando dos nodos se alinean se quedan alineados y")
        print("    pierden en rachas. Un promedio no basta para afirmar RNF-03.")
    else:
        print("  - En estas corridas la v1 cumple en regimen. Con mas semillas o")
        print("    mas horas puede aparecer una alineacion que no cumple: corra")
        print("    la version completa antes de concluir.")
    print("  - Tras un apagon, la v1 queda muy por debajo del 99 %: es un")
    print("    transitorio de minutos, justo cuando mas importa.")
    if v3_ok:
        print("  - La v3 cumple en los tres escenarios.")
    else:
        print("  - La v3 no alcanza veredicto en todos los escenarios con esta")
        print("    muestra; con la version completa la muestra es mayor.")
    print()
    print("  CONCLUSION PARA LA MATRIZ DE VERIFICACION")
    print("  RNF-03 se verifica por ANALISIS y SIMULACION, no por prueba: el")
    print("  grupo tiene un solo detector. La simulacion depende de los")
    print("  supuestos S1-S6 de medio.py; el informe debe declararlos.")
    return filas


# --------------------------------------------------------------------------
def grafica(semillas, duracion, archivo):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(Sin matplotlib: se omite la grafica)")
        return
    Ns = [3, 10, 20, 50, 100, 200]
    teo = [m.p_colision_periodica(N, 5.0 + m.T_PROCESO) for N in Ns]
    v1, v3 = [], []
    for N in Ns:
        # Con pocos nodos la perdida es rara: se simula mas tiempo para que
        # cada punto tenga del orden de 6000 tramas por semilla.
        d = max(duracion, 30000.0 / N)
        v1.append(promedio_semillas(N, m.POLITICA_V1, d, semillas)[0])
        v3.append(promedio_semillas(N, m.POLITICA_V3, d, semillas)[0])
    piso = 1e-6
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(Ns, teo, "k--", label="Choque del 1er intento (analisis)")
    for serie, color, marca, nombre, tam in ((v1, "#B00020", "o", "v1", 9),
                                             (v3, "#002D72", "s", "v3", 5)):
        ax.plot(Ns, [max(x, piso) for x in serie], "-", color=color)
        llenos = [(n, x) for n, x in zip(Ns, serie) if x > 0]
        vacios = [(n, piso) for n, x in zip(Ns, serie) if x == 0]
        if llenos:
            ax.plot(*zip(*llenos), marca, color=color, ms=tam,
                    label="Perdida {} (simulacion)".format(nombre))
        if vacios:
            ax.plot(*zip(*vacios), marca, color=color, mfc="white", ms=tam)
    ax.plot([], [], "o", color="gray", mfc="white",
            label="0 perdidas en la muestra")
    ax.axhline(0.01, color="#B08D57", lw=1)
    ax.text(3.1, 0.012, "RNF-03: 1 % de perdida", color="#B08D57", fontsize=8)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(piso * 0.8, 1)
    ax.set_xlabel("Nodos en el canal")
    ax.set_ylabel("Fraccion")
    ax.set_title("Colision y perdida con periodo de 5 s ({} semillas)".format(
        semillas), fontsize=10)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(archivo, dpi=150)
    print("\nGrafica guardada: {}  (un punto hueco: 0 perdidas en la muestra)".format(
        archivo))


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rapido", action="store_true",
                    help="corrida corta para verificar (3 semillas, 120 s)")
    ap.add_argument("--semillas", type=int, default=20)
    ap.add_argument("--duracion", type=float, default=300.0,
                    help="segundos simulados por corrida (secciones 2-5)")
    ap.add_argument("--horas", type=float, default=24.0,
                    help="horas simuladas por corrida en la seccion 6")
    ap.add_argument("--ocupacion", type=float, default=0.30,
                    help="fraccion del tiempo con Wi-Fi en el canal (seccion 6)")
    ap.add_argument("--rafaga", type=float, default=0.002,
                    help="duracion media de cada rafaga Wi-Fi, en s")
    ap.add_argument("--secciones", default="1,2,3,4,5,6")
    ap.add_argument("--grafica", default="colisiones.png",
                    help="archivo PNG; 'no' para omitir")
    a = ap.parse_args()
    if a.rapido:
        a.semillas, a.duracion, a.horas = 3, 120.0, 1.0
    sec = {int(x) for x in a.secciones.split(",") if x.strip()}

    t0 = time.time()
    print("MODELO DE COLISIONES DEL ENLACE RF - Practica 9")
    print("Semillas: {}  Duracion: {:.0f} s  Seccion 6: {:.1f} h".format(
        a.semillas, a.duracion, a.horas))
    if 1 in sec:
        seccion1()
    if 2 in sec:
        seccion2(a.semillas, a.duracion)
    if 3 in sec:
        seccion3(a.semillas, a.duracion)
    if 4 in sec:
        seccion4(a.semillas, a.duracion)
    if 5 in sec:
        seccion5(a.semillas, a.duracion)
    if 6 in sec:
        seccion6(a.horas, max(1, a.semillas // 4), a.ocupacion, a.rafaga)
    if a.grafica != "no":
        grafica(a.semillas, a.duracion, a.grafica)
    print("\nTiempo de ejecucion: {:.0f} s".format(time.time() - t0))


if __name__ == "__main__":
    sys.exit(main())
