"""Medicion del lazo de teleoperacion - Modulo 2, Practica 6.

Verifica el requisito RNF-02: retardo del canal de control por debajo de
150 ms en el percentil 95.

QUE MIDE
El tiempo entre publicar un comando y recibir la respuesta correlacionada por
identificador. Es decir:

    consola -> broker -> Wi-Fi -> robot -> actuador -> broker -> consola

NO incluye el video. El presupuesto del Modulo 1 (162 ms a 15 fps) SI lo
incluia, y ahi estaba su componente dominante: la espera al siguiente cuadro.
Por eso conviene medir ambos por separado y despues sumarlos:

    lazo de control (aqui)  +  latencia de video (medir_video.py)
    = lo que percibe el operador

Confundir ambos es el error mas comun al interpretar este requisito, y separar
los presupuestos es justamente lo que permite saber donde intervenir.

Uso:
    python medir_lazo_control.py --broker 10.42.0.10
    python medir_lazo_control.py --broker localhost --n 200 --periodo 0.1
"""
import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

sys.path.insert(0, "../contrato")
import contrato_mensajes as ct

enviados = {}      # id -> t_envio (perf_counter)
latencias = []
rechazos = 0


def al_recibir(cliente, userdata, msg):
    global rechazos
    t_rx = time.perf_counter()
    try:
        r = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return
    t_tx = enviados.pop(r.get("id"), None)
    if t_tx is None:
        return
    if r.get("resultado") != "ok":
        rechazos += 1
        return
    latencias.append((t_rx - t_tx) * 1000.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--periodo", type=float, default=0.2)
    ap.add_argument("--requisito", type=float, default=150.0, help="ms")
    ap.add_argument("--csv", default="lazo_control.csv")
    a = ap.parse_args()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="medidor-lazo")
    cliente.on_message = al_recibir
    try:
        cliente.connect(a.broker, 1883, 60)
    except OSError as e:
        sys.exit("No se pudo conectar al broker: {}".format(e))
    cliente.subscribe(ct.TOPICOS["respuesta"], qos=ct.QOS["respuesta"])
    cliente.loop_start()
    time.sleep(1.0)

    print("=" * 66)
    print("  LATENCIA DEL LAZO DE TELEOPERACION  (RNF-02)")
    print("=" * 66)
    print("  Broker     : {}".format(a.broker))
    print("  Comandos   : {} cada {:.2f} s".format(a.n, a.periodo))
    print("  Requisito  : p95 < {:.0f} ms".format(a.requisito))
    print("=" * 66)
    print("\n  Barriendo el pan de -60 a +60 grados...\n")

    for i in range(a.n):
        # Barrido suave: el servo se mueve de verdad, asi que la medicion
        # incluye el tiempo real de atender el comando, no solo la red.
        angulo = -60.0 + 120.0 * (i % 20) / 19.0
        id_cmd = "m-{}".format(uuid.uuid4().hex[:8])
        cmd = {
            "version": ct.VERSION_CONTRATO,
            "id": id_cmd,
            "ts": datetime.now(timezone.utc).isoformat(),
            "accion": "apuntar",
            "parametros": {"pan_grados": round(angulo, 1)},
        }
        enviados[id_cmd] = time.perf_counter()
        cliente.publish(ct.TOPICOS["comando"], json.dumps(cmd),
                        qos=ct.QOS["comando"])
        time.sleep(a.periodo)

        if (i + 1) % 20 == 0:
            print("  {}/{} enviados, {} respuestas".format(
                i + 1, a.n, len(latencias)))

    time.sleep(2.0)
    cliente.loop_stop()
    cliente.disconnect()

    print("\n" + "=" * 66)
    print("  RESULTADOS")
    print("=" * 66)

    if not latencias:
        print("  Ninguna respuesta recibida.")
        print("  Verifique que control_actuadores.py este en ejecucion y")
        print("  que ambos apunten al mismo broker.")
        return

    lat = sorted(latencias)
    p50 = statistics.median(lat)
    p95 = lat[min(int(0.95 * len(lat)), len(lat) - 1)]
    p99 = lat[min(int(0.99 * len(lat)), len(lat) - 1)]
    perdidos = a.n - len(lat) - rechazos

    print("  Comandos enviados  : {}".format(a.n))
    print("  Respuestas         : {}".format(len(lat)))
    print("  Rechazados         : {}".format(rechazos))
    print("  Sin respuesta      : {}  ({:.1f} %)".format(
        perdidos, 100.0 * perdidos / a.n))
    print()
    print("  Minimo             : {:7.2f} ms".format(min(lat)))
    print("  Mediana (p50)      : {:7.2f} ms".format(p50))
    print("  Percentil 95       : {:7.2f} ms".format(p95))
    print("  Percentil 99       : {:7.2f} ms".format(p99))
    print("  Maximo             : {:7.2f} ms".format(max(lat)))
    print("  Desviacion tipica  : {:7.2f} ms".format(statistics.pstdev(lat)))
    print()
    print("  Requisito RNF-02   : p95 < {:.0f} ms".format(a.requisito))
    print("  VEREDICTO          : " +
          ("CUMPLE" if p95 < a.requisito else "NO CUMPLE"))

    print("\n  LECTURA DEL RESULTADO")
    print("  La diferencia entre p50 y p99 mide el jitter del enlace. Si p50")
    print("  cumple y p99 no, el problema no es la capacidad sino la varianza,")
    print("  y se ataca con planificacion de espectro, no con mas ancho de banda.")
    print()
    print("  ESTE NUMERO NO ES LO QUE PERCIBE EL OPERADOR.")
    print("  Falta sumarle la latencia del video. El presupuesto del Modulo 1")
    print("  daba 162 ms para el lazo completo a 15 fps, dominado por la espera")
    print("  al siguiente cuadro. Mida el video aparte y sume.")

    with open(a.csv, "w", encoding="utf-8") as f:
        f.write("muestra,latencia_ms\n")
        for k, v in enumerate(latencias, 1):
            f.write("{},{:.3f}\n".format(k, v))
    print("\n  Mediciones en: {}".format(a.csv))


if __name__ == "__main__":
    main()
