#!/usr/bin/env bash
# =====================================================================
#  Configuracion del punto de acceso del robot - Modulo 2, Practica 5
#  Se ejecuta EN LA RASPBERRY PI, una sola vez.
#
#  QUE HACE
#  Convierte la Raspberry Pi en un punto de acceso Wi-Fi propio, con su
#  propia subred y su propio servidor DHCP, independiente de la red
#  institucional.
#
#  POR QUE LA PI Y NO LA COMPUTADORA
#    - La red institucional (PC Puma / RIU) aisla a los clientes entre si:
#      aunque el robot se autenticara, la PC no podria alcanzarlo.
#    - Muchas tarjetas Wi-Fi integradas de PC no admiten modo punto de
#      acceso. La Pi 3B si, de forma fiable, con NetworkManager.
#    - Al poseer el punto de acceso, los alumnos controlan el canal y la
#      potencia. Eso es lo que hace posible el experimento de coexistencia
#      de espectro del Modulo 3.
#
#  EL COSTO, QUE HAY QUE DECLARAR
#    - La Pi 3B carga a la vez con el punto de acceso y la codificacion de
#      video, con 1 GB de RAM. Es el cuello de botella mas probable.
#    - El punto de acceso se mueve con el robot: el alcance depende de
#      donde este el vehiculo, no de una antena bien colocada.
#
#  Uso:
#      chmod +x configurar_ap.sh
#      sudo ./configurar_ap.sh
# =====================================================================
set -euo pipefail

SSID="${SSID:-campus-robot}"
CLAVE="${CLAVE:-telematica2026}"
CANAL="${CANAL:-1}"          # canal 1 = 2412 MHz, ocupa 2401-2423 MHz.
                             # El enlace nRF24L01 usa el canal 76 = 2476 MHz.
                             # Quedan separados por mas de 50 MHz.
IFACE="${IFACE:-wlan0}"
CONEXION="robot-ap"
SUBRED="10.42.0.1/24"

if [[ $EUID -ne 0 ]]; then
    echo "Ejecutar con sudo." >&2
    exit 1
fi

echo "======================================================================"
echo "  PUNTO DE ACCESO DEL ROBOT"
echo "======================================================================"
echo "  SSID      : $SSID"
echo "  Canal     : $CANAL (2.4 GHz)"
echo "  Interfaz  : $IFACE"
echo "  Direccion : $SUBRED"
echo "======================================================================"
echo

# --- Verificaciones previas -------------------------------------------
if ! command -v nmcli >/dev/null; then
    echo "Falta NetworkManager. Instalar con:" >&2
    echo "    sudo apt install network-manager" >&2
    exit 1
fi

if ! iw list 2>/dev/null | grep -q "AP$"; then
    echo "AVISO: 'iw list' no reporta modo AP para esta interfaz."
    echo "       En la Pi 3B deberia estar disponible. Continuando."
fi

# --- Limpiar una configuracion anterior -------------------------------
if nmcli -t -f NAME connection show | grep -qx "$CONEXION"; then
    echo "Eliminando la configuracion anterior '$CONEXION'..."
    nmcli connection delete "$CONEXION" >/dev/null
fi

# --- Crear el punto de acceso -----------------------------------------
echo "Creando el punto de acceso..."
nmcli connection add type wifi ifname "$IFACE" con-name "$CONEXION" \
    autoconnect yes ssid "$SSID" >/dev/null

nmcli connection modify "$CONEXION" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel "$CANAL" \
    ipv4.method shared \
    ipv4.addresses "$SUBRED" \
    ipv6.method disabled \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$CLAVE" >/dev/null

echo "Levantando la conexion..."
nmcli connection up "$CONEXION" >/dev/null

# --- Reserva estatica para la computadora -----------------------------
# EL PROBLEMA QUE ESTO RESUELVE
# La Pi reparte direcciones por DHCP, pero el broker MQTT vive en la
# computadora. Si la computadora recibe una direccion distinta en cada
# arranque, el robot no sabe donde publicar.
#
# Es el tipo de detalle que rompe la integracion de la semana 8 si no se
# resuelve antes, y que no aparece en ningun diagrama de arquitectura.

DIR_RESERVAS="/etc/NetworkManager/dnsmasq-shared.d"
mkdir -p "$DIR_RESERVAS"

if [[ -n "${MAC_PC:-}" ]]; then
    echo "Reservando 10.42.0.10 para la computadora ($MAC_PC)..."
    cat > "$DIR_RESERVAS/reservas.conf" <<EOF
# Reserva estatica: la computadora que hospeda el broker MQTT.
# Generado por configurar_ap.sh
dhcp-host=$MAC_PC,10.42.0.10,pc-broker
EOF
    nmcli connection down "$CONEXION" >/dev/null
    nmcli connection up "$CONEXION" >/dev/null
else
    cat > "$DIR_RESERVAS/reservas.conf" <<'EOF'
# Reserva estatica para la computadora que hospeda el broker.
# Sustituya AA:BB:CC:DD:EE:FF por la direccion fisica real de la interfaz
# Wi-Fi de la computadora y reinicie la conexion:
#     nmcli connection down robot-ap && nmcli connection up robot-ap
#
# Para obtener la direccion fisica, en la computadora:
#     Linux   : ip link show
#     Windows : ipconfig /all
#     macOS   : ifconfig en0
#
#dhcp-host=AA:BB:CC:DD:EE:FF,10.42.0.10,pc-broker
EOF
    echo
    echo "PENDIENTE: editar $DIR_RESERVAS/reservas.conf"
    echo "           con la direccion fisica de la computadora."
    echo "           O volver a ejecutar con: sudo MAC_PC=aa:bb:.. ./configurar_ap.sh"
fi

# --- Resultado ---------------------------------------------------------
echo
echo "======================================================================"
echo "  RESULTADO"
echo "======================================================================"
nmcli -t -f GENERAL.STATE,IP4.ADDRESS connection show "$CONEXION" 2>/dev/null \
    | sed 's/^/  /'
echo
ip -4 addr show "$IFACE" | grep inet | sed 's/^/  /'
echo
echo "  La Pi es 10.42.0.1 y reparte de 10.42.0.10 en adelante."
echo
echo "  SIGUIENTE PASO"
echo "  Conectar la computadora a la red '$SSID' y verificar:"
echo "      ping 10.42.0.1"
echo "      python verificar_enlace.py --pi 10.42.0.1"
echo
echo "  IMPORTANTE: la computadora conserva su cable a la red institucional."
echo "  Son dos interfaces independientes y no se debe hacer puente entre"
echo "  ellas. El robot nunca toca la red del campus."
