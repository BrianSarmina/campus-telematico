"""Prioridad de la alarma en un medio ocupado - Modulo 3, Practica 10.

Pregunta: cuanto del margen de RNF-01 (alarma en menos de 15 s) consume el
enlace de radio cuando el canal esta ocupado, y que cambia la politica v3.

  1. El margen: el presupuesto del Modulo 1 (10.59 s) contra los 15 s
     renegociados deja 4.41 s para todo lo que el presupuesto no conto.
  2. Un nodo, canal ocupado por Wi-Fi: la situacion real del laboratorio.
  3. Tres nodos tras un apagon, y un incendio que los alcanza a los tres:
     el caso que la sincronia vuelve peligroso.
  4. Prioridad por persistencia: cuanto mejora la alarma y cuanto aire
     cuesta.

Fuentes: SIMULACION con practica09/medio.py (supuestos S1-S6) y dos
parametros que se MIDEN en la Practica 10:
  --sigma      fluctuacion natural del ciclo del nodo, en segundos
               (medir_enlace.py con POLITICA = "v1": 'desviacion' / 1e6)
  --ocupacion  fraccion del canal ocupada por Wi-Fi (ver_espectro.py)

Uso:
    python simular_prioridad.py --rapido
    python simular_prioridad.py --sigma 0.0004 --ocupacion 0.35
"""
import argparse
import os
import statistics
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "practica09"))
import medio as m  # noqa: E402

PRESUPUESTO_M1_S = 10.59     # practica03/presupuesto_retardo.py (Modulo 1)
REQUISITO_S = 15.0           # RNF-01 renegociado
MARGEN_S = REQUISITO_S - PRESUPUESTO_M1_S


def titulo(n, texto):
    print()
    print("=" * 78)
    print("  {}. {}".format(n, texto))
    print("=" * 78)


def alternancias(nodos, duracion, cada=20.0, inicio=15.0):
    """Cambios normal <-> alarma cada `cada` s para los nodos indicados."""
    cambios, t, est = [], inicio, m.ALARMA
    while t < duracion - cada:
        for i in nodos:
            cambios.append((t, i, est))
        est = m.NORMAL if est == m.ALARMA else m.ALARMA
        t += cada
    return cambios


def retardos_alarma(res):
    """Retardos de las transiciones HACIA alarma."""
    return [tr["retardo"] for tr in res.transiciones if tr["estado"] == m.ALARMA]


def fila_retardos(nombre, ds):
    finitos = [d for d in ds if d != float("inf")]
    nunca = len(ds) - len(finitos)
    exceso = sum(1 for d in ds if d > MARGEN_S)
    print("  {:<30} {:>5} {:>9.3f} {:>9.3f} {:>9.3f} {:>9} {:>10}".format(
        nombre, len(ds), m.percentil(ds, 50), m.percentil(ds, 95),
        max(finitos) if finitos else float("nan"),
        "{}/{}".format(exceso, len(ds)), nunca))
    return exceso


def encabezado():
    print("  {:<30} {:>5} {:>9} {:>9} {:>9} {:>9} {:>10}".format(
        "Caso", "n", "p50 (s)", "p95 (s)", "max (s)", "> margen", "sin llegar"))
    print("  " + "-" * 86)


# --------------------------------------------------------------------------
def seccion1():
    titulo(1, "EL MARGEN DE RNF-01   [DEL DISENO]")
    print("  Presupuesto de la cadena de alarma (Modulo 1) : {:5.2f} s".format(
        PRESUPUESTO_M1_S))
    print("  RNF-01 renegociado                            : {:5.2f} s".format(
        REQUISITO_S))
    print("  Margen para lo que el presupuesto no conto    : {:5.2f} s".format(
        MARGEN_S))
    print()
    print("  El presupuesto asigno 0.00 s a la transmision por radio: supuso")
    print("  que la trama de la transicion llega al primer intento. Si se")
    print("  pierde, la siguiente sale 1 s despues (periodo en alarma). Cinco")
    print("  tramas perdidas seguidas agotan el margen.")


# --------------------------------------------------------------------------
def seccion2(horas, semillas, rafaga, ocupaciones):
    titulo(2, "UN NODO, CANAL OCUPADO POR WI-FI   [SIMULACION]")
    print("  El nodo alterna normal <-> alarma cada 20 s durante {:.1f} h;".format(
        horas))
    print("  se mide el retardo de cada transicion HACIA alarma, desde que el")
    print("  nodo la transmite hasta que llega al concentrador. Rafagas de")
    print("  {:.0f} ms. {} semillas.".format(rafaga * 1e3, semillas))
    print()
    encabezado()
    dur = horas * 3600
    for ocup in ocupaciones:
        for pol in (m.POLITICA_V1, m.POLITICA_V3):
            ds = []
            for s in range(semillas):
                r = m.simular(1, pol, dur, semilla=2000 + s,
                              ocupacion_wifi=ocup, rafaga_media_s=rafaga,
                              cambios=alternancias([1], dur))
                ds += retardos_alarma(r)
            fila_retardos("Wi-Fi {:>3.0%}, {}".format(ocup, pol["nombre"]), ds)
    print()
    print("  LECTURA: mientras el canal no este saturado, la transicion llega")
    print("  al primer envio y el enlace no toca el margen. Con el canal muy")
    print("  ocupado la v1 empieza a perder la primera trama y el retardo salta")
    print("  en multiplos de 1 s; la v3 insiste por software antes de esperar")
    print("  al periodo siguiente, y el retardo se queda en milisegundos.")


# --------------------------------------------------------------------------
def seccion3(semillas, sigmas):
    titulo(3, "TRES NODOS TRAS UN APAGON, EL INCENDIO LOS ALCANZA A LOS TRES"
           "   [SIMULACION]")
    print("  Los 3 nodos se encienden dentro de 1 ms. A los 30 s los tres")
    print("  pasan a alarma en su siguiente ciclo. Sin azar, comparten ciclo:")
    print("  pasan a 1 s a la vez y siguen transmitiendo juntos.")
    print("  La fluctuacion natural del ciclo (sigma) decide cuanto duran")
    print("  juntos; se mide en el nodo real (Practica 10, paso 2).")
    print()
    encabezado()
    peores = {}
    for sig in sigmas:
        for pol in (m.POLITICA_V1, m.POLITICA_V3):
            ds = []
            for s in range(semillas):
                r = m.simular(3, pol, 400, semilla=1000 + s,
                              dispersion_arranque_s=0.001,
                              sigma_proceso_s=sig,
                              cambios=[(30.0, i, m.ALARMA) for i in (1, 2, 3)])
                ds += retardos_alarma(r)
            ex = fila_retardos("sigma {:.2f} ms, {}".format(
                sig * 1e3, pol["nombre"]), ds)
            peores[(sig, pol["nombre"])] = (ex, len(ds))
    print()
    print("  LECTURA: con la v1 y un ciclo muy regular, los tres nodos chocan")
    print("  en cada intento de cada periodo: los reintentos usan el mismo")
    print("  retardo y el periodo es el mismo. La alarma puede tardar minutos.")
    print("  Con mas fluctuacion natural se separan solos, pero eso depende")
    print("  del hardware, no del diseno. La v3 no depende de esa suerte.")
    return peores


# --------------------------------------------------------------------------
def seccion4(semillas, duracion):
    titulo(4, "PRIORIDAD POR PERSISTENCIA: BENEFICIO Y COSTO   [SIMULACION]")
    print("  20 nodos; Wi-Fi al 50 % en rafagas LARGAS de 50 ms (ilustrativo de")
    print("  un canal con trafico pesado, como video). Una rafaga asi dura mas")
    print("  que los 9 intentos de una llamada a send(): el ARQ del radio no la")
    print("  esquiva. El nodo 1 alterna normal <-> alarma; los demas, rutina.")
    print("  Se varia cuantos reintentos por software se permiten a una trama")
    print("  prioritaria; la rutina siempre tiene 1.")
    print()
    print("  {:<14} {:>8} {:>8} {:>8} {:>8} {:>14} {:>14}".format(
        "SW de alarma", "p50 (s)", "p95 (s)", "max (s)", "> 1 s",
        "Int./rutina", "Int./alarma"))
    print("  " + "-" * 80)
    for sw in (0, 2, 6):
        pol = dict(m.POLITICA_V3, sw_prioridad=sw)
        ds, it_r, it_p = [], [], []
        for s in range(semillas):
            r = m.simular(20, pol, duracion, semilla=3000 + s,
                          ocupacion_wifi=0.5, rafaga_media_s=0.050,
                          cambios=alternancias([1], duracion))
            ds += retardos_alarma(r)
            it_r += [t["intentos"] for t in r.tramas
                     if t["cerrada"] and not t["prioridad"]]
            it_p += [t["intentos"] for t in r.tramas
                     if t["cerrada"] and t["prioridad"]]
        finitos = [d for d in ds if d != float("inf")]
        print("  {:<14} {:>8.3f} {:>8.3f} {:>8.3f} {:>8} {:>14.2f} {:>14.2f}".format(
            sw, m.percentil(ds, 50), m.percentil(ds, 95),
            max(finitos) if finitos else float("nan"),
            "{}/{}".format(sum(1 for d in ds if d > 1.0), len(ds)),
            statistics.mean(it_r) if it_r else 0.0,
            statistics.mean(it_p) if it_p else 0.0))
    print()
    print("  LECTURA: sin reintentos por software, una trama que cae en una")
    print("  rafaga larga se pierde y la alarma espera al periodo siguiente")
    print("  (1 s), o a varios. Con 6 reintentos y retroceso exponencial (cada")
    print("  espera es de hasta 10, 20, ... 320 ms) la trama sale de la rafaga.")
    print("  El costo se ve en los intentos de las tramas prioritarias; la")
    print("  rutina no paga. Sin deteccion de portadora, la prioridad no se")
    print("  pide al medio: se compra con persistencia propia.")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--semillas", type=int, default=10)
    ap.add_argument("--horas", type=float, default=2.0,
                    help="horas simuladas por corrida en la seccion 2")
    ap.add_argument("--duracion", type=float, default=600.0,
                    help="segundos simulados por corrida en la seccion 4")
    ap.add_argument("--rafaga", type=float, default=0.002)
    ap.add_argument("--ocupacion", type=float, default=None,
                    help="ocupacion medida; se agrega a la seccion 2")
    ap.add_argument("--sigma", type=float, action="append", default=None,
                    help="sigma medida en segundos; se puede repetir")
    ap.add_argument("--secciones", default="1,2,3,4")
    a = ap.parse_args()
    if a.rapido:
        a.semillas, a.horas, a.duracion = 3, 0.25, 180.0
    sigmas = a.sigma or [0.0002, 0.002]
    ocupaciones = [0.0, 0.3, 0.5, 0.7]
    if a.ocupacion is not None and a.ocupacion not in ocupaciones:
        ocupaciones = sorted(ocupaciones + [a.ocupacion])
    sec = {int(x) for x in a.secciones.split(",") if x.strip()}

    t0 = time.time()
    print("PRIORIDAD DE LA ALARMA EN UN MEDIO OCUPADO - Practica 10")
    print("Semillas: {}  Seccion 2: {:.2f} h  Seccion 4: {:.0f} s".format(
        a.semillas, a.horas, a.duracion))
    if 1 in sec:
        seccion1()
    if 2 in sec:
        seccion2(a.horas, a.semillas, a.rafaga, ocupaciones)
    if 3 in sec:
        seccion3(a.semillas, sigmas)
    if 4 in sec:
        seccion4(a.semillas, a.duracion)
    print()
    print("CONCLUSION PARA LA MATRIZ DE VERIFICACION")
    print("  RNF-01 se verifica por PRUEBA con un nodo (secadora, Practica 10)")
    print("  y por SIMULACION en lo que un nodo no puede mostrar: varios nodos")
    print("  y el apagon. 'margen' = {:.2f} s = 15 s - 10.59 s.".format(MARGEN_S))
    print("\nTiempo de ejecucion: {:.0f} s".format(time.time() - t0))


if __name__ == "__main__":
    main()
