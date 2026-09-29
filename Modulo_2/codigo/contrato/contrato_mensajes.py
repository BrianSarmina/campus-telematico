"""Contrato de mensajes de la plataforma - Modulo 2.

Este archivo, junto con trama_rf.py, ES el Documento de Control de Interfaces
en su forma ejecutable. La version en papel describe; esta version VERIFICA.

POR QUE UN CONTRATO EJECUTABLE

Un ICD escrito solo en prosa se desactualiza en cuanto alguien cambia el codigo
y olvida editar el documento. Un contrato en forma de esquema se puede ejecutar
contra los mensajes reales: si el codigo se desvia, la prueba falla.

La prosa sigue siendo necesaria, porque explica POR QUE cada campo existe. Pero
la prosa no detecta una desviacion y el esquema si.

LOS CUATRO CONTRATOS DEL SISTEMA

  1. trama_rf.py        binario, 18 bytes, nodo detector -> concentrador
  2. TELEMETRIA         JSON sobre MQTT, puente -> plataforma
  3. ALERTA             JSON sobre MQTT, puente -> plataforma y consola
  4. COMANDO            JSON sobre MQTT, consola -> robot

El primero ya existe desde el Modulo 1. Los tres siguientes se definen aqui.

VERSIONADO

Cada mensaje lleva su version como cadena "MAYOR.MENOR":

  MENOR sube al AGREGAR un campo opcional. Un receptor viejo lo ignora y sigue
        funcionando. Compatible hacia atras.
  MAYOR sube al QUITAR o RENOMBRAR un campo, o al cambiar su significado.
        Rompe a los receptores existentes y exige coordinar el cambio.

Esta distincion es la que hace util al versionado. Subir siempre la version
mayor por miedo obliga a coordinar cambios que no lo necesitaban.

Ejecutar este archivo valida los ejemplos contra los esquemas:
    python contrato_mensajes.py
"""

VERSION_CONTRATO = "1.0"

# =====================================================================
#  TOPICOS
# =====================================================================
# El topico forma parte del contrato, no es un detalle de implementacion.
# En el Modulo 1 un suscriptor dejo de funcionar porque distinguia los
# mensajes por el contenido de un campo en lugar del topico. Ese fallo es
# la razon de que esta seccion exista.

TOPICOS = {
    "telemetria": "campus/telemetria/{nodo}/ambiente",
    "alerta": "campus/alertas/{severidad}/{nodo}",
    "estado": "campus/estado/{componente}",
    "comando": "campus/comandos/robot",
    "respuesta": "campus/respuestas/robot",
}

# Calidad de servicio por clase de trafico. Se fija aqui porque es una
# decision de contrato, no de cada programa.
QOS = {
    "telemetria": 1,   # entrega al menos una vez: no se tolera perder
    "alerta": 1,       # idem, y ademas es lo mas critico del sistema
    "estado": 1,       # retenido, para que un cliente nuevo sepa el estado
    "comando": 0,      # un comando perdido se sustituye por el siguiente;
                       # reenviarlo tarde seria peor que perderlo
    "respuesta": 0,
}

RETENIDO = {"estado": True}


# =====================================================================
#  ESQUEMAS
# =====================================================================

ESQUEMA_TELEMETRIA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Telemetria de vigilancia",
    "type": "object",
    "required": ["version", "nodo", "ts", "estado", "medidas"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "pattern": r"^\d+\.\d+$"},
        "nodo": {"type": "string", "pattern": "^d[0-9a-f]{2}$"},
        "ts": {"type": "string", "format": "date-time"},
        "calidad": {"enum": ["valida", "estimada", "sospechosa"]},
        "estado": {"enum": ["normal", "vigilancia", "prealarma", "alarma"]},
        "medidas": {
            "type": "object",
            "required": ["temperatura_c", "dtemp_c_min", "humo_adc",
                         "flama_adc"],
            "additionalProperties": False,
            "properties": {
                "temperatura_c": {"type": "number",
                                  "minimum": -40, "maximum": 85},
                "humedad_pct": {"type": "number",
                                "minimum": 0, "maximum": 100},
                "presion_hpa": {"type": "number",
                                "minimum": 300, "maximum": 1100},
                "dtemp_c_min": {"type": "number",
                                "minimum": -300, "maximum": 300},
                "humo_adc": {"type": "integer", "minimum": 0, "maximum": 4095},
                "flama_adc": {"type": "integer", "minimum": 0, "maximum": 4095},
            },
        },
        "diag": {"type": "object"},
    },
}

ESQUEMA_ALERTA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Alerta de deteccion",
    "type": "object",
    "required": ["version", "nodo", "ts", "estado", "severidad", "transicion"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "pattern": r"^\d+\.\d+$"},
        "nodo": {"type": "string", "pattern": "^d[0-9a-f]{2}$"},
        "ts": {"type": "string", "format": "date-time"},
        "estado": {"enum": ["vigilancia", "prealarma", "alarma"]},
        "severidad": {"enum": ["baja", "alta", "critica"]},
        "transicion": {"type": "string"},
        "medidas": {"type": "object"},
    },
}

# El contrato del canal de control. Se escribe en la semana 6; el robot que
# lo implementa no existe hasta la semana 7. Esa separacion en el tiempo es
# la razon de ser del ICD cuando no hay equipos separados.
ESQUEMA_COMANDO = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Comando al robot",
    "type": "object",
    "required": ["version", "id", "ts", "accion"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "pattern": r"^\d+\.\d+$"},
        # El identificador permite correlacionar comando y respuesta, y
        # descartar duplicados. Sin el no se puede medir la latencia del
        # lazo de teleoperacion, que es el requisito RNF-02.
        "id": {"type": "string", "minLength": 4, "maxLength": 36},
        "ts": {"type": "string", "format": "date-time"},
        "accion": {"enum": ["apuntar", "ventilador", "centrar", "parar"]},
        "parametros": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                # Angulos absolutos, no relativos. Un comando relativo que se
                # pierde deja al actuador desfasado para siempre; uno absoluto
                # se corrige solo con el siguiente.
                "pan_grados": {"type": "number",
                               "minimum": -90, "maximum": 90},
                "tilt_grados": {"type": "number",
                                "minimum": -45, "maximum": 45},
                "encendido": {"type": "boolean"},
            },
        },
    },
}

ESQUEMA_RESPUESTA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Respuesta del robot",
    "type": "object",
    "required": ["version", "id", "ts", "resultado"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "pattern": r"^\d+\.\d+$"},
        "id": {"type": "string"},
        "ts": {"type": "string", "format": "date-time"},
        "resultado": {"enum": ["ok", "rechazado", "fuera_de_rango", "error"]},
        "detalle": {"type": "string"},
        "posicion": {
            "type": "object",
            "properties": {
                "pan_grados": {"type": "number"},
                "tilt_grados": {"type": "number"},
                "ventilador": {"type": "boolean"},
            },
        },
    },
}

ESQUEMAS = {
    "telemetria": ESQUEMA_TELEMETRIA,
    "alerta": ESQUEMA_ALERTA,
    "comando": ESQUEMA_COMANDO,
    "respuesta": ESQUEMA_RESPUESTA,
}


# =====================================================================
#  COMPORTAMIENTO ANTE PERDIDA DE ENLACE
# =====================================================================
# Esto tambien es contrato: define que hace el robot cuando deja de recibir
# comandos. Sin acordarlo, cada implementacion elige distinto y el sistema
# se vuelve impredecible justo en la situacion de falla.

PLAZO_SEGURO_S = 2.0
"""Si el robot no recibe ningun comando durante este tiempo, se detiene:
apaga el ventilador y conserva la posicion. NO vuelve a centrarse, porque un
movimiento inesperado ante una perdida de enlace es peor que quedarse quieto.

Dos segundos es un compromiso: suficiente para tolerar un hueco de Wi-Fi,
corto para que el operador note que perdio el control."""


def validar(tipo, mensaje):
    """Valida un mensaje contra su esquema. Devuelve lista de errores."""
    try:
        import jsonschema
    except ImportError:
        return ["falta jsonschema: pip install jsonschema"]

    esquema = ESQUEMAS.get(tipo)
    if esquema is None:
        return ["tipo de mensaje desconocido: {}".format(tipo)]

    validador = jsonschema.Draft202012Validator(esquema)
    return [
        "{}: {}".format("/".join(str(p) for p in e.absolute_path) or "(raiz)",
                        e.message)
        for e in validador.iter_errors(mensaje)
    ]


# =====================================================================
if __name__ == "__main__":
    from datetime import datetime, timezone

    ahora = datetime.now(timezone.utc).isoformat()

    casos = [
        ("telemetria", {
            "version": "1.0", "nodo": "d01", "ts": ahora,
            "calidad": "estimada", "estado": "normal",
            "medidas": {"temperatura_c": 23.4, "humedad_pct": 48.2,
                        "presion_hpa": 780.1, "dtemp_c_min": 0.12,
                        "humo_adc": 318, "flama_adc": 94},
            "diag": {"tasa_entrega": 0.998},
        }, True, "Telemetria completa"),

        ("telemetria", {
            "version": "1.0", "nodo": "d01", "ts": ahora, "estado": "normal",
            "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                        "humo_adc": 318, "flama_adc": 94},
        }, True, "Telemetria minima (opcionales ausentes)"),

        ("telemetria", {
            "version": "1.0", "nodo": "d01", "ts": ahora, "estado": "normal",
            "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                        "humo_adc": 9999, "flama_adc": 94},
        }, False, "Humo fuera del rango del ADC"),

        ("telemetria", {
            "version": "1.0", "nodo": "detector-1", "ts": ahora,
            "estado": "normal",
            "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                        "humo_adc": 318, "flama_adc": 94},
        }, False, "Identificador de nodo con formato invalido"),

        ("alerta", {
            "version": "1.0", "nodo": "d01", "ts": ahora,
            "estado": "prealarma", "severidad": "alta",
            "transicion": "vigilancia -> prealarma",
        }, True, "Alerta de prealarma"),

        ("alerta", {
            "version": "1.0", "nodo": "d01", "ts": ahora,
            "estado": "normal", "severidad": "baja",
            "transicion": "x -> normal",
        }, False, "Alerta con estado normal (no existe tal alerta)"),

        ("comando", {
            "version": "1.0", "id": "cmd-0042", "ts": ahora,
            "accion": "apuntar",
            "parametros": {"pan_grados": 30.0, "tilt_grados": -10.0},
        }, True, "Comando de apuntado"),

        ("comando", {
            "version": "1.0", "id": "cmd-0043", "ts": ahora,
            "accion": "apuntar", "parametros": {"pan_grados": 150.0},
        }, False, "Pan fuera del rango mecanico"),

        ("comando", {
            "version": "1.0", "id": "cmd-0044", "ts": ahora,
            "accion": "disparar_agua",
        }, False, "Accion no contemplada en el contrato"),

        ("respuesta", {
            "version": "1.0", "id": "cmd-0042", "ts": ahora,
            "resultado": "ok",
            "posicion": {"pan_grados": 30.0, "tilt_grados": -10.0,
                         "ventilador": False},
        }, True, "Respuesta correlacionada con su comando"),
    ]

    print("=" * 76)
    print("  VALIDACION DEL CONTRATO DE MENSAJES  (ICD v{})".format(
        VERSION_CONTRATO))
    print("=" * 76)
    print("{:<44}{:>10}{:>10}{:>10}".format(
        "Caso", "Esperado", "Obtenido", ""))
    print("-" * 76)

    fallos = 0
    for tipo, msg, valido_esperado, desc in casos:
        errores = validar(tipo, msg)
        if errores and errores[0].startswith("falta jsonschema"):
            print("\n  " + errores[0])
            raise SystemExit(1)
        obtenido = not errores
        ok = obtenido == valido_esperado
        if not ok:
            fallos += 1
        print("{:<44}{:>10}{:>10}{:>10}".format(
            desc[:43],
            "valido" if valido_esperado else "invalido",
            "valido" if obtenido else "invalido",
            "OK" if ok else "FALLA"))
        if errores and not valido_esperado:
            print("      -> {}".format(errores[0][:64]))

    print("-" * 76)
    print("\nTOPICOS Y CALIDAD DE SERVICIO")
    print("{:<14}{:<40}{:>6}{:>10}".format(
        "Clase", "Topico", "QoS", "Retenido"))
    print("-" * 76)
    for clase, patron in TOPICOS.items():
        print("{:<14}{:<40}{:>6}{:>10}".format(
            clase, patron, QOS[clase],
            "si" if RETENIDO.get(clase) else "no"))

    print("\nCOMPORTAMIENTO SEGURO")
    print("  Sin comandos durante {:.1f} s: el robot apaga el ventilador y".format(
        PLAZO_SEGURO_S))
    print("  conserva su posicion. No se recentra.")

    print("\nRESULTADO: " + ("el contrato acepta y rechaza lo que debe"
                            if fallos == 0 else "{} casos a revisar".format(fallos)))
