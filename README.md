# Campus Telemático: Detección Temprana y Mitigación de Incendios

Repositorio principal del proyecto integrador de la asignatura **Telemática** (FES Cuautitlán, UNAM).

El sistema integra nodos sensores de detección en el borde, una plataforma central de supervisión y gestión de eventos, y un vehículo robótico teleoperado para tareas de mitigación.

---

## 1. Arquitectura y Dominios de Comunicación

El proyecto está dividido en tres dominios aislados para garantizar la operación sin dependencia de la infraestructura de red institucional:

| Dominio | Medio / Enlace | Tráfico principal | Frontera / Interfaz |
| :--- | :--- | :--- | :--- |
| **Detección** | nRF24L01 (2.4 GHz, 250 kbps) | Telemetría periódica y alarmas críticas | Concentrador ESP32 vía USB |
| **Servicios** | Red local / Host | Broker MQTT, base de datos, API y tableros | Servicios en contenedores |
| **Respuesta** | Wi-Fi (Punto de acceso propio) | Transmisión de video y teleoperación | Interfaz de red de la estación de control |

---

## 2. Estructura del Repositorio

El trabajo del semestre se organiza de forma modular:

```text
campus-telematico/
├── README.md                 # Este archivo (visión general del sistema)
├── modulo1/                  # Módulo 1: Fundamentos y análisis
│   ├── README.md             # Guía de inicio y preparación del Módulo 1
│   └── codigo/               # Infraestructura y prácticas 1 a 4
│       ├── infra/            # Docker Compose (Mosquitto, InfluxDB, Grafana)
│       ├── practica01/       # Entorno MQTT y flujo de eventos
│       ├── practica02/       # Caracterización de tráfico y traducción
│       ├── practica03/       # Modelado de colas y retardos
│       └── practica04/       # Nodo detector, concentrador y puente serie
└── docs/                     # Especificaciones, manuales y contratos de interfaz
