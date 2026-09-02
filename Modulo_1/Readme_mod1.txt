# Módulo 1: Fundamentos y Análisis del Sistema

Material de trabajo para las **Semanas 1 a 4** de la asignatura **Telemática** (FES Cuautitlán, UNAM).

El objetivo de este módulo es caracterizar el problema telemático, levantar requisitos verificables, caracterizar y modelar el tráfico de las clases de servicio del sistema, dimensionar la capacidad del enlace y desplegar el nodo detector con el enlace de radiofrecuencia.

---

## 1. Estructura de Prácticas

| Práctica | Semana | Título | Modalidad / Hardware |
| :--- | :--- | :--- | :--- |
| **P1** | 1 | Entorno y primer sistema telemático | Sin hardware físico (Docker + Python) |
| **P2** | 2 | Caracterización del tráfico y costo de traducción | Sin hardware físico (`tshark`, `iperf3`) |
| **P3** | 3 | Colas y presupuestos de retardo | Linux / WSL2 (`simpy`, `iproute2`/`tc`) |
| **P4** | 4 | Nodo detector y enlace de radiofrecuencia | Con hardware (2 ESP32, nRF24L01, sensores) |

---

## 2. Organización del Código

```text
modulo1/
├── README.md                 # Este documento
└── codigo/
    ├── requirements.txt      # Dependencias de Python
    ├── infra/                # Docker Compose (Mosquitto, InfluxDB, Grafana)
    ├── practica01/           # Scripts de verificación y flujo MQTT
    ├── practica02/           # Análisis y comparación de capturas de red
    ├── practica03/           # Simulación de colas y presupuestos de retardo
    └── practica04/           # Contrato de trama, nodo detector y gateway
        ├── formato_trama.py
        ├── medir_latencia_alarma.py
        ├── autonomia.py
        ├── nodo_detector/    # Firmware MicroPython (ESP32 sensor)
        ├── concentrador/     # Firmware MicroPython (ESP32 gateway RF-Serie)
        └── puente/           # Servicio CPython (Puente serie a MQTT)
