"""Formato de trama del enlace de radiofrecuencia - Modulo 1, Practica 4.

Este archivo ES el contrato del enlace RF. Deben respetarlo por igual:
    - el nodo detector          (MicroPython, practica04/nodo_detector)
    - el concentrador           (MicroPython, practica04/concentrador)
    - el puente serie           (CPython,     practica04/puente)

Si se modifica aqui, hay que propagarlo a los tres. Ese es justamente el
problema que el Documento de Control de Interfaces resuelve en el Modulo 2.

RESTRICCION DE ORIGEN
El nRF24L01 admite 32 bytes de carga util por paquete. No cabe JSON. Se
empaqueta en binario con punto fijo y el concentrador reconstruye los valores.

DISPOSICION DE LA TRAMA (18 bytes de los 32 disponibles)

  Desp. Campo        Tipo    Escala   Unidad     Observacion
  ----- ------------ ------- -------- ---------- ---------------------------
    0   version      uint8   -        -          Version del formato
    1   nodo         uint8   -        -          1..254, inmutable
    2   secuencia    uint16  -        -          Detecta perdidas y desorden
    4   temperatura  int16   x100     grados C   Canal termico
    6   humedad      uint16  x100     % HR       Contexto
    8   presion      uint16  x10      hPa        Contexto y validacion
   10   humo         uint16  -        cuentas    ADC crudo del MQ-2, 0..4095
   12   flama        uint16  -        cuentas    ADC crudo del sensor IR
   14   dtemp        int16   x100     grados/min VELOCIDAD DE SUBIDA
   16   estado       uint8   -        -          Veredicto del nodo
   17   flags        uint8   -        -          Mapa de bits

POR QUE SE ENVIA dtemp Y NO SOLO LA TEMPERATURA
La velocidad de subida es el indicador primario de incendio, no el valor
absoluto: un aula a 32 grados en mayo es normal, una que sube 8 grados por
minuto no lo es. Calcularla exige una serie historica, y el nodo la tiene
mientras que la plataforma tendria que reconstruirla. Es computo en el borde
con una justificacion concreta: se envia una conclusion, no datos crudos.

POR QUE SE ENVIAN humo Y flama COMO ADC CRUDO
Convertir cuentas del ADC a ppm exige una curva de calibracion que el nodo no
puede almacenar y que ademas cambia con la humedad y el envejecimiento del
sensor. Se envia el dato crudo y la plataforma aplica la conversion, que puede
actualizarse sin reprogramar el nodo. Es la decision contraria a la de dtemp, y
por eso vale la pena discutir ambas juntas.

ESTADOS DEL NODO
   0  NORMAL      Ningun indicador activo
   1  VIGILANCIA  Un indicador activo. No genera alarma
   2  PREALARMA   Dos indicadores activos. Notifica sin despachar el robot
   3  ALARMA      Tres indicadores, o dos sostenidos. Despacha

MAPA DE BITS DE flags
   bit 0  sensor termico fuera de rango o no responde
   bit 1  el nodo se reinicio recientemente
   bit 2  el MQ-2 aun no termina su precalentamiento
   bit 3  bateria baja
   bit 4  reservado

Ejecutar este archivo corre la prueba de ida y vuelta:
    python formato_trama.py
"""
import struct

VERSION_TRAMA = 2
FORMATO = "<BBHhHHHHhBB"          # little endian, sin relleno
TAMANO = struct.calcsize(FORMATO)  # 18 bytes

# Factores de escala del punto fijo
ESC_TEMPERATURA = 100.0
ESC_HUMEDAD = 100.0
ESC_PRESION = 10.0
ESC_DTEMP = 100.0

# Estados
NORMAL, VIGILANCIA, PREALARMA, ALARMA = 0, 1, 2, 3
NOMBRE_ESTADO = {0: "normal", 1: "vigilancia", 2: "prealarma", 3: "alarma"}

# Banderas
FLAG_TERMICO_FALLA = 0x01
FLAG_REINICIO = 0x02
FLAG_PRECALENTANDO = 0x04
FLAG_BATERIA_BAJA = 0x08


def empaquetar(nodo, secuencia, temperatura_c, humedad_pct, presion_hpa,
               humo_adc, flama_adc, dtemp_c_min, estado, flags=0):
    """Construye la trama binaria. Espejo exacto del codigo del nodo."""
    return struct.pack(
        FORMATO,
        VERSION_TRAMA,
        nodo & 0xFF,
        secuencia & 0xFFFF,
        int(round(temperatura_c * ESC_TEMPERATURA)),
        int(round(humedad_pct * ESC_HUMEDAD)),
        int(round(presion_hpa * ESC_PRESION)),
        int(humo_adc) & 0xFFFF,
        int(flama_adc) & 0xFFFF,
        int(round(dtemp_c_min * ESC_DTEMP)),
        estado & 0xFF,
        flags & 0xFF,
    )


def desempaquetar(trama):
    """Reconstruye los valores. Lo ejecuta el concentrador."""
    if len(trama) < TAMANO:
        raise ValueError(
            "Trama de {} bytes, se esperaban {}".format(len(trama), TAMANO))

    (version, nodo, secuencia, temp, hum, pres,
     humo, flama, dtemp, estado, flags) = struct.unpack(FORMATO, trama[:TAMANO])

    if version != VERSION_TRAMA:
        raise ValueError(
            "Version de trama {} desconocida (se esperaba {})".format(
                version, VERSION_TRAMA))

    return {
        "version": version,
        "nodo": "d{:02x}".format(nodo),     # d01, d02, ... detector
        "secuencia": secuencia,
        "estado": NOMBRE_ESTADO.get(estado, "desconocido"),
        "estado_num": estado,
        "medidas": {
            "temperatura_c": temp / ESC_TEMPERATURA,
            "humedad_pct": hum / ESC_HUMEDAD,
            "presion_hpa": pres / ESC_PRESION,
            "dtemp_c_min": dtemp / ESC_DTEMP,
            "humo_adc": humo,
            "flama_adc": flama,
        },
        "diag": {
            "termico_falla": bool(flags & FLAG_TERMICO_FALLA),
            "reinicio": bool(flags & FLAG_REINICIO),
            "precalentando": bool(flags & FLAG_PRECALENTANDO),
            "bateria_baja": bool(flags & FLAG_BATERIA_BAJA),
        },
    }


# =====================================================================
if __name__ == "__main__":
    print("Formato : {}".format(FORMATO))
    print("Tamano  : {} bytes de los 32 disponibles".format(TAMANO))
    print("Margen  : {} bytes libres para crecimiento\n".format(32 - TAMANO))

    casos = [
        # nodo sec temp   hum   pres    humo flama dtemp estado flags desc
        (1, 0, 23.45, 51.20, 780.15, 320, 90, 0.10, NORMAL, 0,
         "Reposo, condiciones normales"),
        (1, 1, 31.20, 44.00, 780.10, 850, 120, 6.80, VIGILANCIA, 0,
         "Rampa termica de la secadora"),
        (1, 2, 38.90, 38.50, 780.05, 2100, 140, 9.40, PREALARMA, 0,
         "Termico y humo coinciden"),
        (1, 3, 45.00, 30.00, 780.00, 3200, 3900, 12.50, ALARMA, 0,
         "Tres indicadores activos"),
        (2, 65535, -5.00, 0.00, 700.00, 0, 0, -327.00, NORMAL,
         FLAG_PRECALENTANDO | FLAG_REINICIO, "Limites y banderas"),
    ]

    print("{:<32}{:>8}{:>9}{:>8}{:>12}{:>8}".format(
        "Caso", "Temp", "dTemp", "Humo", "Estado", "Error"))
    print("-" * 78)

    fallos = 0
    EPS = 1e-9
    for nodo, sec, t, h, p, humo, flama, dt, est, fl, desc in casos:
        trama = empaquetar(nodo, sec, t, h, p, humo, flama, dt, est, fl)
        assert len(trama) == TAMANO, "Tamano incorrecto"

        r = desempaquetar(trama)
        m = r["medidas"]

        # El unico error posible es la cuantizacion del punto fijo, acotada
        # a medio bit menos significativo en cada campo.
        dentro = (
            abs(m["temperatura_c"] - t) <= 0.5 / ESC_TEMPERATURA + EPS
            and abs(m["humedad_pct"] - h) <= 0.5 / ESC_HUMEDAD + EPS
            and abs(m["presion_hpa"] - p) <= 0.5 / ESC_PRESION + EPS
            and abs(m["dtemp_c_min"] - dt) <= 0.5 / ESC_DTEMP + EPS
            and m["humo_adc"] == humo and m["flama_adc"] == flama
            and r["estado_num"] == est and r["secuencia"] == sec
        )
        err = max(abs(m["temperatura_c"] - t), abs(m["dtemp_c_min"] - dt))
        if not dentro:
            fallos += 1

        print("{:<32}{:>8.2f}{:>9.2f}{:>8d}{:>12}{:>8.3f}  {}".format(
            desc, m["temperatura_c"], m["dtemp_c_min"], m["humo_adc"],
            r["estado"], err, "OK" if dentro else "FALLA"))

    print("-" * 78)
    print("\nResolucion del punto fijo:")
    print("  Temperatura      : {:.2f} grados C".format(1 / ESC_TEMPERATURA))
    print("  Velocidad subida : {:.2f} grados/min".format(1 / ESC_DTEMP))
    print("  Presion          : {:.2f} hPa".format(1 / ESC_PRESION))

    ejemplo = empaquetar(1, 258, 38.90, 38.50, 780.05, 2100, 140, 9.40,
                         PREALARMA, 0)
    print("\nEjemplo de trama de PREALARMA en hexadecimal:")
    print("  " + " ".join("{:02X}".format(b) for b in ejemplo))

    import json
    equivalente = json.dumps(desempaquetar(ejemplo))
    print("\nComparacion de tamano para la MISMA informacion:")
    print("  Trama binaria por RF : {:>4d} bytes".format(len(ejemplo)))
    print("  JSON equivalente     : {:>4d} bytes".format(len(equivalente)))
    print("  Factor de expansion  : {:>4.1f} veces".format(
        len(equivalente) / len(ejemplo)))
    print("\n  Esa expansion ocurre en el concentrador. Es el precio de pasar")
    print("  de un dominio restringido a uno de proposito general, y es la")
    print("  razon de que el gateway exista.")

    print("\nRESULTADO: " + ("todos los casos correctos"
                            if fallos == 0 else "{} fallos".format(fallos)))
