"""Pruebas del Modulo 3. Se ejecutan sin hardware.

    pytest pruebas_modulo3.py -v              # rapidas (unos segundos)
    pytest pruebas_modulo3.py -v -m banco     # banco de pruebas (~2 min)

Cada nombre de prueba enuncia una propiedad que el material afirma. Si una
falla, el manual dice algo que el codigo ya no hace.
"""
import os
import py_compile
import re
import socket
import subprocess
import sys
import types

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
# El Modulo 3 se apoya en el firmware del Modulo 1. Por omision lo busca en
# el mismo repositorio; CAMPUS_MODULO1 permite indicar otra ruta.
M1 = os.environ.get("CAMPUS_MODULO1", os.path.normpath(
    os.path.join(AQUI, "..", "..", "Modulo_1", "codigo", "practica04")))
requiere_m1 = pytest.mark.skipif(
    not os.path.isdir(M1),
    reason="no se encontro el Modulo 1 en {} (CAMPUS_MODULO1)".format(M1))
sys.path.insert(0, os.path.join(AQUI, "practica09"))
sys.path.insert(0, os.path.join(AQUI, "practica10"))

import medio  # noqa: E402


# =================================================================
#  1. Modelo del medio
# =================================================================

def test_trama_ocupa_868_us_y_la_ventana_vulnerable_2_58_ms():
    assert round(medio.T_AIRE * 1e6) == 868
    assert round(medio.T_ACUSE * 1e6) == 292
    assert round(medio.VENTANA_VULNERABLE * 1e5) == 258


def test_299_tramas_sin_perdida_demuestran_99_por_ciento():
    assert medio.tramas_para_demostrar(0.99) == 299
    bajo, alto = medio.wilson(299, 299)
    assert bajo >= 0.99 - 0.003 and alto > 0.9999


def test_wilson_no_colapsa_sin_perdidas():
    bajo, alto = medio.wilson(50, 50)
    assert bajo < 0.95 and alto > 0.9999


def test_un_nodo_sin_interferencia_no_pierde():
    r = medio.simular(1, medio.POLITICA_V1, 120, semilla=1)
    e, g = r.entrega()
    assert g > 20 and e == g


def test_canal_ocupado_al_100_no_entrega_nada():
    r = medio.simular(1, medio.POLITICA_V3, 60, semilla=1, ocupacion_wifi=1.0)
    e, g = r.entrega()
    assert g > 5 and e == 0


def test_simulacion_coincide_con_formula_del_primer_intento():
    fallos, total = 0, 0
    for s in range(6):
        r = medio.simular(50, medio.POLITICA_V3, 200, semilla=40 + s)
        a, b = r.primer_intento()
        fallos += b - a
        total += b
    teo = medio.p_colision_periodica(50, 5.0 + medio.T_PROCESO)
    assert abs(fallos / total - teo) < 0.6 * teo


def test_v1_tras_apagon_pierde_y_v3_no():
    kw = dict(dispersion_arranque_s=0.001, sigma_proceso_s=0.0002)
    e1, g1 = medio.simular(3, medio.POLITICA_V1, 120, semilla=7, **kw).entrega()
    e3, g3 = medio.simular(3, medio.POLITICA_V3, 120, semilla=7, **kw).entrega()
    assert e1 / g1 < 0.9 and e3 == g3


# =================================================================
#  2. El firmware y el modelo dicen lo mismo
# =================================================================

def _constantes(ruta, nombres):
    texto = open(ruta).read()
    valores = {}
    for n in nombres:
        m = re.search(r"^{}\s*=\s*([0-9.]+)".format(n), texto, re.M)
        assert m, "{} no esta en {}".format(n, ruta)
        valores[n] = float(m.group(1))
    return valores


def test_constantes_del_firmware_v3_coinciden_con_el_modelo():
    c = _constantes(os.path.join(AQUI, "firmware", "nodo_detector", "main.py"),
                    ["ARC", "ARD_IDX_MIN", "ARD_IDX_MAX", "SW_RUTINA",
                     "SW_PRIORIDAD", "ESPERA_SW_BASE_MS", "FLUCTUACION"])
    p = medio.POLITICA_V3
    assert c["ARC"] == p["arc"]
    assert (c["ARD_IDX_MIN"], c["ARD_IDX_MAX"]) == p["ard_idx"]
    assert c["SW_RUTINA"] == p["sw_rutina"]
    assert c["SW_PRIORIDAD"] == p["sw_prioridad"]
    assert c["ESPERA_SW_BASE_MS"] / 1000 == p["espera_sw_base_s"]
    assert c["FLUCTUACION"] == p["fluctuacion"]


# =================================================================
#  3. Contabilidad del concentrador
# =================================================================

def _cargar_concentrador(directorio):
    """Carga main.py del concentrador SIN ejecutar main()."""
    sys.path[:0] = [os.path.join(AQUI, "banco", "mpy"), M1]
    fuente = open(os.path.join(directorio, "main.py")).read()
    fuente = re.sub(r"\nmain\(\)\s*$", "\n", fuente)
    mod = types.ModuleType("concentrador_prueba")
    exec(compile(fuente, "main.py", "exec"), mod.__dict__)
    return mod


def _msg(seq, nodo="d01"):
    return {"nodo": nodo, "secuencia": seq, "diag": {}}


@requiere_m1
def test_concentrador_v3_descarta_duplicados_y_cuenta_huecos():
    c = _cargar_concentrador(os.path.join(AQUI, "firmware", "concentrador"))
    assert c.contabilizar(_msg(0)) is not None
    assert c.contabilizar(_msg(1)) is not None
    assert c.contabilizar(_msg(1)) is None             # duplicado
    m = c.contabilizar(_msg(4))                        # se perdieron 2 y 3
    assert m["diag"]["perdidos"] == 2
    assert m["diag"]["duplicados"] == 1
    assert m["diag"]["secuencia"] == 4


@requiere_m1
def test_concentrador_v3_no_cuenta_un_reinicio_como_perdida():
    c = _cargar_concentrador(os.path.join(AQUI, "firmware", "concentrador"))
    for s in range(10):
        c.contabilizar(_msg(s))
    m = c.contabilizar(_msg(0))                        # el nodo se reinicio
    assert m["diag"]["perdidos"] == 0
    assert c.reinicios["d01"] == 1


@requiere_m1
def test_concentrador_m1_contaba_el_reinicio_como_65526_perdidas():
    c = _cargar_concentrador(os.path.join(M1, "concentrador"))
    for s in range(10):
        c.contabilizar(_msg(s))
    m = c.contabilizar(_msg(0))
    assert m["diag"]["perdidos"] == 65526              # el error del Modulo 1


@requiere_m1
def test_secuencia_cruza_el_cero_sin_contarse_como_reinicio():
    c = _cargar_concentrador(os.path.join(AQUI, "firmware", "concentrador"))
    c.contabilizar(_msg(65534))
    c.contabilizar(_msg(65535))
    m = c.contabilizar(_msg(0))
    assert m["diag"]["perdidos"] == 0 and c.reinicios.get("d01", 0) == 0


# =================================================================
#  4. Instrumentos
# =================================================================

LINEA = ("[0012]  23.4 C  d=+0.02 C/min  humo= 318  flama=  95 ( 0/50)  "
         "normal     T0H0F0  ACK int=3 sw=1 tx_us=42100 ciclo_us=1003000")


def test_medir_enlace_entiende_la_bitacora_del_firmware():
    import medir_enlace
    r = medir_enlace.parsear(LINEA, 100.0, 115200)
    assert (r["seq"], r["estado"], r["ack"], r["int"], r["sw"]) == \
        (12, "normal", True, 3, 1)
    # t_gen descuenta la transmision y el paso por el puerto serie
    assert 99.94 < r["t_gen"] < 99.96


def test_formato_de_bitacora_del_firmware_no_cambio():
    texto = open(os.path.join(AQUI, "firmware", "nodo_detector",
                              "main.py")).read()
    assert '{} int={} sw={} tx_us={}"' in texto
    assert '" ciclo_us={}"' in texto


def test_visor_ubica_el_wifi_del_canal_11_sobre_el_nrf_70():
    import ver_espectro
    fr, n = ver_espectro.acumular(
        ver_espectro.barridos_simulados(11, 0.4, 3))
    assert n == 3
    assert ver_espectro.promedio(fr, 69, 71) > 0.2
    assert ver_espectro.promedio(fr, 75, 77) < 0.1


# =================================================================
#  5. Higiene del codigo
# =================================================================

def _archivos_py():
    for raiz, _, archivos in os.walk(AQUI):
        if "corridas" in raiz or "__pycache__" in raiz:
            continue
        for a in archivos:
            if a.endswith(".py"):
                yield os.path.join(raiz, a)


def test_todo_el_codigo_es_ascii_y_compila():
    for ruta in _archivos_py():
        datos = open(ruta, "rb").read()
        assert all(b < 128 for b in datos), "no ASCII: " + ruta
        py_compile.compile(ruta, doraise=True)


# =================================================================
#  6. Banco de pruebas: firmware real, varios nodos (lento)
# =================================================================

def _correr(args, tmp_path):
    salida = str(tmp_path / "banco")
    cmd = [sys.executable, os.path.join(AQUI, "banco", "correr.py"),
           "--salida", salida, "--puerto-aire", "47100"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.stdout, salida


@pytest.mark.banco
@requiere_m1
def test_banco_tres_nodos_v3_entregan_todo(tmp_path):
    out, _ = _correr(["--nodos", "3", "--duracion", "25",
                      "--periodo-fijo", "1.0"], tmp_path)
    filas = re.findall(r"^\s+(d0\d)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
                       out, re.M)
    assert len(filas) == 3, out
    for nodo, emit, ack, uno, sw, conc in filas:
        assert int(emit) > 10 and int(conc) == int(emit), out


@pytest.mark.banco
@requiere_m1
def test_banco_reinicio_y_acuses_perdidos(tmp_path):
    out, _ = _correr(["--nodos", "2", "--duracion", "30", "--periodo-fijo",
                      "1.0", "--perdida-acuse", "0.5", "--reiniciar", "2@14"],
                     tmp_path)
    assert "reinicio del nodo d02" in out, out
    for linea in re.findall(r"Concentrador, d0\d: .*", out):
        assert "perdidos=0" in linea, out


@pytest.mark.banco
@requiere_m1
def test_banco_flama_por_d0_activa_el_canal(tmp_path):
    out, salida = _correr(["--nodos", "1", "--duracion", "32",
                           "--escenario", "flama", "--inicio", "6"], tmp_path)
    log = open(os.path.join(salida, "nodo_1.log")).read()
    assert "flama=1200" in log, log
    assert "T0H0F1" in log, log


def _broker_local():
    try:
        socket.create_connection(("localhost", 1883), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.banco
@requiere_m1
def test_banco_secadora_la_latencia_se_descompone(tmp_path):
    if not _broker_local():
        pytest.skip("hace falta un broker en localhost:1883")
    salida = str(tmp_path / "banco")
    banco = subprocess.Popen(
        [sys.executable, os.path.join(AQUI, "banco", "correr.py"),
         "--nodos", "1", "--puente", "--escenario", "secadora",
         "--inicio", "25", "--duracion", "95", "--salida", salida,
         "--puerto-aire", "47100"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        r = subprocess.run(
            [sys.executable,
             os.path.join(AQUI, "practica10", "descomponer_alarma.py"),
             "--nodo-log", os.path.join(salida, "nodo_1.log"),
             "--marca-banco", "--repeticiones", "1", "--csv", "no"],
            capture_output=True, text=True, timeout=150)
    finally:
        banco.wait(timeout=150)
    out = r.stdout
    m = re.search(r"Persistencia\s+([\d.]+)s", out)
    e = re.search(r"Enlace y plataforma\s+([\d.]+)s", out)
    assert m and e, out
    # Con periodo de 5 s, la persistencia de 6 s cuesta dos periodos
    assert 9.5 < float(m.group(1)) < 12.0, out
    assert float(e.group(1)) < 1.0, out
