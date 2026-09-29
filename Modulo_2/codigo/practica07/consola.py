"""Consola de operacion - Modulo 2, Practica 7. Se ejecuta en la computadora.

Lo que ve y usa el operador: estado de los nodos, alertas pendientes, serie de
temperatura, video del robot y controles del actuador.

LA CONSOLA SOLO HABLA HTTP CON LA API
Nunca se conecta al broker. Si manana se cambia MQTT por otra cosa, la consola
no se entera. Una sola frontera, con su propio contrato.

EL INTERRUPTOR DE HOMBRE MUERTO
El contrato fija que el robot apaga el ventilador si pasa PLAZO_SEGURO_S sin
recibir comandos. Consecuencia para este lado: mientras el operador quiera el
ventilador encendido, la consola debe REENVIAR la orden cada segundo. Si la
consola se cuelga o se pierde el enlace, el reenvio se detiene y el robot se
pone a salvo solo.

Es la misma logica del pedal de hombre muerto de un tren: el sistema exige una
senal continua de que alguien esta al mando. El comportamiento seguro de un
lado del contrato impone una obligacion al otro lado, y eso no se ve hasta
que se integran ambos.

Uso:
    streamlit run consola.py
    CAMPUS_API=http://localhost:8080 CAMPUS_VIDEO=http://10.42.0.1:8000/video \\
        streamlit run consola.py
"""
import os
import time

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("CAMPUS_API", "http://localhost:8080")
VIDEO = os.environ.get("CAMPUS_VIDEO", "http://10.42.0.1:8000/video")
COLOR = {"normal": "green", "vigilancia": "orange",
         "prealarma": "red", "alarma": "red"}

st.set_page_config(page_title="Consola - Campus Telematico", layout="wide")


def get(ruta, **params):
    try:
        r = requests.get(API + ruta, params=params, timeout=3)
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)


def post(ruta, cuerpo=None):
    try:
        r = requests.post(API + ruta, json=cuerpo, timeout=3)
        return r.status_code, r.json()
    except requests.RequestException as e:
        return None, {"detail": str(e)}


def mandar(accion, **parametros):
    codigo, r = post("/comandos", {"accion": accion, "parametros": parametros})
    if codigo == 202:
        st.session_state.ultimo_cmd = r["id"]
    else:
        st.session_state.error_cmd = "{}: {}".format(codigo, r.get("detail"))


if "ventilador" not in st.session_state:
    st.session_state.ventilador = False

# ------------------------------------------------------------------ lateral
with st.sidebar:
    st.header("Conexion")
    st.caption("API: {}".format(API))
    st.caption("Video: {}".format(VIDEO))
    auto = st.toggle("Actualizar cada 3 s", value=False)
    minutos = st.slider("Ventana de la grafica (min)", 5, 120, 30)

salud, err = get("/salud")
if err:
    st.error("No se alcanza la API en {}.\n\n{}".format(API, err))
    st.info("Verifique: uvicorn api:app --port 8080 en la carpeta practica07.")
    st.stop()

# ----------------------------------------------------------------- cabecera
st.title("Consola de operacion")
c1, c2, c3 = st.columns(3)
c1.metric("Contrato", salud["contrato"])
c2.metric("Lecturas guardadas", salud["lecturas"])
c3.markdown("**Broker:** " + (":green[conectado]" if salud["broker"]
                              else ":red[sin conexion: los comandos no salen]"))

# -------------------------------------------------------------------- nodos
st.subheader("Nodos detectores")
nodos, _ = get("/nodos")
if not nodos:
    st.info("Aun no hay telemetria. Estan corriendo el puente y la ingesta?")
else:
    columnas = st.columns(max(len(nodos), 1))
    for col, n in zip(columnas, nodos):
        col.metric(n["nodo"], "{:.1f} C".format(n["temperatura_c"] or 0),
                   "{:+.2f} C/min".format(n["dtemp_c_min"] or 0),
                   delta_color="inverse")
        col.markdown(":{}[{}]".format(COLOR.get(n["estado"], "gray"),
                                      n["estado"].upper()))
        col.caption("ultima lectura: {}".format(n["ts"][11:19]))

# ------------------------------------------------------------------ alertas
st.subheader("Alertas pendientes")
alertas, _ = get("/alertas", pendientes=True)
if not alertas:
    st.success("Sin alertas pendientes.")
else:
    for a in alertas:
        c1, c2 = st.columns([5, 1])
        c1.markdown(":{}[**{}**] {} - {} - {}".format(
            "red" if a["severidad"] != "baja" else "orange",
            a["severidad"].upper(), a["nodo"], a["transicion"], a["ts"][11:19]))
        if c2.button("Atender", key="al{}".format(a["id"])):
            post("/alertas/{}/atender".format(a["id"]))
            st.rerun()

# ------------------------------------------------------------------ grafica
if nodos:
    nodo = st.selectbox("Serie del nodo", [n["nodo"] for n in nodos])
    datos, _ = get("/telemetria/{}".format(nodo), minutos=minutos)
    if datos:
        df = pd.DataFrame(datos)
        df["ts"] = pd.to_datetime(df["ts"])
        g1, g2 = st.columns(2)
        g1.line_chart(df.set_index("ts")[["temperatura_c"]])
        g2.line_chart(df.set_index("ts")[["dtemp_c_min"]])

# ---------------------------------------------------------- video y control
st.subheader("Robot")
v, c = st.columns([3, 2])
v.markdown('<img src="{}" style="width:100%">'.format(VIDEO),
           unsafe_allow_html=True)
v.caption("Si no aparece el video: esta la PC en la red del robot y corre "
          "servidor_video.py en la Pi?")

with c:
    pan = st.slider("Pan (grados)", -90, 90, 0, 5)
    tilt = st.slider("Tilt (grados)", -45, 45, 0, 5)
    b1, b2 = st.columns(2)
    if b1.button("Apuntar", use_container_width=True):
        mandar("apuntar", pan_grados=pan, tilt_grados=tilt)
    if b2.button("Centrar", use_container_width=True):
        mandar("centrar")

    encender = st.toggle("Ventilador (hombre muerto)",
                         value=st.session_state.ventilador)
    if encender != st.session_state.ventilador:
        st.session_state.ventilador = encender
        if not encender:
            mandar("ventilador", encendido=False)
    if st.session_state.ventilador:
        mandar("ventilador", encendido=True)       # reenvio en cada ciclo
        st.caption(":orange[Reenviando la orden cada segundo. Si la consola "
                   "se detiene, el robot apaga el ventilador en 2 s.]")

    if st.button("PARAR", type="primary", use_container_width=True):
        st.session_state.ventilador = False
        mandar("parar")

    if "error_cmd" in st.session_state:
        st.error(st.session_state.pop("error_cmd"))
    if "ultimo_cmd" in st.session_state:
        time.sleep(0.3)
        r, _ = get("/comandos/{}".format(st.session_state.ultimo_cmd))
        if r and r.get("resultado"):
            st.caption("Ultimo comando: {} en {:.0f} ms".format(
                r["resultado"], r["latencia_ms"] or 0))
        else:
            st.caption("Ultimo comando: sin respuesta aun")

# --------------------------------------------------- actualizacion periodica
if st.session_state.ventilador:
    time.sleep(1.0)            # el reenvio del hombre muerto manda el ritmo
    st.rerun()
elif auto:
    time.sleep(3.0)
    st.rerun()
