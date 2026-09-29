"""Verificacion de integracion - Modulo 2, Practica 8. Se ejecuta en la PC.

Recorre el sistema completo en el orden en que fluye la informacion y dice,
para cada eslabon, si funciona y que revisar si no.

LA DIFERENCIA CON LAS PRUEBAS DE CONTRATO
Las pruebas de contrato preguntan "cada pieza respeta el ICD?". Esta
verificacion pregunta "las piezas estan conectadas entre si?". Un sistema
puede aprobar todas las pruebas de contrato y fallar aqui: por una direccion
equivocada, un proceso sin arrancar o un cortafuegos.

EL ORDEN IMPORTA
Se verifica de la fuente hacia el operador. El primer eslabon que falla suele
explicar todos los siguientes; por eso el diagnostico se lee de arriba abajo
y se atiende la PRIMERA falla, no la mas llamativa.

Uso:
    python verificar_integracion.py
    python verificar_integracion.py --pi 10.42.0.1 --api http://localhost:8080
    python verificar_integracion.py --sin-video
"""
import argparse
import json
import socket
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

sys.path.insert(0, "../contrato")
import contrato_mensajes as ct

ORDEN_ARRANQUE = [
    "1. Broker          docker compose up -d                 (PC)",
    "2. Ingesta         python ingesta.py                    (PC, practica07)",
    "3. API             uvicorn api:app --port 8080          (PC, practica07)",
    "4. Punto de acceso ya configurado en la P5              (Pi)",
    "5. Video           python3 servidor_video.py            (Pi, practica06)",
    "6. Robot           python3 control_actuadores.py --broker 10.42.0.10  (Pi)",
    "7. Concentrador y puente_serie.py                       (PC, practica04)",
    "8. Consola         streamlit run consola.py             (PC, practica07)",
]

resultados = []


def registrar(nombre, ok, detalle, pista=""):
    resultados.append((nombre, ok, detalle, pista))
    marca = {True: "OK   ", False: "FALLA", None: "OMIT."}[ok]
    print("  [{}] {:<34} {}".format(marca, nombre, detalle))


def http_json(url, datos=None, timeout=3):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--pi", default="10.42.0.1")
    ap.add_argument("--sin-video", action="store_true")
    ap.add_argument("--espera", type=float, default=12.0,
                    help="segundos escuchando telemetria")
    a = ap.parse_args()

    print("=" * 72)
    print("  VERIFICACION DE INTEGRACION DEL SISTEMA")
    print("=" * 72)

    # ---------------------------------------------------------- 1. broker
    try:
        socket.create_connection((a.broker, 1883), timeout=2).close()
        registrar("Broker MQTT", True, "{}:1883 acepta conexiones".format(a.broker))
    except OSError as e:
        registrar("Broker MQTT", False, str(e),
                  "docker compose up -d en codigo/infra")
        return resumen()

    estados, telemetria, respuestas = {}, [], {}

    def rx(c, u, m):
        try:
            d = json.loads(m.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if m.topic.startswith("campus/estado/"):
            estados[m.topic.split("/")[-1]] = d.get("estado")
        elif m.topic.startswith("campus/telemetria/"):
            telemetria.append((d, ct.validar("telemetria", d)))
        elif m.topic == ct.TOPICOS["respuesta"]:
            respuestas[d.get("id")] = d

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id="verif-{}".format(uuid.uuid4().hex[:6]))
    c.on_message = rx
    c.connect(a.broker, 1883)
    c.subscribe("campus/estado/#")
    c.subscribe("campus/telemetria/+/ambiente")
    c.subscribe(ct.TOPICOS["respuesta"])
    c.loop_start()

    # ------------------------------------------- 2. componentes declarados
    time.sleep(2)            # los estados retenidos llegan al suscribirse
    for comp, pista in (("puente-rf", "puente_serie.py en practica04"),
                        ("ingesta", "python ingesta.py en practica07"),
                        ("robot", "control_actuadores.py en la Pi")):
        e = estados.get(comp)
        registrar("Componente '{}'".format(comp), e == "online",
                  "estado retenido: {}".format(e or "nunca se anuncio"), pista)

    # ------------------------------------------------------ 3. telemetria
    print("\n  Escuchando telemetria {:.0f} s...".format(a.espera))
    time.sleep(a.espera)
    invalidos = [e for _, e in telemetria if e]
    nodos = sorted({d.get("nodo") for d, _ in telemetria})
    if not telemetria:
        registrar("Telemetria en el broker", False, "ningun mensaje",
                  "revise el concentrador y el puente serie")
    else:
        registrar("Telemetria en el broker", not invalidos,
                  "{} mensajes de {}; {} invalidos".format(
                      len(telemetria), ", ".join(nodos), len(invalidos)),
                  invalidos[0][0] if invalidos else "")

    # -------------------------------------------------------------- 4. API
    try:
        _, s = http_json(a.api + "/salud")
        registrar("API", s.get("broker") is True,
                  "responde; broker={}".format(s.get("broker")),
                  "la API no alcanza al broker: revise CAMPUS_BROKER")
    except OSError as e:
        registrar("API", False, str(e), "uvicorn api:app --port 8080")
        s = None

    # -------------------------------------------------- 5. base de datos
    if s:
        _, nod = http_json(a.api + "/nodos")
        frescos = []
        for n in nod:
            edad = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(n["ts"])).total_seconds()
            if edad < 30:
                frescos.append(n["nodo"])
        registrar("Base actualizandose", bool(frescos),
                  "nodos con dato de menos de 30 s: {}".format(
                      ", ".join(frescos) or "ninguno"),
                  "la ingesta no esta guardando: revise su terminal")
    else:
        registrar("Base actualizandose", None, "sin API")

    # ------------------------------------------------------------ 6. video
    if a.sin_video:
        registrar("Video del robot", None, "omitido por opcion")
    else:
        try:
            _, m = http_json("http://{}:8000/metricas".format(a.pi))
            registrar("Video del robot", m["fps_real"] > 0,
                      "{:.1f} fps, {} B por cuadro".format(
                          m["fps_real"], m["bytes_cuadro"]),
                      "servidor_video.py en la Pi")
        except OSError as e:
            registrar("Video del robot", False, str(e)[:40],
                      "la PC esta en la red del robot? ping {}".format(a.pi))

    # ------------------------------------------- 7. lazo de comando por API
    if s:
        try:
            _, r = http_json(a.api + "/comandos", {"accion": "centrar"})
            id_cmd = r["id"]
            t0 = time.time()
            resultado = None
            while time.time() - t0 < 3:
                _, cmd = http_json(a.api + "/comandos/" + id_cmd)
                if cmd.get("resultado"):
                    resultado = cmd
                    break
                time.sleep(0.2)
            if resultado:
                registrar("Lazo consola-API-robot", resultado["resultado"] == "ok",
                          "{} en {:.0f} ms".format(resultado["resultado"],
                                                   resultado["latencia_ms"]))
            else:
                registrar("Lazo consola-API-robot", False,
                          "el comando salio y nadie respondio",
                          "el robot apunta a otro broker: --broker 10.42.0.10")
        except OSError as e:
            registrar("Lazo consola-API-robot", False, str(e)[:40])
    else:
        registrar("Lazo consola-API-robot", None, "sin API")

    # --------------------------------------- 8. cadena de alarma completa
    # Se inyecta una alerta del nodo reservado dff y se busca en la API.
    # Verifica broker -> ingesta -> base -> API sin tocar el hardware.
    if s:
        alerta = {"version": ct.VERSION_CONTRATO, "nodo": "dff",
                  "ts": datetime.now(timezone.utc).isoformat(),
                  "estado": "vigilancia", "severidad": "baja",
                  "transicion": "prueba de integracion"}
        c.publish("campus/alertas/baja/dff", json.dumps(alerta), qos=1)
        t0 = time.time()
        vista = None
        while time.time() - t0 < 4 and vista is None:
            time.sleep(0.3)
            _, al = http_json(a.api + "/alertas?pendientes=true")
            vista = next((x for x in al if x["nodo"] == "dff"
                          and x["ts"] == alerta["ts"]), None)
        if vista:
            http_json(a.api + "/alertas/{}/atender".format(vista["id"]), {})
            registrar("Cadena de alarma", True,
                      "alerta inyectada visible en {:.1f} s".format(time.time() - t0))
        else:
            registrar("Cadena de alarma", False, "la alerta no llego a la API",
                      "revise la ingesta: esta suscrita a campus/alertas/#?")
    else:
        registrar("Cadena de alarma", None, "sin API")

    c.loop_stop()
    c.disconnect()
    return resumen()


def resumen():
    fallas = [r for r in resultados if r[1] is False]
    print("\n" + "=" * 72)
    if not fallas:
        print("  SISTEMA INTEGRADO: todos los eslabones verificados responden.")
        print("=" * 72)
        return 0
    print("  {} ESLABON(ES) CON FALLA. Atienda el PRIMERO:".format(len(fallas)))
    print("=" * 72)
    nombre, _, detalle, pista = fallas[0]
    print("  {} -> {}".format(nombre, detalle))
    if pista:
        print("  Revisar: {}".format(pista))
    print("\n  Las fallas posteriores suelen ser consecuencia de esta.")
    print("\n  ORDEN DE ARRANQUE DEL SISTEMA")
    for paso in ORDEN_ARRANQUE:
        print("    " + paso)
    return 1


if __name__ == "__main__":
    sys.exit(main())
