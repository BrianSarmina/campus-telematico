"""Medio compartido del enlace RF - Modulo 3, Practicas 9 y 10. Biblioteca.

Simula, evento por evento, varios nodos detectores que transmiten por el
mismo canal del nRF24L01 hacia un solo concentrador. Existe porque el grupo
tiene UN detector real: las preguntas sobre varios nodos (colisiones,
sincronia, RNF-03 con 3 nodos) solo se pueden responder por analisis y por
simulacion, y el informe debe declararlo asi.

La usan:
    modelo_colisiones.py           (P9)
    ../practica10/simular_prioridad.py  (P10)

SUPUESTOS DEL MODELO (cada uno es una decision, no un hecho)
  S1  Sin deteccion de portadora: el nRF24L01 transmite sin escuchar antes.
  S2  Sin efecto captura: dos transmisiones que se traslapan, aunque sea un
      microsegundo, se destruyen las dos. Es la suposicion pesimista.
  S3  Cada intento ocupa el aire con la trama (T_AIRE) y, si la trama llego,
      con el acuse (T_ACUSE) tras la conmutacion (T_CONMUTACION). Un acuse
      destruido se ve en el nodo igual que una trama perdida.
  S4  El reintento automatico empieza ARD despues del FIN de la trama
      (registro SETUP_RETR de la hoja de datos del nRF24L01+).
  S5  Cada nodo tiene un reloj con deriva fija, uniforme en +-deriva_ppm, y
      un tiempo de proceso por ciclo que fluctua con desviacion sigma.
  S6  La interferencia Wi-Fi se modela como rafagas de ocupacion con duracion
      y separacion exponenciales. Cualquier traslape destruye el intento.
      Es un modelo de primer orden de "canal ocupado", NO un modelo de Wi-Fi.

Este archivo es ASCII puro y no tiene dependencias fuera de la biblioteca
estandar. Ejecutarlo corre una autoprueba corta:
    python medio.py
"""
import bisect
import heapq
import math
import random

# --------------------------------------------------------------------------
#  Parametros fisicos del enlace (de diseno y de la hoja de datos)
# --------------------------------------------------------------------------
VELOCIDAD_BPS = 250_000
# Paquete Enhanced ShockBurst: preambulo 1 B, direccion 5 B, campo de control
# de 9 bits, carga util y CRC de 2 B.
BITS_TRAMA = (1 + 5 + 18 + 2) * 8 + 9          # 217 bits
BITS_ACUSE = (1 + 5 + 0 + 2) * 8 + 9           # 73 bits, acuse sin carga
T_AIRE = BITS_TRAMA / VELOCIDAD_BPS            # 868 us
T_ACUSE = BITS_ACUSE / VELOCIDAD_BPS           # 292 us
T_CONMUTACION = 130e-6                         # cambio RX <-> TX del radio
T_ENCENDIDO = 1.5e-3                           # espera de send_start() del driver
ARD_DRIVER = 1750e-6                           # SETUP_RETR = (6 << 4) | 8
ARC_DRIVER = 8

# Ventana vulnerable de un intento: otro intento (trama + acuse) que empiece
# dentro de ella se traslapa con la trama o con el acuse propios.
VENTANA_VULNERABLE = 2 * (T_AIRE + T_CONMUTACION + T_ACUSE)    # 2.58 ms

# --------------------------------------------------------------------------
#  Parametros del nodo (del firmware)
# --------------------------------------------------------------------------
PERIODO_S = 5.0
PERIODO_POR_ESTADO = {0: PERIODO_S, 1: 2.0, 2: 1.0, 3: 1.0}
T_PROCESO = 0.170       # ventana de flama 150 ms + ADC + BME280 (aproximado)
NORMAL, VIGILANCIA, PREALARMA, ALARMA = 0, 1, 2, 3

# --------------------------------------------------------------------------
#  Politicas de acceso al medio. Deben coincidir con el firmware del nodo
#  (firmware/nodo_detector/main.py); pruebas_modulo3.py lo comprueba.
# --------------------------------------------------------------------------
POLITICA_V1 = {
    "nombre": "v1",
    "arc": ARC_DRIVER,
    "ard_aleatorio": False,      # ARD fijo de 1750 us, igual en todos
    "ard_idx": (6, 6),
    "sw_rutina": 0,              # sin reintentos por software
    "sw_prioridad": 0,
    "espera_sw_base_s": 0.010,
    "fluctuacion": 0.0,          # periodo exacto
    "espera_arranque": False,
}

POLITICA_V3 = {
    "nombre": "v3",
    "arc": ARC_DRIVER,
    "ard_aleatorio": True,       # ARD elegido al azar antes de cada trama
    "ard_idx": (3, 15),          # (k + 1) * 250 us: de 1000 a 4000 us
    "sw_rutina": 1,              # la rutina insiste poco
    "sw_prioridad": 6,           # la transicion y la alarma insisten mucho
    "espera_sw_base_s": 0.010,   # retroceso exponencial: U(0, base * 2^i)
    "fluctuacion": 0.10,         # periodo * U(0.9, 1.1)
    "espera_arranque": True,     # espera U(0, PERIODO_S) al arrancar
}

POLITICAS = {"v1": POLITICA_V1, "v3": POLITICA_V3}


# --------------------------------------------------------------------------
#  Modelos analiticos
# --------------------------------------------------------------------------
def capacidad_por_ocupacion(t_ocupacion, periodo_s, rho_max=0.7):
    """Nodos que caben si solo importara la OCUPACION del canal (Modulo 1)."""
    return rho_max * periodo_s / t_ocupacion


def carga_ofrecida(nodos, periodo_s, t_aire=T_AIRE):
    """G: fraccion del tiempo que el canal estaria ocupado sin reintentos."""
    return nodos * t_aire / periodo_s


def p_colision_aloha(G):
    """Colision de un intento en ALOHA puro con llegadas de Poisson."""
    return 1.0 - math.exp(-2.0 * G)


def p_colision_periodica(nodos, periodo_s, ventana=VENTANA_VULNERABLE):
    """Colision del primer intento con nodos periodicos de fase aleatoria.

    Cada uno de los otros N-1 nodos cae en la ventana vulnerable con
    probabilidad ventana/periodo. Es la formula del Modulo 1 con la ventana
    completa (trama + acuse) en lugar de 2 tramas.
    """
    q = min(1.0, ventana / periodo_s)
    return 1.0 - (1.0 - q) ** (nodos - 1)


def p_perdida_independiente(p_intento, reintentos):
    """Perdida tras agotar los reintentos SI los intentos son independientes.

    Esa condicion es justo la que la sincronia rompe.
    """
    return p_intento ** (reintentos + 1)


def wilson(exitos, n, z=1.96):
    """Intervalo de confianza de Wilson para una proporcion (95 %).

    Se usa en lugar de p +- z*sqrt(p(1-p)/n) porque ese intervalo colapsa a
    ancho cero cuando no hay perdidas: con 50 de 50 diria "100 % +- 0 %".
    """
    if n == 0:
        return 0.0, 1.0
    p = exitos / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    medio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - medio), min(1.0, centro + medio)


def tramas_para_demostrar(tasa_minima, confianza=0.95):
    """Tramas consecutivas SIN perdida para afirmar tasa >= tasa_minima.

    Si no se pierde ninguna de n, la cota superior de la perdida al nivel de
    confianza dado es 1 - (1 - confianza)^(1/n). Se despeja n.
    """
    return math.ceil(math.log(1 - confianza) / math.log(tasa_minima))


def veredicto(exitos, n, objetivo, z=1.96):
    """'cumple', 'no cumple' o 'no concluyente' segun el intervalo."""
    bajo, alto = wilson(exitos, n, z)
    if bajo >= objetivo:
        return "cumple"
    if alto < objetivo:
        return "no cumple"
    return "no concluyente"


def percentil(valores, p):
    """Percentil por el metodo del rango mas cercano (sin interpolar)."""
    if not valores:
        return float("nan")
    v = sorted(valores)
    k = max(0, min(len(v) - 1, int(math.ceil(p / 100.0 * len(v))) - 1))
    return v[k]


# --------------------------------------------------------------------------
#  Interferencia
# --------------------------------------------------------------------------
class Interferencia:
    """Rafagas de ocupacion del canal (supuesto S6)."""

    def __init__(self, ocupacion, rafaga_media_s, duracion_s, rng):
        self.inicios, self.fines = [], []
        if ocupacion <= 0:
            return
        if ocupacion >= 1:
            self.inicios, self.fines = [0.0], [duracion_s + 1]
            return
        hueco_medio = rafaga_media_s * (1 - ocupacion) / ocupacion
        t = rng.expovariate(1 / hueco_medio)
        while t < duracion_s + 1:
            d = rng.expovariate(1 / rafaga_media_s)
            self.inicios.append(t)
            self.fines.append(t + d)
            t += d + rng.expovariate(1 / hueco_medio)

    def traslapa(self, a, b):
        """True si alguna rafaga toca el intervalo [a, b]."""
        k = bisect.bisect_left(self.fines, a)
        return k < len(self.inicios) and self.inicios[k] < b

    def fraccion(self, a, b):
        ocupado = 0.0
        k = bisect.bisect_left(self.fines, a)
        while k < len(self.inicios) and self.inicios[k] < b:
            ocupado += min(b, self.fines[k]) - max(a, self.inicios[k])
            k += 1
        return ocupado / (b - a) if b > a else 0.0


# --------------------------------------------------------------------------
#  Simulador por eventos
# --------------------------------------------------------------------------
class _Nodo:
    def __init__(self, ident, politica, rng, deriva_ppm, sigma_proceso_s,
                 periodo_fijo_s):
        self.id = ident
        self.p = politica
        self.rng = rng
        self.deriva = 1.0 + rng.uniform(-deriva_ppm, deriva_ppm) * 1e-6
        self.sigma = sigma_proceso_s
        self.periodo_fijo = periodo_fijo_s
        self.estado = NORMAL
        self.estado_previo = NORMAL
        self.secuencia = 0
        self.ard = ARD_DRIVER
        # Trama en curso
        self.trama = None


class Resultado:
    """Lo que la simulacion mide. Todo en segundos."""

    def __init__(self):
        self.tramas = []          # dict por trama generada
        self.intentos = 0
        self.intentos_fallidos = 0
        self.transiciones = []    # dict por cambio de estado
        self.duracion = 0.0

    def entrega(self, desde_s=0.0, nodo=None):
        """(entregadas, generadas) contando solo tramas generadas >= desde_s."""
        sel = [t for t in self.tramas
               if t["t_gen"] >= desde_s and (nodo is None or t["nodo"] == nodo)
               and t["cerrada"]]
        return sum(1 for t in sel if t["t_entrega"] is not None), len(sel)

    def intentos_por_trama(self):
        sel = [t["intentos"] for t in self.tramas if t["cerrada"]]
        return sum(sel) / len(sel) if sel else 0.0

    def primer_intento(self):
        """(tramas con exito al primer intento, tramas cerradas)."""
        sel = [t for t in self.tramas if t["cerrada"]]
        return sum(1 for t in sel if t["intentos"] == 1 and t["ack"]), len(sel)

    def racha_maxima(self):
        """Mayor numero de tramas SEGUIDAS perdidas por un mismo nodo.

        Es la cifra que importa para una alarma: una perdida aislada se
        corrige con la trama siguiente; una racha de k perdidas retrasa el
        aviso k periodos.
        """
        mayor, actual = 0, {}
        for t in self.tramas:
            if not t["cerrada"]:
                continue
            k = t["nodo"]
            actual[k] = actual.get(k, 0) + 1 if t["t_entrega"] is None else 0
            mayor = max(mayor, actual[k])
        return mayor

    def retardos_transicion(self):
        """Retardos de las transiciones; inf si nunca se entrego."""
        return [r["retardo"] for r in self.transiciones]


def simular(nodos, politica, duracion_s, semilla=1, ocupacion_wifi=0.0,
            rafaga_media_s=0.002, dispersion_arranque_s=PERIODO_S,
            cambios=(), periodo_fijo_s=None, sigma_proceso_s=0.0002,
            deriva_ppm=10.0):
    """Simula `nodos` detectores y un concentrador durante duracion_s.

    politica              dict (POLITICA_V1, POLITICA_V3 o una variante)
    ocupacion_wifi        fraccion del tiempo con el canal ocupado (S6)
    rafaga_media_s        duracion media de cada rafaga de interferencia
    dispersion_arranque_s los nodos se encienden en U(0, dispersion). Un
                          valor del orden de milisegundos representa un
                          corte de energia: todos arrancan casi a la vez.
    cambios               lista de (t, id_nodo, estado): el nodo adopta el
                          estado en su siguiente ciclo (es su decision local)
    periodo_fijo_s        si no es None, periodo constante (modo de prueba)
    sigma_proceso_s       fluctuacion del tiempo de proceso por ciclo (S5)
    deriva_ppm            deriva maxima del reloj de cada nodo (S5)
    """
    rng = random.Random(semilla)
    interf = Interferencia(ocupacion_wifi, rafaga_media_s, duracion_s,
                           random.Random(rng.random()))
    ns = [_Nodo(i + 1, politica, random.Random(rng.random()), deriva_ppm,
                sigma_proceso_s, periodo_fijo_s) for i in range(nodos)]
    res = Resultado()
    res.duracion = duracion_s

    cola = []
    cont = [0]

    def agendar(t, tipo, nodo, dato=None):
        cont[0] += 1
        heapq.heappush(cola, (t, cont[0], tipo, nodo, dato))

    # Aire: intervalos (inicio, fin) registrados; se poda periodicamente
    aire = []
    entregadas = {}           # (nodo, secuencia) -> t de la primera entrega
    cambios_por_nodo = {}
    for (t, ident, est) in sorted(cambios):
        cambios_por_nodo.setdefault(ident, []).append((t, est))
    pendientes = {}           # nodo -> transicion abierta (dict)

    for n in ns:
        t0 = rng.uniform(0, dispersion_arranque_s)
        if politica["espera_arranque"]:
            t0 += n.rng.uniform(0, PERIODO_S) * n.deriva
        agendar(t0, "ciclo", n)

    def otros_traslapan(a, b, propio):
        for (s, e, ref) in aire:
            if ref is not propio and s < b and e > a:
                return True
        return False

    ultimo_podado = 0.0
    while cola:
        t, _, tipo, n, dato = heapq.heappop(cola)
        if t > duracion_s:
            break

        if t - ultimo_podado > 0.05:
            aire = [x for x in aire if x[1] > t - 0.02]
            ultimo_podado = t

        if tipo == "ciclo":
            # Estado vigente: el ultimo cambio con t <= ahora
            for (tc, est) in cambios_por_nodo.get(n.id, []):
                if tc <= t:
                    n.estado = est
            transicion = n.estado != n.estado_previo
            prioridad = transicion or n.estado >= PREALARMA
            t_proc = max(0.0, T_PROCESO + n.rng.gauss(0, n.sigma)) * n.deriva
            trama = {"nodo": n.id, "secuencia": n.secuencia,
                     "estado": n.estado, "t_gen": t + t_proc,
                     "t_entrega": None, "intentos": 0, "sw": 0,
                     "ack": False, "cerrada": False, "prioridad": prioridad}
            res.tramas.append(trama)
            if transicion:
                pendientes[n.id] = {"nodo": n.id, "estado": n.estado,
                                    "t_gen": trama["t_gen"], "retardo": None}
                res.transiciones.append(pendientes[n.id])
            n.estado_previo = n.estado
            n.secuencia += 1
            n.trama = trama
            n.sw_max = (n.p["sw_prioridad"] if prioridad
                        else n.p["sw_rutina"])
            n.t_ciclo = t
            agendar(t + t_proc + T_ENCENDIDO, "envio", n, 0)

        elif tipo == "envio":
            # Una llamada a send(): hasta arc+1 intentos con el mismo ARD
            if n.p["ard_aleatorio"]:
                k = n.rng.randint(*n.p["ard_idx"])
            else:
                k = n.p["ard_idx"][0]
            n.ard = (k + 1) * 250e-6
            n.intento = 0
            agendar(t, "intento", n)

        elif tipo == "intento":
            ref = (n.id, n.trama["secuencia"], n.trama["sw"], n.intento)
            aire.append((t, t + T_AIRE, ref))
            res.intentos += 1
            n.trama["intentos"] += 1
            agendar(t + T_AIRE, "fin_trama", n, (t, ref))

        elif tipo == "fin_trama":
            s, ref = dato
            ok = not otros_traslapan(s, t, ref) and not interf.traslapa(s, t)
            if ok:
                clave = (n.id, n.trama["secuencia"])
                if clave not in entregadas:
                    entregadas[clave] = t
                    n.trama["t_entrega"] = t
                    tr = pendientes.get(n.id)
                    if (tr is not None and tr["retardo"] is None
                            and n.trama["estado"] == tr["estado"]
                            and n.trama["t_gen"] >= tr["t_gen"]):
                        tr["retardo"] = t - tr["t_gen"]
                a = t + T_CONMUTACION
                b = a + T_ACUSE
                ref_a = ref + ("acuse",)
                aire.append((a, b, ref_a))
                agendar(b, "fin_acuse", n, (s, a, ref_a))
            else:
                res.intentos_fallidos += 1
                agendar(t, "fallo", n, s)

        elif tipo == "fin_acuse":
            s, a, ref_a = dato
            ok = not otros_traslapan(a, t, ref_a) and not interf.traslapa(a, t)
            if ok:
                n.trama["ack"] = True
                agendar(t, "cerrar", n)
            else:
                res.intentos_fallidos += 1
                agendar(t, "fallo", n, s)

        elif tipo == "fallo":
            s = dato
            fin_trama = s + T_AIRE
            if n.intento < n.p["arc"]:
                n.intento += 1
                agendar(fin_trama + n.ard, "intento", n)
            elif n.trama["sw"] < n.sw_max:
                # MAX_RT: el driver lanza OSError. El firmware espera un
                # tiempo aleatorio creciente y vuelve a llamar a send().
                ventana = n.p["espera_sw_base_s"] * (2 ** n.trama["sw"])
                n.trama["sw"] += 1
                espera = n.rng.uniform(0, ventana) * n.deriva
                agendar(t + espera + T_ENCENDIDO, "envio", n)
            else:
                agendar(t, "cerrar", n)

        elif tipo == "cerrar":
            n.trama["cerrada"] = True
            periodo = (n.periodo_fijo if n.periodo_fijo is not None
                       else PERIODO_POR_ESTADO[n.estado])
            f = n.p["fluctuacion"]
            if f:
                periodo *= n.rng.uniform(1 - f, 1 + f)
            agendar(t + periodo * n.deriva, "ciclo", n)

    for tr in res.transiciones:
        if tr["retardo"] is None:
            tr["retardo"] = float("inf")
    return res


# --------------------------------------------------------------------------
#  Autoprueba corta
# --------------------------------------------------------------------------
if __name__ == "__main__":
    print("Parametros del enlace (calculados con la hoja de datos):")
    print("  trama {} bits -> {:.0f} us en el aire".format(
        BITS_TRAMA, T_AIRE * 1e6))
    print("  acuse {} bits -> {:.0f} us".format(BITS_ACUSE, T_ACUSE * 1e6))
    print("  ventana vulnerable {:.2f} ms".format(VENTANA_VULNERABLE * 1e3))
    print("  tramas sin perdida para demostrar 99 %: {}".format(
        tramas_para_demostrar(0.99)))
    fallos = 0
    # 1. Un nodo solo, sin interferencia: no puede perder nada
    r = simular(1, POLITICA_V1, 120, semilla=1)
    e, g = r.entrega()
    ok = e == g and g > 20
    fallos += not ok
    print("  1 nodo, sin interferencia : {}/{} entregadas  {}".format(
        e, g, "OK" if ok else "FALLA"))
    # 2. Canal ocupado al 100 %: no entrega nada
    r = simular(1, POLITICA_V1, 60, semilla=1, ocupacion_wifi=1.0)
    e, g = r.entrega()
    ok = e == 0 and g > 5
    fallos += not ok
    print("  canal ocupado al 100 %    : {}/{} entregadas  {}".format(
        e, g, "OK" if ok else "FALLA"))
    # 3. Wilson con 300 de 300 debe dar cota inferior cercana a 0.987
    b, a = wilson(300, 300)
    ok = 0.98 < b < 0.995 and a > 0.9999
    fallos += not ok
    print("  Wilson 300/300            : [{:.4f}, {:.4f}]  {}".format(
        b, a, "OK" if ok else "FALLA"))
    print("RESULTADO: " + ("autoprueba correcta" if not fallos
                          else "{} fallas".format(fallos)))
