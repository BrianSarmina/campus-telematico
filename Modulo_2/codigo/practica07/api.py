"""API de la plataforma - Modulo 2, Practica 7. Se ejecuta en la computadora.

Es la unica puerta de la consola hacia el sistema: la consola nunca habla
MQTT, solo HTTP. Asi el operador depende de una sola interfaz, y esa interfaz
tiene su propio contrato (OpenAPI), que FastAPI genera a partir del codigo.

RECURSOS
    GET  /salud                  estado de la API, la base y el broker
    GET  /nodos                  ultima lectura de cada nodo
    GET  /telemetria/{nodo}      serie reciente de un nodo
    GET  /alertas                alertas, todas o solo pendientes
    POST /alertas/{id}/atender   el operador marca una alerta como atendida
    POST /comandos               ordena una accion al robot
    GET  /comandos/{id}          resultado y latencia de un comando
    GET  /docs                   documentacion interactiva generada

CODIGOS DE ESTADO, Y POR QUE ESOS
    202 Accepted  al enviar un comando: la API lo publico, pero el robot aun
                  no lo ejecuta. Responder 200 mentiria sobre lo que se sabe.
    404           nodo, alerta o comando inexistente.
    422           el comando viola el contrato. Se rechaza ANTES de publicar,
                  la misma barrera que aplica el robot, un paso antes.
    503           el broker no esta disponible. La API sigue viva y sirve lo
                  que ya esta en la base: se degrada, no se cae.

Uso:
    uvicorn api:app --host 0.0.0.0 --port 8080
    CAMPUS_BROKER=localhost CAMPUS_BD=campus.db uvicorn api:app --port 8080
"""
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "contrato"))
import contrato_mensajes as ct
import modelo_datos as md

BROKER = os.environ.get("CAMPUS_BROKER", "localhost")
RUTA_BD = os.environ.get("CAMPUS_BD", md.RUTA_BD)

estado = {"broker": False, "cliente": None}


def iniciar_mqtt():
    """Conecta al broker y escucha las respuestas del robot.

    La API registra la latencia de cada comando porque es la unica que
    conoce el instante de envio. El reloj es monotono y del mismo proceso,
    asi que no hay que sincronizar nada.
    """
    con_resp = md.conectar(RUTA_BD)

    def al_conectar(c, u, flags, motivo, props=None):
        estado["broker"] = not motivo.is_failure
        c.subscribe(ct.TOPICOS["respuesta"], qos=ct.QOS["respuesta"])

    def al_desconectar(c, u, flags, motivo, props=None):
        estado["broker"] = False

    def al_recibir(c, u, m):
        t = time.monotonic()
        try:
            r = json.loads(m.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not ct.validar("respuesta", r):
            md.registrar_respuesta(con_resp, r, t)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id="api-{}".format(uuid.uuid4().hex[:6]))
    c.on_connect = al_conectar
    c.on_disconnect = al_desconectar
    c.on_message = al_recibir
    c.reconnect_delay_set(min_delay=1, max_delay=10)
    try:
        c.connect(BROKER, 1883, keepalive=30)
    except OSError:
        pass              # la API arranca igual; /salud lo reporta
    c.loop_start()
    estado["cliente"] = c


@asynccontextmanager
async def ciclo_de_vida(app):
    md.conectar(RUTA_BD).close()       # crea las tablas si no existen
    iniciar_mqtt()
    yield
    if estado["cliente"]:
        estado["cliente"].loop_stop()
        estado["cliente"].disconnect()


app = FastAPI(title="Campus Telematico - Plataforma",
              version=ct.VERSION_CONTRATO, lifespan=ciclo_de_vida)


def bd():
    return md.conectar(RUTA_BD)


class ComandoEntrada(BaseModel):
    accion: str = Field(description="apuntar | ventilador | centrar | parar")
    parametros: dict = Field(default_factory=dict)


# --------------------------------------------------------------------- rutas

@app.get("/salud")
def salud():
    con = bd()
    n = con.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0]
    con.close()
    return {"api": "ok", "broker": estado["broker"], "lecturas": n,
            "contrato": ct.VERSION_CONTRATO}


@app.get("/nodos")
def nodos():
    con = bd()
    filas = md.ultimos_por_nodo(con)
    con.close()
    return filas


@app.get("/telemetria/{nodo}")
def telemetria(nodo: str, minutos: int = Query(30, ge=1, le=10080)):
    con = bd()
    filas = md.serie(con, nodo, minutos)
    existe = con.execute("SELECT 1 FROM telemetria WHERE nodo=? LIMIT 1",
                         (nodo,)).fetchone()
    con.close()
    if not existe:
        raise HTTPException(404, "Nodo {} sin datos".format(nodo))
    return filas


@app.get("/alertas")
def alertas(pendientes: bool = False, limite: int = Query(100, ge=1, le=1000)):
    con = bd()
    filas = md.listar_alertas(con, pendientes, limite)
    con.close()
    return filas


@app.post("/alertas/{id_alerta}/atender")
def atender(id_alerta: int):
    con = bd()
    ok = md.atender_alerta(con, id_alerta)
    con.close()
    if not ok:
        raise HTTPException(404, "Alerta inexistente o ya atendida")
    return {"id": id_alerta, "atendida": True}


@app.post("/comandos", status_code=202)
def enviar_comando(entrada: ComandoEntrada):
    cmd = {
        "version": ct.VERSION_CONTRATO,
        "id": "api-{}".format(uuid.uuid4().hex[:10]),
        "ts": datetime.now(timezone.utc).isoformat(),
        "accion": entrada.accion,
    }
    if entrada.parametros:
        cmd["parametros"] = entrada.parametros

    # Barrera del contrato ANTES de publicar
    errores = ct.validar("comando", cmd)
    if errores:
        raise HTTPException(422, {"motivo": "viola el contrato",
                                  "errores": errores})

    if not estado["broker"]:
        raise HTTPException(503, "Broker no disponible; el comando no se envio")

    con = bd()
    md.registrar_comando(con, cmd, time.monotonic())
    con.close()
    estado["cliente"].publish(ct.TOPICOS["comando"], json.dumps(cmd),
                              qos=ct.QOS["comando"])
    return {"id": cmd["id"], "estado": "enviado"}


@app.get("/comandos/{id_cmd}")
def consultar_comando(id_cmd: str):
    con = bd()
    c = md.obtener_comando(con, id_cmd)
    con.close()
    if c is None:
        raise HTTPException(404, "Comando inexistente")
    return c
