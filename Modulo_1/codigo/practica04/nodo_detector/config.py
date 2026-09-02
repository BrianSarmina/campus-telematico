"""Configuracion del nodo detector - Practica 4.

Cada nodo debe tener un ID_NODO distinto. Si dos nodos comparten
identificador, el concentrador los mezcla y la deteccion de perdidas por
numero de secuencia deja de funcionar.

Copiar al ESP32:
    mpremote connect /dev/ttyUSB0 fs cp config.py :config.py
"""

# --- Identidad ---
ID_NODO = 1                # 1, 2, 3 ... unico por nodo detector

# --- Radio ---
CANAL_RF = 76              # 2476 MHz. Ver la seccion de coexistencia:
                           # debe quedar lejos del canal del punto de acceso
DIRECCION = b"FUEGO"       # 5 bytes, igual en el concentrador

# --- Temporizacion ---
PERIODO_S = 5              # periodo en estado normal
                           # en prealarma y alarma el nodo acelera solo

# --- Sensores ---
PRECALENTADO_S = 60        # el MQ-2 no es fiable antes de este tiempo.
                           # La PRIMERA vez que se energiza el sensor
                           # requiere de 24 a 48 h de precalentamiento.
