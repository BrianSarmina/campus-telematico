"""El aire del banco de pruebas: decide el destino de cada intento de radio.

Los nodos y el concentrador del banco usan mpy/nrf24l01.py, que en lugar de
transmitir manda cada intento a este proceso por UDP. Aqui se decide:

  COLISION       otro intento en el mismo canal empezo a menos de
                 T_AIRE + T_CONMUTACION + T_ACUSE (1.29 ms): se pierden los dos
                 (supuestos S1-S3 de practica09/medio.py).
  INTERFERENCIA  --perdida p: cada trama se pierde con probabilidad p,
                 independiente. --ocupacion d --rafaga s: rafagas como en
                 medio.py (supuesto S6), en tiempo real.
  ACUSE          --perdida-acuse q: el acuse se pierde con probabilidad q.
                 Sirve para provocar duplicados y probar el concentrador.
  ENTREGA        una sola vez por llamada a send() (filtro PID del radio),
                 a los receptores del mismo canal y direccion.

Lo arranca correr.py; tambien se puede usar solo:
    python aire.py --puerto 47000 --perdida 0.2
"""
import argparse
import json
import os
import random
import signal
import socket
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "practica09"))
import medio  # noqa: E402

SEMI_VENTANA = medio.T_AIRE + medio.T_CONMUTACION + medio.T_ACUSE
GUARDA = 0.003      # margen para que lleguen los intentos que se traslapan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=47000)
    ap.add_argument("--perdida", type=float, default=0.0)
    ap.add_argument("--perdida-acuse", type=float, default=0.0)
    ap.add_argument("--ocupacion", type=float, default=0.0)
    ap.add_argument("--rafaga", type=float, default=0.002)
    ap.add_argument("--sin-colisiones", action="store_true")
    ap.add_argument("--semilla", type=int, default=1)
    a = ap.parse_args()

    rng = random.Random(a.semilla)
    t_base = time.perf_counter()
    interf = medio.Interferencia(a.ocupacion, a.rafaga, 7 * 24 * 3600,
                                 random.Random(a.semilla + 1))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", a.puerto))
    sock.settimeout(0.0005)

    oyentes = {}          # puerto -> (canal, direccion)
    historia = []         # (t, canal, puerto_tx) de intentos recientes
    pendientes = []       # (t_decision, mensaje)
    entregados = set()    # (puerto_tx, envio)
    est = {"intentos": 0, "colisiones": 0, "interferencia": 0,
           "sin_receptor": 0, "acuses_perdidos": 0, "entregas": 0}
    fin = {"ya": False}

    def resumen(*_):
        print(json.dumps({"evento": "aire_resumen", **est}), flush=True)
        if _:
            fin["ya"] = True

    signal.signal(signal.SIGTERM, resumen)
    signal.signal(signal.SIGINT, resumen)
    print(json.dumps({"evento": "aire_listo", "puerto": a.puerto,
                      "perdida": a.perdida, "perdida_acuse": a.perdida_acuse,
                      "ocupacion": a.ocupacion, "rafaga_s": a.rafaga}),
          flush=True)
    ultimo_resumen = time.perf_counter()

    while not fin["ya"]:
        try:
            datos, _ = sock.recvfrom(8192)
            m = json.loads(datos.decode())
            tipo = m.get("tipo")
            if tipo == "tx":
                historia.append((m["t"], m["canal"], m["puerto"]))
                pendientes.append((m["t"] + SEMI_VENTANA + GUARDA, m))
            elif tipo == "rx":
                oyentes[m["puerto"]] = (m["canal"], m["dir"])
            elif tipo == "rx_fin":
                oyentes.pop(m["puerto"], None)
        except socket.timeout:
            pass
        except (OSError, ValueError, KeyError):
            continue

        ahora = time.perf_counter()
        listos = [p for p in pendientes if p[0] <= ahora]
        if not listos:
            if ahora - ultimo_resumen > 10:
                resumen()
                ultimo_resumen = ahora
            continue
        pendientes = [p for p in pendientes if p[0] > ahora]
        historia = [h for h in historia if h[0] > ahora - 0.05]

        for _, m in sorted(listos, key=lambda p: p[0]):
            est["intentos"] += 1
            t, canal, ptx = m["t"], m["canal"], m["puerto"]
            ok = True
            if not a.sin_colisiones and any(
                    c == canal and p != ptx and abs(th - t) < SEMI_VENTANA
                    for (th, c, p) in historia):
                est["colisiones"] += 1
                ok = False
            rel = t - t_base
            if ok and (rng.random() < a.perdida or interf.traslapa(
                    rel, rel + medio.T_AIRE)):
                est["interferencia"] += 1
                ok = False
            receptores = [p for p, (c, d) in oyentes.items()
                          if c == canal and d == m["dir"]]
            if ok and not receptores:
                est["sin_receptor"] += 1
                ok = False
            if ok:
                clave = (ptx, m["envio"])
                if clave not in entregados:
                    entregados.add(clave)
                    est["entregas"] += 1
                    aviso = json.dumps({"tipo": "trama",
                                        "carga": m["carga"]}).encode()
                    for p in receptores:
                        sock.sendto(aviso, ("127.0.0.1", p))
                a_ini = rel + medio.T_AIRE + medio.T_CONMUTACION
                if rng.random() < a.perdida_acuse or interf.traslapa(
                        a_ini, a_ini + medio.T_ACUSE):
                    est["acuses_perdidos"] += 1
                    ok = False
            res = json.dumps({"tipo": "res", "ok": ok, "envio": m["envio"],
                              "intento": m["intento"]}).encode()
            sock.sendto(res, ("127.0.0.1", ptx))
    sock.close()


if __name__ == "__main__":
    main()
