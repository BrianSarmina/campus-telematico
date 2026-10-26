"""Banco de pruebas del enlace RF: varios nodos con su firmware REAL en la PC.

Arranca el aire simulado, el concentrador y N nodos detectores, cada uno en
su proceso y con el mismo main.py que se copia al ESP32. Opcionalmente
conecta el puente serie del Modulo 1 por una terminal virtual (pty), de modo
que la telemetria llega al broker igual que con el hardware.

Existe porque el grupo tiene UN detector: con el banco, el firmware v3 y el
concentrador v3 se ejercitan con 3 nodos, con perdidas, con reinicios y con
arranques simultaneos. NO sustituye al radio: la temporizacion es aproximada
y la interferencia es un modelo. Verifica logica, no fisica.

Corre en Linux, macOS o WSL. Con --puente necesita una terminal virtual
(pty), que Windows no tiene: en Windows nativo, use el banco sin --puente.

Ejemplos:
    python correr.py --nodos 3 --duracion 60
    python correr.py --nodos 3 --perdida 0.3 --perdida-acuse 0.6 --duracion 90
    python correr.py --nodos 1 --reiniciar 1@40 --duracion 70
    python correr.py --nodos 3 --puente --broker localhost --duracion 120
    python correr.py --nodos 3 --concentrador m1 --reiniciar 2@30   # el error
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
M1_DEF = os.environ.get("CAMPUS_MODULO1", os.path.normpath(
    os.path.join(CODIGO, "..", "..", "Modulo_1", "codigo", "practica04")))

LINEA_NODO = re.compile(
    r"^\[(\d+)\].*?\s(normal|vigilancia|prealarma|alarma)\s+T\dH\dF\d\s+"
    r"(ACK|SIN ACK) int=(\d+) sw=(\d+) tx_us=(\d+) ciclo_us=(\d+)")


def lanzar(cmd, log, env=None, **kw):
    f = open(log, "w")
    return subprocess.Popen(cmd, stdout=kw.pop("stdout", f),
                            stderr=subprocess.STDOUT, env=env, **kw), f


def main():
    ap = argparse.ArgumentParser(description="Banco de pruebas del enlace RF")
    ap.add_argument("--nodos", type=int, default=3)
    ap.add_argument("--duracion", type=float, default=60.0)
    ap.add_argument("--politica", default="v3", choices=["v1", "v3"])
    ap.add_argument("--firmware-nodo", default="v3", choices=["v3", "m1"],
                    help="m1: el main.py original del Modulo 1")
    ap.add_argument("--concentrador", default="v3", choices=["v3", "m1"],
                    help="m1: el main.py original del Modulo 1")
    ap.add_argument("--periodo-fijo", type=float, default=None)
    ap.add_argument("--periodo", type=float, default=5)
    ap.add_argument("--precalentado", type=float, default=5)
    ap.add_argument("--perdida", type=float, default=0.0)
    ap.add_argument("--perdida-acuse", type=float, default=0.0)
    ap.add_argument("--ocupacion", type=float, default=0.0)
    ap.add_argument("--rafaga", type=float, default=0.002)
    ap.add_argument("--escenario", default="normal",
                    help="escenario del nodo 1: normal|secadora|flama|incendio")
    ap.add_argument("--inicio", type=float, default=20.0,
                    help="segundo en que empieza el estimulo del nodo 1")
    ap.add_argument("--arranque-sincronizado", action="store_true")
    ap.add_argument("--reiniciar", action="append", default=[],
                    help="NODO@SEGUNDO: mata y rearranca ese nodo")
    ap.add_argument("--puente", action="store_true")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto-aire", type=int, default=47000)
    ap.add_argument("--modulo1", default=M1_DEF)
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()

    salida = a.salida or os.path.join(
        AQUI, "corridas", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(salida, exist_ok=True)
    py = [sys.executable, "-u"]
    ejecutar = os.path.join(AQUI, "ejecutar.py")
    m1_nodo = os.path.join(a.modulo1, "nodo_detector")
    m1_conc = os.path.join(a.modulo1, "concentrador")
    env = dict(os.environ, BANCO_AIRE="127.0.0.1:{}".format(a.puerto_aire))
    procesos = []           # (nombre, Popen, archivo)

    # ----------------------------------------------------------- aire
    p, f = lanzar(py + [os.path.join(AQUI, "aire.py"),
                        "--puerto", str(a.puerto_aire),
                        "--perdida", str(a.perdida),
                        "--perdida-acuse", str(a.perdida_acuse),
                        "--ocupacion", str(a.ocupacion),
                        "--rafaga", str(a.rafaga)],
                  os.path.join(salida, "aire.log"), env)
    procesos.append(("aire", p, f))
    time.sleep(0.5)

    # ----------------------------------------------------------- concentrador
    fw_conc = (os.path.join(CODIGO, "firmware", "concentrador")
               if a.concentrador == "v3" else m1_conc)
    conc = subprocess.Popen(
        py + [ejecutar, "--firmware", fw_conc, "--extra", a.modulo1],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    log_conc = open(os.path.join(salida, "concentrador.log"), "w")
    maestro = esclavo = None
    if a.puente:
        import pty   # solo Linux, macOS o WSL
        import tty
        maestro, esclavo = pty.openpty()
        tty.setraw(esclavo)
    por_nodo = {}
    eventos = []

    def leer_concentrador():
        for crudo in conc.stdout:
            log_conc.write(crudo.decode("utf-8", "replace"))
            log_conc.flush()
            if maestro is not None:
                try:
                    os.write(maestro, crudo.replace(b"\n", b"\r\n"))
                except OSError:
                    pass
            try:
                m = json.loads(crudo.decode())
            except ValueError:
                continue
            if "evento" in m:
                eventos.append(m)
            elif "nodo" in m:
                por_nodo.setdefault(m["nodo"], []).append(m)

    hilo = threading.Thread(target=leer_concentrador, daemon=True)
    hilo.start()
    procesos.append(("concentrador", conc, log_conc))
    time.sleep(1.0)

    # ----------------------------------------------------------- puente
    if a.puente:
        p, f = lanzar(py + [os.path.join(a.modulo1, "puente", "puente_serie.py"),
                            "--puerto", os.ttyname(esclavo),
                            "--broker", a.broker],
                      os.path.join(salida, "puente.log"), env)
        procesos.append(("puente", p, f))
        time.sleep(3.0)

    # ----------------------------------------------------------- nodos
    fw_nodo = (os.path.join(CODIGO, "firmware", "nodo_detector")
               if a.firmware_nodo == "v3" else m1_nodo)
    t_arr = time.perf_counter() + 2.0 if a.arranque_sincronizado else None

    def lanzar_nodo(i, sufijo=""):
        cfg = {"ID_NODO": i, "POLITICA": a.politica, "PERIODO_S": a.periodo,
               "PRECALENTADO_S": a.precalentado,
               "PERIODO_FIJO_S": a.periodo_fijo}
        e = dict(env, BANCO_SEMILLA=str(i),
                 BANCO_ESCENARIO=a.escenario if i == 1 else "normal",
                 BANCO_INICIO_S=str(a.inicio))
        if t_arr is not None and not sufijo:
            e["BANCO_ARRANQUE"] = repr(t_arr)
        return lanzar(py + [ejecutar, "--firmware", fw_nodo, "--extra", m1_nodo,
                            "--extra", a.modulo1, "--config", json.dumps(cfg)],
                      os.path.join(salida, "nodo_{}{}.log".format(i, sufijo)), e)

    nodos = {}
    for i in range(1, a.nodos + 1):
        nodos[i] = lanzar_nodo(i)
        procesos.append(("nodo_{}".format(i), *nodos[i]))

    reinicios = sorted((float(r.split("@")[1]), int(r.split("@")[0]))
                       for r in a.reiniciar)
    print("Banco en marcha: {} nodos, politica {}, {:.0f} s. Bitacoras en {}".format(
        a.nodos, a.politica, a.duracion, salida), flush=True)
    t0 = time.time()
    try:
        while time.time() - t0 < a.duracion:
            if reinicios and time.time() - t0 >= reinicios[0][0]:
                _, i = reinicios.pop(0)
                viejo, f = nodos[i]
                viejo.terminate()
                viejo.wait()
                nodos[i] = lanzar_nodo(i, "_reinicio")
                procesos.append(("nodo_{}_reinicio".format(i), *nodos[i]))
                print("  t={:.0f} s: nodo {} reiniciado".format(
                    time.time() - t0, i), flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for nombre, p, f in reversed(procesos):
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        for nombre, p, f in procesos:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        time.sleep(0.3)
        for _, _, f in procesos:
            try:
                f.close()
            except Exception:
                pass

    # ----------------------------------------------------------- resumen
    print()
    print("=" * 74)
    print("  RESUMEN DEL BANCO")
    print("=" * 74)
    aire = [json.loads(l) for l in open(os.path.join(salida, "aire.log"))
            if l.startswith("{") and "aire_resumen" in l]
    if aire:
        r = aire[-1]
        print("  Aire: {intentos} intentos, {colisiones} colisiones, "
              "{interferencia} por interferencia, {acuses_perdidos} acuses "
              "perdidos, {entregas} entregas".format(**r))
    print()
    print("  {:<6} {:>8} {:>8} {:>10} {:>10} {:>10} {:>11}".format(
        "Nodo", "Emitidas", "Con ACK", "1er int.", "Con SW", "Al conc.",
        "Entrega"))
    print("  " + "-" * 70)
    for i in range(1, a.nodos + 1):
        lineas = []
        for nombre in sorted(os.listdir(salida)):
            if nombre.startswith("nodo_{}".format(i)) and (
                    nombre == "nodo_{}.log".format(i)
                    or nombre.startswith("nodo_{}_".format(i))):
                lineas += [LINEA_NODO.match(l) for l in
                           open(os.path.join(salida, nombre))]
        ms = [x for x in lineas if x]
        emit = len(ms)
        ack = sum(1 for x in ms if x.group(3) == "ACK")
        uno = sum(1 for x in ms if x.group(3) == "ACK" and x.group(4) == "1")
        sw = sum(1 for x in ms if int(x.group(5)) > 0)
        ident = "d{:02x}".format(i)
        conc_n = len(por_nodo.get(ident, []))
        print("  {:<6} {:>8} {:>8} {:>10} {:>10} {:>10} {:>10.1%}".format(
            ident, emit, ack, uno, sw, conc_n, conc_n / emit if emit else 0))
    latidos = [e for e in eventos if e.get("evento") == "latido"]
    reinic = [e for e in eventos if e.get("evento") == "reinicio_nodo"]
    print()
    for ident, ms in sorted(por_nodo.items()):
        d = ms[-1].get("diag", {})
        print("  Concentrador, {}: recibidos={} perdidos={} duplicados={} "
              "tasa_entrega={}".format(ident, d.get("recibidos"),
                                       d.get("perdidos"), d.get("duplicados", "-"),
                                       d.get("tasa_entrega")))
    if reinic:
        for e in reinic:
            print("  Evento: reinicio del nodo {} (secuencia {} -> {})".format(
                e["nodo"], e["secuencia_previa"], e["secuencia"]))
    if latidos:
        print("  Ultimo latido: {}".format(latidos[-1]))
    print("\n  Bitacoras: {}".format(salida))


if __name__ == "__main__":
    main()
