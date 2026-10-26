"""Configuracion del nodo detector, firmware v3 - Modulo 3.

Cada nodo debe tener un ID_NODO distinto. Si dos nodos comparten
identificador, el concentrador los mezcla.

Copiar al ESP32:
    mpremote connect COM5 fs cp config.py :config.py
"""

# --- Identidad ---
ID_NODO = 1                # 1, 2, 3 ... unico por nodo detector

# --- Radio ---
CANAL_RF = 76              # 2476 MHz. En la P9 se cambia a 70 (2470 MHz)
                           # para traslaparlo con el Wi-Fi del canal 11.
                           # Debe coincidir con el del concentrador.
DIRECCION = b"FUEGO"       # 5 bytes, igual en el concentrador

# --- Temporizacion ---
PERIODO_S = 5              # periodo en estado normal; en eventos acelera solo
PERIODO_FIJO_S = None      # P9 y P10: 1.0 fija el periodo para medir rapido.
                           # None en operacion normal.

# --- Acceso al medio ---
POLITICA = "v3"            # "v3": Modulo 3.  "v1": como el Modulo 1
                           # (sin azar, sin reintentos por software).

# --- Sensores ---
PRECALENTADO_S = 60        # el MQ-2 no es fiable antes de este tiempo
FLAMA_NIVEL_ACTIVO = 0     # nivel de D0 con flama presente. Verificar con el
                           # LED del modulo: 0 en la mayoria (LM393 a tierra)
