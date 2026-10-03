"""Prueba del sensor BME280 - Practica 4, nodo detector. MicroPython/ESP32.

Separa las dos causas posibles cuando el sensor no funciona:
    HARDWARE  alimentacion, cableado, protoboard, modulo
    SOFTWARE  controlador bme280.py o su configuracion

Cada prueba usa MENOS software que la siguiente. Si una falla, el
problema esta por debajo de ella:
    1. Niveles de SDA/SCL en reposo   solo GPIO, sin I2C
    2. Escaneo del bus                I2C por hardware y por software
    3. Registro de ID del chip        I2C directo, sin el controlador
    4. Lecturas con bme280.py         el controlador completo

Ejecutar (Windows: el puerto lo detecta mpremote; si no, connect COMx):
    mpremote fs cp bme280.py :bme280.py
    mpremote run prueba_sensor.py
"""
import time
from machine import Pin, I2C

try:
    from machine import SoftI2C
except ImportError:
    SoftI2C = None

# Mismos pines que nodo_detector/main.py
PIN_SCL = 22
PIN_SDA = 21

DIRECCIONES_BME = (0x76, 0x77)
REG_ID = 0xD0
CHIPS = {
    0x60: "BME280",
    0x58: "BMP280 (NO mide humedad)",
    0x56: "BMP280 (muestra de ingenieria, NO mide humedad)",
    0x57: "BMP280 (muestra de ingenieria, NO mide humedad)",
    0x61: "BME680 (requiere otro controlador)",
}

LINEA = "=" * 64


def titulo(texto):
    print("\n" + LINEA)
    print(texto)
    print(LINEA)


def soltar_pines():
    """Devuelve SDA y SCL a entrada con pull-up. Se llama antes de cada
    intento de bus para que no quede ninguna salida activa de un intento
    anterior (por ejemplo, el de cables invertidos)."""
    Pin(PIN_SDA, Pin.IN, Pin.PULL_UP)
    Pin(PIN_SCL, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(5)


# ------------------------------------------------------------------
# 1. Niveles en reposo
# ------------------------------------------------------------------
def leer_nivel(num, pull):
    p = Pin(num, Pin.IN, pull)
    time.sleep_ms(5)
    return p.value()


def prueba_niveles():
    titulo("1. NIVELES DE SDA Y SCL EN REPOSO (solo GPIO, sin I2C)")
    print("Con el pull-down interno activo, una linea solo lee 1 si la")
    print("resistencia de pull-up DEL MODULO la sube. Eso solo ocurre si")
    print("el modulo esta alimentado Y el cable llega hasta el pin.\n")
    estado = {}
    for nombre, num in (("SDA", PIN_SDA), ("SCL", PIN_SCL)):
        abajo = leer_nivel(num, Pin.PULL_DOWN)
        arriba = leer_nivel(num, Pin.PULL_UP)
        if abajo == 1 and arriba == 1:
            e, diag = "ok", "pull-up del modulo presente"
        elif abajo == 0 and arriba == 1:
            e, diag = "flotante", "SIN pull-up externo (cable no llega o modulo sin energia)"
        elif abajo == 0 and arriba == 0:
            e, diag = "baja", "linea forzada a 0 (corto a GND o bus retenido)"
        else:
            e, diag = "incoherente", "lectura incoherente, repetir"
        estado[nombre] = e
        print("  {} (GPIO{}): con pull-down={}  con pull-up={}  -> {}".format(
            nombre, num, abajo, arriba, diag))
    soltar_pines()
    return estado


def liberar_bus():
    """Si el ESP32 se reinicio a mitad de una transaccion, el sensor puede
    quedar esperando reloj y retener SDA en 0. Nueve pulsos de SCL y una
    condicion de STOP lo liberan (procedimiento estandar de I2C)."""
    scl = Pin(PIN_SCL, Pin.OPEN_DRAIN, value=1)
    sda = Pin(PIN_SDA, Pin.OPEN_DRAIN, value=1)
    for _ in range(9):
        scl.value(0)
        time.sleep_us(10)
        scl.value(1)
        time.sleep_us(10)
    sda.value(0)
    time.sleep_us(10)
    sda.value(1)
    soltar_pines()


# ------------------------------------------------------------------
# 2. Escaneo
# ------------------------------------------------------------------
def crear_bus(tipo, scl, sda, freq):
    soltar_pines()
    if tipo == "hw":
        return I2C(0, scl=Pin(scl), sda=Pin(sda), freq=freq)
    return SoftI2C(scl=Pin(scl), sda=Pin(sda), freq=freq)


def prueba_escaneo():
    titulo("2. ESCANEO DEL BUS I2C")
    intentos = [
        ("hw",  PIN_SCL, PIN_SDA, 100000, "hardware, 100 kHz (el del firmware)"),
        ("sw",  PIN_SCL, PIN_SDA, 10000,  "software, 10 kHz (tolera cables malos)"),
        ("sw",  PIN_SDA, PIN_SCL, 10000,  "software, SDA y SCL INVERTIDOS"),
    ]
    resultados = []
    for tipo, scl, sda, freq, desc in intentos:
        if tipo == "sw" and SoftI2C is None:
            print("  {:44s} (SoftI2C no disponible)".format(desc))
            continue
        try:
            disp = crear_bus(tipo, scl, sda, freq).scan()
        except Exception as e:
            print("  {:44s} error: {}".format(desc, e))
            continue
        texto = ", ".join(hex(d) for d in disp) if disp else "ninguno"
        print("  {:44s} -> {}".format(desc, texto))
        resultados.append((tipo, scl, sda, freq, disp))
    soltar_pines()
    return resultados


# ------------------------------------------------------------------
# 3. ID del chip
# ------------------------------------------------------------------
def prueba_id(bus, direcciones):
    titulo("3. REGISTRO DE ID DEL CHIP (I2C directo, sin el controlador)")
    candidatas = [d for d in direcciones if d in DIRECCIONES_BME]
    if not candidatas:
        print("  Responden: {}. Ninguna es 0x76 ni 0x77.".format(
            ", ".join(hex(d) for d in direcciones)))
        return None, None
    d = candidatas[0]
    try:
        chip = bus.readfrom_mem(d, REG_ID, 1)[0]
    except Exception as e:
        print("  La direccion {} responde al escaneo pero no a la lectura: {}".format(hex(d), e))
        return d, None
    print("  Direccion {}: ID = 0x{:02X} -> {}".format(
        hex(d), chip, CHIPS.get(chip, "desconocido")))
    return d, chip


# ------------------------------------------------------------------
# 4. Controlador
# ------------------------------------------------------------------
def altitud_m(p_hpa):
    """Altitud de la atmosfera estandar. Sirve como verificacion rapida:
    en Cuautitlan debe salir del orden de 2200 m (+- unos cien metros,
    segun el clima). Una presion de ~1013 hPa aqui indica un error."""
    return 44330.0 * (1.0 - (p_hpa / 1013.25) ** (1 / 5.255))


def prueba_controlador(bus, direccion, n=5):
    titulo("4. LECTURAS CON EL CONTROLADOR bme280.py")
    try:
        import bme280
    except ImportError:
        print("  bme280.py no esta en el ESP32. Copiarlo con:")
        print("      mpremote fs cp bme280.py :bme280.py")
        return ["bme280.py no esta copiado al ESP32"]
    try:
        sensor = bme280.BME280(i2c=bus, direccion=direccion)
    except Exception as e:
        print("  El controlador fallo al iniciar: {}".format(e))
        return ["el controlador no inicia: {}".format(e)]

    problemas = []
    lecturas = []
    for i in range(n):
        try:
            t, p, h = sensor.leer()
        except Exception as e:
            print("  {}: error al leer: {}".format(i + 1, e))
            problemas.append("error al leer: {}".format(e))
            time.sleep(1)
            continue
        avisos = []
        if not -10 <= t <= 60:
            avisos.append("T fuera de rango")
        if not 600 <= p <= 1100:
            avisos.append("P fuera de rango")
        if not 1 <= h <= 100:
            avisos.append("HR fuera de rango")
        print("  {}: T = {:6.2f} C   P = {:7.2f} hPa   HR = {:5.1f} %   "
              "alt ~ {:5.0f} m   {}".format(i + 1, t, p, h, altitud_m(p),
                                            "; ".join(avisos) or "OK"))
        problemas.extend(avisos)
        lecturas.append((t, p, h))
        time.sleep(1)

    if len(lecturas) > 1 and all(l == lecturas[0] for l in lecturas):
        problemas.append("lecturas identicas: el sensor no esta midiendo de nuevo")
    print("\n  Verificacion manual: soplar suavemente sobre el sensor. La")
    print("  humedad debe subir varios puntos y la temperatura algo.")
    return problemas


# ------------------------------------------------------------------
# Veredicto
# ------------------------------------------------------------------
def veredicto(tipo, causas):
    titulo("VEREDICTO: " + tipo)
    for c in causas:
        # las lineas que empiezan con dos espacios continuan la anterior
        print(("  " if c.startswith("  ") else "  - ") + c)
    print()


def pistas_sin_dispositivo(estado):
    sda, scl = estado.get("SDA"), estado.get("SCL")
    if sda == "flotante" and scl == "flotante":
        return [
            "Ninguna linea tiene pull-up: el modulo no recibe energia o los",
            "  cables no llegan. Medir 3.3 V ENTRE LOS PINES VCC Y GND DEL",
            "  MODULO (no en el ESP32).",
            "El ESP32 DevKit es muy ancho para la protoboard: confirmar que",
            "  cada jumper esta en la MISMA fila que el pin del ESP32.",
            "Confirmar que los pines del modulo estan soldados (no solo",
            "  apoyados en el header).",
        ]
    if "flotante" in (sda, scl):
        malo = "SDA (GPIO21)" if sda == "flotante" else "SCL (GPIO22)"
        return ["Solo {} no tiene pull-up: ese cable o esa fila".format(malo),
                "  de la protoboard es el problema. Cambiar el jumper."]
    if "baja" in (sda, scl):
        return ["Una linea esta en 0 aun tras intentar liberar el bus:",
                "  corto a GND, o el sensor esta danado. Desconectar el",
                "  sensor y repetir: si la linea sube, el sensor la retiene."]
    return [
        "Hay pull-ups (el modulo tiene energia y los cables llegan) pero",
        "  nadie responde. Causas en este caso:",
        "Modulo de 6 pines: CSB debe ir a 3V3 (en 0 el chip entra en modo",
        "  SPI y no contesta por I2C) y SDO a GND (0x76) o a 3V3 (0x77).",
        "El modulo fue alimentado a 5 V siendo de 3.3 V y se dano.",
        "Probar con otro modulo para confirmar.",
    ]


def main():
    print("\n" + LINEA)
    print("PRUEBA DEL SENSOR BME280 - nodo detector")
    print("SCL = GPIO{}   SDA = GPIO{}".format(PIN_SCL, PIN_SDA))
    print(LINEA)

    estado = prueba_niveles()
    if estado.get("SDA") == "baja" and estado.get("SCL") == "ok":
        print("\n  SDA retenida en 0 con SCL libre: intentando liberar el bus...")
        liberar_bus()
        estado = prueba_niveles()

    resultados = prueba_escaneo()
    normal_hw = [r for r in resultados if r[0] == "hw" and r[4]]
    normal_sw = [r for r in resultados
                 if r[0] == "sw" and r[1] == PIN_SCL and r[4]]
    invertido = [r for r in resultados
                 if r[0] == "sw" and r[1] == PIN_SDA and r[4]]

    if not normal_hw and not normal_sw:
        if invertido:
            veredicto("HARDWARE", [
                "El sensor responde con SDA y SCL INVERTIDOS.",
                "Intercambiar los cables de GPIO21 y GPIO22."])
        else:
            veredicto("HARDWARE", ["Ningun dispositivo responde en el bus.",
                                   "El controlador no interviene en esta"
                                   " prueba: no es un error de software."]
                      + pistas_sin_dispositivo(estado))
        return

    if normal_sw and not normal_hw:
        veredicto("HARDWARE (calidad de senal)", [
            "El sensor responde a 10 kHz pero no a 100 kHz, que es la",
            "  velocidad del firmware. Causas: cables largos o flojos, o",
            "  falta de resistencias de pull-up en el modulo.",
            "Acortar los cables y repetir."])
        return

    tipo, scl, sda, freq, disp = normal_hw[0]
    bus = crear_bus(tipo, scl, sda, freq)
    direccion, chip = prueba_id(bus, disp)

    if direccion is None:
        veredicto("HARDWARE", ["Lo que esta conectado no es un BME280/BMP280",
                               "  (no responde en 0x76 ni 0x77)."])
        return
    if chip is None:
        veredicto("HARDWARE", ["El chip aparece en el escaneo pero falla al leer:",
                               "  contacto intermitente. Revisar cables."])
        return
    if chip != 0x60:
        veredicto("MODULO EQUIVOCADO", [
            "El chip es {}, no un BME280.".format(CHIPS.get(chip, "0x{:02X}".format(chip))),
            "El cableado esta bien; hace falta un modulo BME280 real."])
        return

    problemas = prueba_controlador(bus, direccion)
    if problemas:
        veredicto("SOFTWARE (el hardware esta verificado)", problemas + [
            "El bus y el chip respondieron correctamente en las pruebas 1-3."])
    else:
        veredicto("TODO CORRECTO", [
            "Hardware y controlador funcionan.",
            "Siguiente paso: copiar los archivos del nodo y ejecutar main.py."])


main()