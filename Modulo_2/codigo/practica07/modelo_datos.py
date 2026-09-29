"""Modelo de datos de la plataforma - Modulo 2, Practica 7.

Define que se guarda, como se guarda y cuanto tiempo se conserva. Lo usan
ingesta.py (escribe telemetria y alertas) y api.py (lee todo y registra los
comandos).

TRES TABLAS, TRES POLITICAS DE CONSERVACION

  telemetria  Volumen alto, valor decreciente. Se depura despues de N dias.
  alertas     Volumen minimo, valor permanente. NUNCA se borra: es la
              evidencia de que el sistema detecto algo y de cuando.
  comandos    Registro de auditoria del operador: que se ordeno, cuando, y
              cuanto tardo el robot en responder. Tampoco se borra.

La diferencia no es tecnica sino de proposito. Un sistema de seguridad debe
poder reconstruir despues que paso durante un incidente; la lectura rutinaria
de las 3 de la manana de hace dos meses no le sirve a nadie.

TRES DECISIONES QUE SE DEBEN PODER DEFENDER

1. INGESTA IDEMPOTENTE. MQTT con QoS 1 garantiza entrega "al menos una vez":
   un mensaje puede llegar dos veces. La clave primaria (nodo, ts) hace que el
   duplicado se descarte solo. Un mensaje reenviado es identico byte a byte,
   asi que su sello de tiempo tambien lo es.

2. MODO WAL. Por omision, SQLite bloquea las lecturas mientras alguien
   escribe. Aqui escriben dos procesos (ingesta y API) y lee un tercero (la
   consola); sin WAL aparece "database is locked" en cuanto hay trafico. Con
   WAL, lectores y escritor no se estorban.

3. SQLITE Y NO UNA BASE DE SERIES DE TIEMPO. Con un nodo cada 5 s el volumen
   es de unos pocos MB al dia. InfluxDB resolveria un problema que este
   sistema no tiene, a cambio de un servicio mas que operar. Es un recorte de
   alcance documentado, no una preferencia tecnica.

Ejecutar este archivo corre la prueba y la estimacion de volumen:
    python modelo_datos.py
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

RUTA_BD = os.environ.get("CAMPUS_BD", "campus.db")

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS telemetria (
    nodo           TEXT    NOT NULL,
    ts             TEXT    NOT NULL,     -- sello del puente, ISO 8601 UTC
    ts_ingesta     REAL    NOT NULL,     -- epoch de la escritura
    estado         TEXT    NOT NULL,
    calidad        TEXT,
    temperatura_c  REAL,
    humedad_pct    REAL,
    presion_hpa    REAL,
    dtemp_c_min    REAL,
    humo_adc       INTEGER,
    flama_adc      INTEGER,
    PRIMARY KEY (nodo, ts)               -- la clave que da la idempotencia
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_telemetria_ts ON telemetria (ts);

CREATE TABLE IF NOT EXISTS alertas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nodo         TEXT NOT NULL,
    ts           TEXT NOT NULL,
    estado       TEXT NOT NULL,
    severidad    TEXT NOT NULL,
    transicion   TEXT,
    medidas      TEXT,                   -- JSON: la foto del momento
    atendida_ts  TEXT,                   -- NULL mientras este pendiente
    UNIQUE (nodo, ts, estado)
);

CREATE TABLE IF NOT EXISTS comandos (
    id            TEXT PRIMARY KEY,      -- el mismo id del contrato
    ts_envio      TEXT NOT NULL,
    accion        TEXT NOT NULL,
    parametros    TEXT,
    resultado     TEXT,                  -- NULL hasta que el robot responde
    detalle       TEXT,
    ts_respuesta  TEXT,
    latencia_ms   REAL,
    t_envio_mono  REAL                   -- reloj monotono, para la latencia
);
"""


def ahora_iso():
    return datetime.now(timezone.utc).isoformat()


def conectar(ruta=RUTA_BD):
    con = sqlite3.connect(ruta, timeout=5.0, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(ESQUEMA_SQL)
    return con


# ------------------------------------------------------------------ escritura

def guardar_telemetria(con, msg):
    """Devuelve True si el mensaje era nuevo, False si era un duplicado."""
    m = msg["medidas"]
    cur = con.execute(
        "INSERT OR IGNORE INTO telemetria VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (msg["nodo"], msg["ts"], time.time(), msg["estado"],
         msg.get("calidad"), m.get("temperatura_c"), m.get("humedad_pct"),
         m.get("presion_hpa"), m.get("dtemp_c_min"), m.get("humo_adc"),
         m.get("flama_adc")))
    con.commit()
    return cur.rowcount == 1


def guardar_alerta(con, msg):
    cur = con.execute(
        "INSERT OR IGNORE INTO alertas "
        "(nodo, ts, estado, severidad, transicion, medidas) VALUES (?,?,?,?,?,?)",
        (msg["nodo"], msg["ts"], msg["estado"], msg["severidad"],
         msg.get("transicion"), json.dumps(msg.get("medidas", {}))))
    con.commit()
    return cur.rowcount == 1


def registrar_comando(con, cmd, t_envio_mono):
    con.execute(
        "INSERT OR IGNORE INTO comandos "
        "(id, ts_envio, accion, parametros, t_envio_mono) VALUES (?,?,?,?,?)",
        (cmd["id"], cmd["ts"], cmd["accion"],
         json.dumps(cmd.get("parametros", {})), t_envio_mono))
    con.commit()


def registrar_respuesta(con, resp, t_recepcion_mono):
    """Completa el comando con su resultado y la latencia del lazo."""
    fila = con.execute("SELECT t_envio_mono, resultado FROM comandos WHERE id=?",
                       (resp["id"],)).fetchone()
    if fila is None or fila["resultado"] is not None:
        return False          # comando ajeno, o respuesta repetida
    latencia = (t_recepcion_mono - fila["t_envio_mono"]) * 1000.0
    con.execute(
        "UPDATE comandos SET resultado=?, detalle=?, ts_respuesta=?, "
        "latencia_ms=? WHERE id=?",
        (resp["resultado"], resp.get("detalle"), resp["ts"], latencia,
         resp["id"]))
    con.commit()
    return True


def atender_alerta(con, id_alerta):
    cur = con.execute(
        "UPDATE alertas SET atendida_ts=? WHERE id=? AND atendida_ts IS NULL",
        (ahora_iso(), id_alerta))
    con.commit()
    return cur.rowcount == 1


# -------------------------------------------------------------------- lectura

def ultimos_por_nodo(con):
    return [dict(r) for r in con.execute(
        "SELECT t.* FROM telemetria t JOIN "
        "(SELECT nodo, MAX(ts) AS ts FROM telemetria GROUP BY nodo) u "
        "ON t.nodo = u.nodo AND t.ts = u.ts ORDER BY t.nodo")]


def serie(con, nodo, minutos=30, limite=2000):
    desde = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()
    return [dict(r) for r in con.execute(
        "SELECT ts, estado, temperatura_c, dtemp_c_min, humo_adc, flama_adc "
        "FROM telemetria WHERE nodo=? AND ts>=? ORDER BY ts LIMIT ?",
        (nodo, desde, limite))]


def listar_alertas(con, pendientes=False, limite=100):
    sql = "SELECT * FROM alertas"
    if pendientes:
        sql += " WHERE atendida_ts IS NULL"
    sql += " ORDER BY ts DESC LIMIT ?"
    filas = [dict(r) for r in con.execute(sql, (limite,))]
    for f in filas:
        f["medidas"] = json.loads(f["medidas"] or "{}")
    return filas


def obtener_comando(con, id_cmd):
    r = con.execute("SELECT * FROM comandos WHERE id=?", (id_cmd,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d.pop("t_envio_mono", None)
    d["parametros"] = json.loads(d["parametros"] or "{}")
    return d


# --------------------------------------------------------------- conservacion

def depurar(con, dias_telemetria=30):
    """Borra telemetria antigua. Alertas y comandos se conservan siempre."""
    limite = (datetime.now(timezone.utc) - timedelta(days=dias_telemetria)).isoformat()
    cur = con.execute("DELETE FROM telemetria WHERE ts < ?", (limite,))
    con.commit()
    return cur.rowcount


# ====================================================================== prueba
if __name__ == "__main__":
    import tempfile

    ruta = os.path.join(tempfile.mkdtemp(), "prueba.db")
    con = conectar(ruta)

    def msg(i, estado="normal"):
        return {"version": "1.0", "nodo": "d01", "calidad": "estimada",
                "ts": (datetime(2026, 1, 1, tzinfo=timezone.utc)
                       + timedelta(seconds=5 * i)).isoformat(),
                "estado": estado,
                "medidas": {"temperatura_c": 23.4, "humedad_pct": 48.0,
                            "presion_hpa": 780.1, "dtemp_c_min": 0.1,
                            "humo_adc": 318, "flama_adc": 94}}

    print("=" * 68)
    print("  PRUEBA DEL MODELO DE DATOS")
    print("=" * 68)

    # 1. Idempotencia
    a = guardar_telemetria(con, msg(0))
    b = guardar_telemetria(con, msg(0))       # el mismo mensaje, reenviado
    n = con.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0]
    ok1 = a and not b and n == 1
    print("  Idempotencia: primero={}, reenvio={}, filas={}   {}".format(
        a, b, n, "OK" if ok1 else "FALLA"))

    # 2. Alerta y su atencion
    guardar_alerta(con, {"nodo": "d01", "ts": msg(1)["ts"], "estado": "prealarma",
                         "severidad": "alta", "transicion": "normal -> prealarma",
                         "medidas": {"temperatura_c": 31.0}})
    pend = len(listar_alertas(con, pendientes=True))
    atender_alerta(con, 1)
    pend2 = len(listar_alertas(con, pendientes=True))
    ok2 = pend == 1 and pend2 == 0
    print("  Alertas pendientes antes/despues de atender: {}/{}   {}".format(
        pend, pend2, "OK" if ok2 else "FALLA"))

    # 3. Comando y latencia
    t0 = time.monotonic()
    registrar_comando(con, {"id": "cmd-prueba", "ts": ahora_iso(),
                            "accion": "centrar"}, t0)
    registrar_respuesta(con, {"id": "cmd-prueba", "ts": ahora_iso(),
                              "resultado": "ok"}, t0 + 0.012)
    c = obtener_comando(con, "cmd-prueba")
    ok3 = c["resultado"] == "ok" and abs(c["latencia_ms"] - 12.0) < 0.5
    print("  Comando registrado: resultado={}, latencia={:.1f} ms   {}".format(
        c["resultado"], c["latencia_ms"], "OK" if ok3 else "FALLA"))

    # 4. Volumen: se miden bytes reales por fila, no se suponen
    N = 5000
    for i in range(1, N + 1):
        guardar_telemetria(con, msg(i))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    bytes_fila = os.path.getsize(ruta) / (N + 1)

    print()
    print("  VOLUMEN MEDIDO: {:.0f} bytes por lectura en disco".format(bytes_fila))
    print("  " + "-" * 60)
    for etiqueta, periodo in (("normal, cada 5 s", 5), ("evento, cada 1 s", 1)):
        por_dia = 86400 / periodo * bytes_fila / 1e6
        print("  Un nodo en estado {:<18}: {:6.1f} MB/dia, {:6.0f} MB/mes".format(
            etiqueta, por_dia, por_dia * 30))
    print()
    print("  Con 30 dias de retencion y 3 nodos en estado normal, la base no")
    print("  llega a {:.0f} MB. Por eso SQLite basta y la depuracion puede ser".format(
        3 * 86400 / 5 * bytes_fila * 30 / 1e6 * 1.1))
    print("  mensual. Las alertas y los comandos no se depuran nunca.")

    ok = ok1 and ok2 and ok3
    print("\nRESULTADO: " + ("modelo de datos correcto" if ok else "revisar fallas"))
