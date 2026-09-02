"""Verificacion del entorno de trabajo - Practica 1.

Ejecutar ANTES de empezar la practica:
    python verificar_entorno.py

Comprueba version de Python, paquetes instalados, herramientas del sistema
y conectividad con la infraestructura Docker. Imprime un diagnostico con
instrucciones concretas por cada elemento faltante.
"""
import importlib
import shutil
import socket
import subprocess
import sys

OK, FALLA, AVISO = "[ OK ]", "[FALLA]", "[AVISO]"

PAQUETES = [
    ("paho.mqtt", "paho-mqtt", "Cliente MQTT. Nucleo de todas las practicas."),
    ("pandas", "pandas", "Analisis de capturas de trafico (Practica 2)."),
    ("numpy", "numpy", "Calculo numerico (Practicas 2 y 3)."),
    ("matplotlib", "matplotlib", "Graficas para los informes."),
    ("simpy", "simpy", "Simulacion de colas (Practica 3)."),
    ("pyshark", "pyshark", "Lectura de capturas pcap (Practica 2)."),
    ("serial", "pyserial", "Puente serie con el concentrador (Practica 4)."),
]

HERRAMIENTAS = [
    ("docker", "Docker: levanta broker, base de datos y tableros.", True),
    ("tshark", "Analizador de trafico en linea de comandos.", True),
    ("iperf3", "Medicion de ancho de banda (Practica 2).", True),
    ("git", "Control de versiones del repositorio del grupo.", True),
    ("tc", "Emulacion de red (Practica 3). Solo Linux.", False),
    ("esptool.py", "Flasheo de los ESP32 (Practica 4).", False),
    ("mpremote", "Copia de archivos al ESP32 (Practica 4).", False),
]

PUERTOS = [
    ("localhost", 1883, "Broker MQTT (Mosquitto)"),
    ("localhost", 8086, "Base de datos InfluxDB"),
    ("localhost", 3000, "Tableros Grafana"),
]

fallas = []


def titulo(texto):
    print(f"\n{texto}")
    print("-" * 66)


def revisar_python():
    titulo("1. Interprete de Python")
    v = sys.version_info
    if (v.major, v.minor) >= (3, 10):
        print(f"{OK} Python {v.major}.{v.minor}.{v.micro}")
    else:
        print(f"{FALLA} Python {v.major}.{v.minor}: se requiere 3.10 o superior")
        fallas.append("Instalar Python 3.10+ desde python.org o el gestor del SO")

    if sys.prefix != sys.base_prefix:
        print(f"{OK} Entorno virtual activo: {sys.prefix}")
    else:
        print(f"{AVISO} Sin entorno virtual activo")
        print("       Recomendado: python -m venv .venv && source .venv/bin/activate")


def revisar_paquetes():
    titulo("2. Paquetes de Python")
    for modulo, paquete, uso in PAQUETES:
        try:
            m = importlib.import_module(modulo)
            version = getattr(m, "__version__", "?")
            print(f"{OK} {paquete:<14} {version:<10} {uso}")
        except ImportError:
            print(f"{FALLA} {paquete:<14} {'':<10} {uso}")
            fallas.append(f"pip install {paquete}")


def revisar_herramientas():
    titulo("3. Herramientas del sistema")
    for binario, uso, obligatorio in HERRAMIENTAS:
        ruta = shutil.which(binario)
        if ruta:
            print(f"{OK} {binario:<12} {uso}")
        elif obligatorio:
            print(f"{FALLA} {binario:<12} {uso}")
            fallas.append(f"Instalar {binario} (ver LEEME, seccion de instalacion)")
        else:
            print(f"{AVISO} {binario:<12} {uso}")


def revisar_puertos():
    titulo("4. Infraestructura (contenedores Docker)")
    activo = False
    for host, puerto, servicio in PUERTOS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        if s.connect_ex((host, puerto)) == 0:
            print(f"{OK} {servicio:<28} puerto {puerto} accesible")
            activo = True
        else:
            print(f"{FALLA} {servicio:<28} puerto {puerto} sin respuesta")
        s.close()
    if not activo:
        fallas.append("Levantar la infraestructura: docker compose up -d")


def revisar_docker():
    titulo("5. Estado de los contenedores")
    if not shutil.which("docker"):
        print(f"{FALLA} Docker no esta instalado")
        return
    try:
        r = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=20,
        )
        salida = r.stdout.strip()
        if salida:
            for linea in salida.splitlines():
                print(f"{OK} {linea}")
        else:
            print(f"{AVISO} Ningun contenedor en ejecucion en este directorio")
            print("       Ejecutar desde la carpeta que contiene docker-compose.yml")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"{FALLA} No se pudo consultar Docker: {e}")
        fallas.append("Verificar que el servicio de Docker este iniciado")


if __name__ == "__main__":
    print("=" * 66)
    print("  VERIFICACION DEL ENTORNO - Telematica FES Cuautitlan")
    print("=" * 66)

    revisar_python()
    revisar_paquetes()
    revisar_herramientas()
    revisar_puertos()
    revisar_docker()

    print("\n" + "=" * 66)
    if fallas:
        print(f"  RESULTADO: {len(fallas)} elemento(s) por resolver\n")
        for i, f in enumerate(dict.fromkeys(fallas), 1):
            print(f"   {i}. {f}")
        sys.exit(1)
    print("  RESULTADO: entorno completo. Puede iniciar la practica.")
    print("=" * 66)
