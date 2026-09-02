"""Diagnostico del bus I2C - Practica 4 (MicroPython, se ejecuta en el ESP32).

Es el PRIMER programa que debe correr en el nodo. Si el sensor no aparece
aqui, no tiene sentido continuar: el problema es de cableado, no de codigo.

Ejecutar sin copiarlo al dispositivo:
    mpremote connect /dev/ttyUSB0 run escanear_i2c.py
"""
from machine import I2C, Pin
import time

SCL = 22
SDA = 21

CONOCIDOS = {
    0x76: "BME280 / BMP280 (direccion principal)",
    0x77: "BME280 / BMP280 (direccion alterna, SDO a VCC)",
    0x3C: "Pantalla OLED SSD1306",
    0x48: "ADS1115 / convertidor analogico-digital",
    0x68: "MPU6050 o reloj de tiempo real DS3231",
    0x40: "Sensor de humedad HTU21D / SHT21",
}

print("=" * 58)
print("  ESCANEO DEL BUS I2C")
print(f"  SCL = GPIO{SCL}   SDA = GPIO{SDA}")
print("=" * 58)

try:
    i2c = I2C(0, scl=Pin(SCL), sda=Pin(SDA), freq=100000)
except Exception as e:
    print(f"ERROR al inicializar el bus: {e}")
    raise SystemExit

dispositivos = i2c.scan()

if not dispositivos:
    print("\n  NO se detecto ningun dispositivo.\n")
    print("  Revisar en este orden:")
    print("   1. VCC del sensor al pin 3V3 del ESP32 (NO a 5V ni a VIN)")
    print("   2. GND del sensor a GND del ESP32")
    print("   3. SCL del sensor a GPIO22")
    print("   4. SDA del sensor a GPIO21")
    print("   5. Cables firmes en la protoboard (es la causa mas frecuente)")
    print("   6. Probar otro juego de cables: los jumpers se rompen por dentro")
    print("   7. Medir con el multimetro que llegue 3.3 V al sensor")
else:
    print(f"\n  Dispositivos encontrados: {len(dispositivos)}\n")
    for d in dispositivos:
        descripcion = CONOCIDOS.get(d, "desconocido")
        print(f"   0x{d:02X}  ({d:3d})  {descripcion}")

    if 0x76 in dispositivos or 0x77 in dispositivos:
        direccion = 0x76 if 0x76 in dispositivos else 0x77
        chip = i2c.readfrom_mem(direccion, 0xD0, 1)[0]
        print(f"\n  Registro de identificacion (0xD0) = 0x{chip:02X}")
        if chip == 0x60:
            print("   -> BME280 confirmado. Mide temperatura, presion y humedad.")
        elif chip == 0x58:
            print("   -> Es un BMP280: mide temperatura y presion, NO humedad.")
            print("      El proyecto requiere humedad; solicitar el modulo correcto.")
        else:
            print("   -> Identificacion no reconocida. Revisar el modulo.")

print("\n" + "=" * 58)
print("  Si el sensor aparece correctamente, continuar con prueba_sensor.py")
print("=" * 58)
