"""Algoritmo de deteccion multicriterio - Modulo 1, Practica 4.

Se ejecuta EN EL NODO, no en la plataforma. Dos razones:

  1. Latencia. El requisito RNF-01 exige menos de 5 s entre la deteccion y el
     aviso. Decidir en el borde elimina el tiempo de ida y vuelta.
  2. Trafico. Un nodo que solo transmite conclusiones ocupa menos aire que uno
     que transmite datos crudos para que otro decida. En un medio compartido
     sin deteccion de portadora, ese ahorro es lo que deja espacio a la alarma.

POR QUE MULTICRITERIO Y NO UN UMBRAL

El requisito RNF-05 exige menos de una falsa alarma cada 24 horas. Un umbral
simple de temperatura no lo cumple: se dispara con el sol de la tarde, con una
calefaccion o con alguien que pasa con un cafe. El sistema exige coincidencia
de indicadores independientes, que es como funcionan los detectores
comerciales.

LOS TRES INDICADORES

  Termico   Velocidad de subida de la temperatura, en grados por minuto.
            NO el valor absoluto: un aula a 32 grados en mayo es normal,
            una que sube 8 grados por minuto no lo es.
  Humo      Lectura del MQ-2 por encima de su linea base aprendida.
  Radiacion Sensor infrarrojo por encima de su linea base.

LA MAQUINA DE ESTADOS

  NORMAL     ningun indicador
  VIGILANCIA un indicador               -> no notifica
  PREALARMA  dos indicadores            -> notifica, no despacha
  ALARMA     tres, o dos sostenidos     -> notifica y despacha el robot

La histeresis evita el parpadeo: para subir de estado se exige persistencia,
y para bajar se exige que el indicador caiga por debajo de un umbral MENOR
que el de subida.

Este archivo funciona igual en CPython y en MicroPython. Ejecutarlo en la PC
corre la prueba con escenarios sinteticos:
    python deteccion.py
"""

# ------------------------- Umbrales de deteccion ---------------------
# Se calibran en la Practica 4 con el protocolo de estimulo. Los valores
# iniciales son un punto de partida, NO un resultado.

UMBRAL_DTEMP_SUBIDA = 4.0      # grados/min para activar el indicador termico
UMBRAL_DTEMP_BAJADA = 2.0      # grados/min para desactivarlo (histeresis)

UMBRAL_HUMO_SUBIDA = 400       # cuentas de ADC sobre la linea base
UMBRAL_HUMO_BAJADA = 200

UMBRAL_FLAMA_SUBIDA = 600      # cuentas de ADC sobre la linea base
UMBRAL_FLAMA_BAJADA = 300

# PERSISTENCIA POR CANAL, no comun a los tres.
# Cada sensor responde a una velocidad fisica distinta, y exigirles el mismo
# tiempo sostenido produce falsos positivos en el lento y retrasa al rapido.
PERSISTENCIA_TERMICO_S = 6.0   # la temperatura responde en segundos
PERSISTENCIA_HUMO_S = 20.0     # el MQ-2 tarda ~10 s en responder y ~30 s en
                               # recuperarse; ademas filtra vapores transitorios
                               # (una taza de cafe, alguien que exhala cerca)
PERSISTENCIA_FLAMA_S = 3.0     # el sensor IR es practicamente instantaneo
SOSTENIDO_ALARMA_S = 20.0      # dos indicadores sostenidos escalan a ALARMA

NORMAL, VIGILANCIA, PREALARMA, ALARMA = 0, 1, 2, 3
NOMBRE = {0: "normal", 1: "vigilancia", 2: "prealarma", 3: "alarma"}


class VentanaTemperatura:
    """Calcula la velocidad de subida sobre una ventana deslizante.

    Se usa una ventana y no la diferencia entre dos lecturas consecutivas
    porque el ruido del sensor (mas menos 0.1 grados) sobre un periodo de
    5 s produciria una pendiente aparente de 1.2 grados por minuto que no
    existe. La ventana promedia ese ruido.
    """

    def __init__(self, ventana_s=60.0, maximo=24):
        self.ventana_s = ventana_s
        self.maximo = maximo
        self.muestras = []          # lista de (t_segundos, temperatura)

    def agregar(self, t_s, temperatura_c):
        self.muestras.append((t_s, temperatura_c))
        # Descartar lo que cae fuera de la ventana
        limite = t_s - self.ventana_s
        self.muestras = [m for m in self.muestras if m[0] >= limite]
        if len(self.muestras) > self.maximo:
            self.muestras = self.muestras[-self.maximo:]

    def pendiente_c_min(self):
        """Regresion lineal simple. Devuelve grados por minuto."""
        n = len(self.muestras)
        if n < 3:
            return 0.0
        sx = sy = sxy = sxx = 0.0
        for t, v in self.muestras:
            sx += t
            sy += v
            sxy += t * v
            sxx += t * t
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-9:
            return 0.0
        pendiente_por_s = (n * sxy - sx * sy) / denom
        return pendiente_por_s * 60.0


class Indicador:
    """Un canal de deteccion con histeresis y persistencia."""

    def __init__(self, nombre, umbral_sube, umbral_baja, persistencia_s):
        self.nombre = nombre
        self.umbral_sube = umbral_sube
        self.umbral_baja = umbral_baja
        self.persistencia_s = persistencia_s
        self.activo = False
        self.desde = None
        self.activo_desde = None

    def actualizar(self, valor, t_s):
        if not self.activo:
            if valor >= self.umbral_sube:
                if self.desde is None:
                    self.desde = t_s
                elif t_s - self.desde >= self.persistencia_s:
                    self.activo = True
                    self.activo_desde = t_s
                    self.desde = None
            else:
                self.desde = None        # no sostenido: se reinicia
        else:
            if valor < self.umbral_baja:
                self.activo = False
                self.activo_desde = None
        return self.activo

    def tiempo_activo(self, t_s):
        if not self.activo or self.activo_desde is None:
            return 0.0
        return t_s - self.activo_desde


class Detector:
    """Fusiona los tres indicadores en un estado."""

    def __init__(self):
        self.ventana = VentanaTemperatura()
        self.termico = Indicador("termico", UMBRAL_DTEMP_SUBIDA,
                                 UMBRAL_DTEMP_BAJADA, PERSISTENCIA_TERMICO_S)
        self.humo = Indicador("humo", UMBRAL_HUMO_SUBIDA,
                              UMBRAL_HUMO_BAJADA, PERSISTENCIA_HUMO_S)
        self.flama = Indicador("flama", UMBRAL_FLAMA_SUBIDA,
                               UMBRAL_FLAMA_BAJADA, PERSISTENCIA_FLAMA_S)
        # Lineas base: se aprenden en los primeros minutos de operacion.
        self.base_humo = None
        self.base_flama = None
        self.estado = NORMAL
        self.dtemp = 0.0

    def aprender_base(self, humo_adc, flama_adc, alfa=0.02):
        """Media movil muy lenta de la linea base en reposo.

        Solo se actualiza cuando el detector esta en NORMAL: de lo contrario
        un incendio sostenido acabaria por convertirse en la nueva normalidad.
        """
        if self.base_humo is None:
            self.base_humo = float(humo_adc)
            self.base_flama = float(flama_adc)
            return
        if self.estado == NORMAL:
            self.base_humo += alfa * (humo_adc - self.base_humo)
            self.base_flama += alfa * (flama_adc - self.base_flama)

    def evaluar(self, t_s, temperatura_c, humo_adc, flama_adc):
        self.ventana.agregar(t_s, temperatura_c)
        self.dtemp = self.ventana.pendiente_c_min()
        self.aprender_base(humo_adc, flama_adc)

        exceso_humo = humo_adc - (self.base_humo or humo_adc)
        exceso_flama = flama_adc - (self.base_flama or flama_adc)

        a_term = self.termico.actualizar(self.dtemp, t_s)
        a_humo = self.humo.actualizar(exceso_humo, t_s)
        a_flama = self.flama.actualizar(exceso_flama, t_s)

        activos = sum((a_term, a_humo, a_flama))

        if activos == 0:
            self.estado = NORMAL
        elif activos == 1:
            self.estado = VIGILANCIA
        elif activos == 2:
            sostenido = max(self.termico.tiempo_activo(t_s),
                            self.humo.tiempo_activo(t_s),
                            self.flama.tiempo_activo(t_s))
            self.estado = ALARMA if sostenido >= SOSTENIDO_ALARMA_S else PREALARMA
        else:
            self.estado = ALARMA

        return {
            "estado": self.estado,
            "nombre": NOMBRE[self.estado],
            "dtemp": self.dtemp,
            "indicadores": {"termico": a_term, "humo": a_humo,
                            "flama": a_flama},
            "exceso_humo": exceso_humo,
            "exceso_flama": exceso_flama,
        }


# =====================================================================
#  Prueba con escenarios sinteticos
# =====================================================================
if __name__ == "__main__":
    import random

    def correr(nombre, generador, duracion_s=180, paso_s=5.0):
        det = Detector()
        random.seed(7)
        historial = []
        t_alarma = None
        for k in range(int(duracion_s / paso_s)):
            t = k * paso_s
            temp, humo, flama = generador(t)
            r = det.evaluar(t, temp, humo, flama)
            historial.append((t, r["estado"]))
            if r["estado"] >= PREALARMA and t_alarma is None:
                t_alarma = t
        maximo = max(e for _, e in historial)
        return nombre, NOMBRE[maximo], t_alarma

    def normal(t):
        """Dia tranquilo con ruido y deriva lenta."""
        return (23.0 + 0.8 * (t / 3600.0) + random.gauss(0, 0.08),
                320 + random.gauss(0, 12),
                95 + random.gauss(0, 8))

    def sol_de_la_tarde(t):
        """Falso positivo clasico: el sol calienta la pared, sin humo."""
        return (23.0 + 6.0 * min(t / 900.0, 1.0) + random.gauss(0, 0.08),
                320 + random.gauss(0, 12),
                95 + random.gauss(0, 8))

    def secadora(t):
        """Estimulo de laboratorio: rampa termica fuerte desde t=60 s."""
        rampa = 0.0 if t < 60 else min((t - 60) * 0.20, 22.0)
        return (23.0 + rampa + random.gauss(0, 0.08),
                320 + random.gauss(0, 12),
                95 + random.gauss(0, 8))

    def incendio(t):
        """Termico, humo y radiacion coinciden desde t=60 s."""
        if t < 60:
            return (23.0 + random.gauss(0, 0.08), 320 + random.gauss(0, 12),
                    95 + random.gauss(0, 8))
        d = t - 60
        return (23.0 + min(d * 0.25, 30.0) + random.gauss(0, 0.1),
                320 + min(d * 40, 3000) + random.gauss(0, 20),
                95 + min(d * 60, 3600) + random.gauss(0, 15))

    def alguien_con_cafe(t):
        """Humo/vapor breve sin componente termico ni radiacion."""
        pico = 900 if 60 <= t < 75 else 0
        return (23.0 + random.gauss(0, 0.08),
                320 + pico + random.gauss(0, 12),
                95 + random.gauss(0, 8))

    escenarios = [
        ("Dia normal", normal, "normal"),
        ("Sol de la tarde", sol_de_la_tarde, "normal"),
        ("Alguien pasa con cafe", alguien_con_cafe, "normal"),
        ("Secadora (estimulo de lab)", secadora, "vigilancia"),
        ("Incendio simulado", incendio, "alarma"),
    ]

    print("=" * 74)
    print("  PRUEBA DEL ALGORITMO MULTICRITERIO")
    print("=" * 74)
    print("{:<30}{:>14}{:>14}{:>14}".format(
        "Escenario", "Esperado", "Obtenido", "t deteccion"))
    print("-" * 74)

    fallos = 0
    for nombre, gen, esperado in escenarios:
        n, obtenido, t_det = correr(nombre, gen)
        ok = (obtenido == esperado)
        if not ok:
            fallos += 1
        print("{:<30}{:>14}{:>14}{:>14}  {}".format(
            n, esperado, obtenido,
            "{:.0f} s".format(t_det) if t_det is not None else "-",
            "OK" if ok else "REVISAR"))

    print("-" * 74)
    print("\nLECTURA DE LOS RESULTADOS")
    print("  'Sol de la tarde' debe quedar en NORMAL: calienta 6 grados en")
    print("  15 minutos, es decir 0.4 grados/min, muy por debajo del umbral")
    print("  de 4.0. El indicador termico distingue una rampa lenta de un")
    print("  incendio precisamente por eso.")
    print("  'Alguien pasa con cafe' debe quedar en NORMAL: el pico de humo")
    print("  dura 15 s y la persistencia del canal de humo exige 20 s.")
    print("  'Secadora' debe quedarse en VIGILANCIA: hay rampa termica fuerte")
    print("  pero no hay humo ni radiacion. Si escalara a alarma, el sistema")
    print("  no cumpliria RNF-05.")
    print("  Solo 'Incendio simulado' debe alcanzar ALARMA.")
    print("\n  NOTA: la secadora sola NO dispara la alarma. Para provocarla en")
    print("  el laboratorio hay que activar tambien el canal de humo con")
    print("  alcohol isopropilico y el de radiacion con un control remoto.")
    print("\nRESULTADO: " + ("comportamiento correcto en los 5 escenarios"
                            if fallos == 0
                            else "{} escenarios a revisar".format(fallos)))
