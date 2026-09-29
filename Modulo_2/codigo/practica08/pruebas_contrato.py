"""Pruebas de contrato - Modulo 2, Practica 8.

Verifican de forma automatica que cada pieza del sistema respeta el ICD.

DOS NIVELES

  Sin hardware (por omision). Corren en cualquier computadora en segundos:
  esquemas, trama de radiofrecuencia, modelo de datos, API y congelamiento.
  Se ejecutan despues de CADA cambio.

      pytest pruebas_contrato.py -v

  Integracion (marca "integracion"). Necesitan el sistema levantado: broker,
  robot y flujo de telemetria. Verifican que las piezas reales, no sus
  dobles, cumplen el contrato.

      pytest pruebas_contrato.py -v -m integracion

UN DOBLE DE PRUEBA EN ACCION
Las pruebas de la API sustituyen el cliente MQTT por un objeto que solo anota
lo que se le pide publicar. Asi se verifica que la API publica un comando
valido, en el topico correcto y con el QoS del contrato, sin necesitar broker.
Es el mismo principio que el stub del robot, aplicado un nivel mas abajo.
"""
import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "contrato"))
sys.path.insert(0, os.path.join(AQUI, "..", "practica07"))

import contrato_mensajes as ct
import generar_icd
import modelo_datos as md
import trama_rf

BROKER = os.environ.get("CAMPUS_BROKER", "localhost")


def ahora():
    return datetime.now(timezone.utc).isoformat()


# =================================================================
#  1. ESQUEMAS
# =================================================================

VALIDOS = [
    ("telemetria", {"version": "1.0", "nodo": "d01", "ts": "2026-01-01T00:00:00+00:00",
                    "estado": "normal",
                    "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                                "humo_adc": 318, "flama_adc": 94}}),
    ("alerta", {"version": "1.0", "nodo": "d01", "ts": "2026-01-01T00:00:00+00:00",
                "estado": "alarma", "severidad": "critica",
                "transicion": "prealarma -> alarma"}),
    ("comando", {"version": "1.0", "id": "cmd-0001", "ts": "2026-01-01T00:00:00+00:00",
                 "accion": "apuntar", "parametros": {"pan_grados": -30.0}}),
    ("respuesta", {"version": "1.0", "id": "cmd-0001", "ts": "2026-01-01T00:00:00+00:00",
                   "resultado": "ok"}),
]

INVALIDOS = [
    ("telemetria", {"version": "1.0", "nodo": "d01", "ts": "x", "estado": "normal",
                    "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                                "humo_adc": 5000, "flama_adc": 94}},
     "humo fuera del rango del convertidor"),
    ("telemetria", {"version": "1.0", "nodo": "d01", "ts": "x", "estado": "incendio",
                    "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                                "humo_adc": 300, "flama_adc": 94}},
     "estado que no existe en el contrato"),
    ("telemetria", {"version": "1.0", "nodo": "d01", "ts": "x", "estado": "normal",
                    "extra": 1,
                    "medidas": {"temperatura_c": 23.4, "dtemp_c_min": 0.1,
                                "humo_adc": 300, "flama_adc": 94}},
     "campo no declarado"),
    ("comando", {"version": "1.0", "id": "c1", "ts": "x", "accion": "centrar"},
     "identificador demasiado corto"),
    ("comando", {"version": "1.0", "id": "cmd-0002", "ts": "x", "accion": "apuntar",
                 "parametros": {"tilt_grados": 60}},
     "tilt fuera del rango mecanico"),
    ("alerta", {"version": "1.0", "nodo": "d01", "ts": "x", "estado": "normal",
                "severidad": "baja", "transicion": "x"},
     "una alerta no puede tener estado normal"),
]


@pytest.mark.parametrize("tipo,msg", VALIDOS, ids=[v[0] for v in VALIDOS])
def test_mensaje_valido_se_acepta(tipo, msg):
    assert ct.validar(tipo, msg) == []


@pytest.mark.parametrize("tipo,msg,motivo", INVALIDOS, ids=[i[2] for i in INVALIDOS])
def test_mensaje_invalido_se_rechaza(tipo, msg, motivo):
    assert ct.validar(tipo, msg), "debio rechazarse: " + motivo


def test_todos_los_topicos_tienen_qos():
    assert set(ct.TOPICOS) == set(ct.QOS)


# =================================================================
#  2. TRAMA DE RADIOFRECUENCIA
# =================================================================

def test_trama_cabe_en_el_nrf24l01():
    assert trama_rf.TAMANO <= 32


def test_trama_ida_y_vuelta():
    t = trama_rf.empaquetar(3, 1234, 38.9, 38.5, 780.05, 2100, 140, 9.4,
                            trama_rf.PREALARMA)
    r = trama_rf.desempaquetar(t)
    assert r["nodo"] == "d03" and r["secuencia"] == 1234
    assert r["estado"] == "prealarma"
    assert abs(r["medidas"]["temperatura_c"] - 38.9) <= 0.005 + 1e-9


def test_trama_de_version_desconocida_se_rechaza():
    t = bytearray(trama_rf.empaquetar(1, 0, 20, 40, 780, 0, 0, 0, 0))
    t[0] = 99
    with pytest.raises(ValueError):
        trama_rf.desempaquetar(bytes(t))


# =================================================================
#  3. MODELO DE DATOS
# =================================================================

@pytest.fixture
def base(tmp_path):
    con = md.conectar(str(tmp_path / "prueba.db"))
    yield con
    con.close()


def test_ingesta_idempotente(base):
    m = VALIDOS[0][1]
    assert md.guardar_telemetria(base, m) is True
    assert md.guardar_telemetria(base, m) is False       # reenvio QoS 1
    assert base.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0] == 1


def test_alerta_se_atiende_una_sola_vez(base):
    md.guardar_alerta(base, VALIDOS[1][1])
    assert md.atender_alerta(base, 1) is True
    assert md.atender_alerta(base, 1) is False


def test_depuracion_conserva_las_alertas(base):
    md.guardar_telemetria(base, VALIDOS[0][1])            # fecha de 2026-01-01
    md.guardar_alerta(base, VALIDOS[1][1])
    md.depurar(base, dias_telemetria=1)
    assert base.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0] == 0
    assert base.execute("SELECT COUNT(*) FROM alertas").fetchone()[0] == 1


# =================================================================
#  4. API, con un doble del cliente MQTT
# =================================================================

class ClienteFalso:
    """Doble de prueba: anota lo que se publicaria, sin broker."""

    def __init__(self):
        self.publicados = []

    def publish(self, topico, carga, qos=0, retain=False):
        self.publicados.append((topico, json.loads(carga), qos))

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


@pytest.fixture
def api_cliente(tmp_path):
    from fastapi.testclient import TestClient
    import api
    api.RUTA_BD = str(tmp_path / "api.db")
    with TestClient(api.app) as cliente:
        falso = ClienteFalso()
        api.estado["cliente"] = falso
        api.estado["broker"] = True
        yield cliente, falso, api


def test_api_publica_comando_valido_segun_contrato(api_cliente):
    cliente, falso, _ = api_cliente
    r = cliente.post("/comandos", json={"accion": "apuntar",
                                        "parametros": {"pan_grados": 45}})
    assert r.status_code == 202
    topico, msg, qos = falso.publicados[-1]
    assert topico == ct.TOPICOS["comando"]
    assert qos == ct.QOS["comando"]
    assert ct.validar("comando", msg) == []
    assert msg["id"] == r.json()["id"]


def test_api_rechaza_antes_de_publicar(api_cliente):
    cliente, falso, _ = api_cliente
    r = cliente.post("/comandos", json={"accion": "apuntar",
                                        "parametros": {"pan_grados": 150}})
    assert r.status_code == 422
    assert falso.publicados == []                        # nunca salio


def test_api_sin_broker_responde_503(api_cliente):
    cliente, falso, api = api_cliente
    api.estado["broker"] = False
    r = cliente.post("/comandos", json={"accion": "centrar"})
    assert r.status_code == 503
    assert cliente.get("/salud").status_code == 200      # se degrada, no se cae


def test_api_nodo_inexistente_404(api_cliente):
    cliente, _, _ = api_cliente
    assert cliente.get("/telemetria/d99").status_code == 404


# =================================================================
#  5. CONGELAMIENTO
# =================================================================

def test_contrato_no_cambio_sin_declararlo():
    if not os.path.exists(generar_icd.ARCHIVO_CONGELADO):
        pytest.skip("El ICD aun no esta congelado (generar_icd.py --congelar)")
    congelado = json.load(open(generar_icd.ARCHIVO_CONGELADO, encoding="utf-8"))
    actual = generar_icd.huella()
    if actual != congelado["huella"]:
        assert ct.VERSION_CONTRATO != congelado["version"], (
            "La interfaz cambio y la version sigue en {}. Revierta el cambio o "
            "suba la version y vuelva a congelar.".format(congelado["version"]))


# =================================================================
#  6. INTEGRACION: piezas reales, no dobles
# =================================================================

def _broker_disponible():
    try:
        socket.create_connection((BROKER, 1883), timeout=1).close()
        return True
    except OSError:
        return False


class Sesion:
    """Cliente MQTT de prueba que recoge respuestas del robot."""

    def __init__(self):
        import paho.mqtt.client as mqtt
        self.respuestas = {}
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="pruebas-{}".format(uuid.uuid4().hex[:6]))
        self.c.on_message = self._rx
        self.c.connect(BROKER, 1883)
        self.c.subscribe(ct.TOPICOS["respuesta"])
        self.c.loop_start()
        time.sleep(0.5)

    def _rx(self, c, u, m):
        r = json.loads(m.payload.decode())
        self.respuestas.setdefault(r["id"], []).append(r)

    def comando(self, accion, esperar=1.5, id_cmd=None, **param):
        cmd = {"version": ct.VERSION_CONTRATO,
               "id": id_cmd or "t-{}".format(uuid.uuid4().hex[:8]),
               "ts": ahora(), "accion": accion}
        if param:
            cmd["parametros"] = param
        self.c.publish(ct.TOPICOS["comando"], json.dumps(cmd))
        time.sleep(esperar)
        return cmd["id"], self.respuestas.get(cmd["id"], [])

    def cerrar(self):
        self.c.loop_stop()
        self.c.disconnect()


@pytest.fixture
def sesion():
    if not _broker_disponible():
        pytest.skip("Broker no disponible en {}".format(BROKER))
    s = Sesion()
    # Sondeo con reintentos: la primera suscripcion puede tardar en quedar
    # activa en el broker, y un solo intento produce omisiones falsas.
    for _ in range(3):
        _, r = s.comando("parar")
        if r:
            break
    else:
        s.cerrar()
        pytest.skip("El robot no responde (control_actuadores.py no corre)")
    yield s
    s.cerrar()


@pytest.mark.integracion
def test_robot_rechaza_fuera_de_rango(sesion):
    _, r = sesion.comando("apuntar", pan_grados=150)
    assert r and r[0]["resultado"] == "rechazado"


@pytest.mark.integracion
def test_robot_es_idempotente(sesion):
    id_cmd = "t-idem-{}".format(uuid.uuid4().hex[:6])
    sesion.comando("centrar", id_cmd=id_cmd, esperar=0.8)
    sesion.comando("centrar", id_cmd=id_cmd, esperar=0.8)
    r = sesion.respuestas[id_cmd]
    assert len(r) == 2 and r[1].get("detalle") == "duplicado ignorado"


@pytest.mark.integracion
def test_robot_estado_seguro(sesion):
    _, r = sesion.comando("ventilador", encendido=True, esperar=0.5)
    assert r[0]["posicion"]["ventilador"] is True
    time.sleep(ct.PLAZO_SEGURO_S + 1.0)          # silencio del operador
    _, r = sesion.comando("apuntar", esperar=0.8, pan_grados=0)
    assert r[0]["posicion"]["ventilador"] is False, \
        "el robot debio apagar el ventilador tras el plazo seguro"


@pytest.mark.integracion
def test_telemetria_en_vivo_cumple_contrato():
    if not _broker_disponible():
        pytest.skip("Broker no disponible")
    import paho.mqtt.client as mqtt
    recibidos, errores = [], []

    def rx(c, u, m):
        msg = json.loads(m.payload.decode())
        recibidos.append(msg)
        e = ct.validar("telemetria", msg)
        if e:
            errores.append((m.topic, e[0]))

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pruebas-tel")
    c.on_message = rx
    c.connect(BROKER, 1883)
    c.subscribe("campus/telemetria/+/ambiente")
    c.loop_start()
    time.sleep(12)
    c.loop_stop()
    c.disconnect()
    if not recibidos:
        pytest.skip("No llego telemetria en 12 s (puente o publicador detenido)")
    assert errores == [], errores[:3]
