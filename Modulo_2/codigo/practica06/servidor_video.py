"""Servidor de video del robot - Modulo 2, Practica 6.

Se ejecuta EN LA RASPBERRY PI. Captura de la camara USB y sirve un flujo MJPEG
por HTTP, mas un punto de medicion de latencia.

POR QUE MJPEG Y NO H.264

MJPEG envia cada cuadro comprimido de forma independiente. Es ineficiente en
ancho de banda (unas 5 veces peor que H.264) pero tiene dos propiedades que
importan aqui:

  1. LATENCIA BAJA Y PREDECIBLE. H.264 agrupa cuadros y necesita un buffer;
     esa es precisamente la latencia que RNF-02 no tolera.
  2. NO HAY DEPENDENCIA ENTRE CUADROS. Un cuadro perdido se nota una vez y se
     recupera solo. En H.264, perder un cuadro clave arruina el siguiente
     grupo entero.

Es el mismo criterio de todo el proyecto: el video es trafico de tiempo real,
tolera perdida pero no retardo. Se paga ancho de banda para comprar latencia.

MEDICION DE LATENCIA
El servidor estampa cada cuadro con su numero y el instante de captura en el
reloj monotono de la Pi. El programa medir_video.py en la computadora lee ese
sello y calcula el retardo. No se comparan relojes de maquinas distintas: se
mide el intervalo entre la captura y la llegada usando una sola referencia.

Puntos servidos:
    http://10.42.0.1:8000/          pagina de prueba
    http://10.42.0.1:8000/video     flujo MJPEG
    http://10.42.0.1:8000/metricas  JSON con fps, tamano y sello del cuadro

Uso:
    python servidor_video.py
    python servidor_video.py --ancho 640 --alto 480 --fps 15 --calidad 70
    python servidor_video.py --simular        # sin camara, patron generado
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

estado = {
    "cuadro": None,        # bytes JPEG
    "numero": 0,
    "t_captura": 0.0,      # reloj monotono de la Pi
    "fps_real": 0.0,
    "bytes_cuadro": 0,
    "clientes": 0,
}
cerrojo = threading.Lock()
CONFIG = {}


def capturar():
    """Hilo productor: captura, comprime y publica el ultimo cuadro.

    Se guarda SOLO el ultimo cuadro, no una cola. Si un cliente va lento,
    pierde cuadros intermedios en lugar de acumular retardo. Para video de
    teleoperacion es lo correcto: un cuadro viejo no sirve de nada.
    """
    if CONFIG["simular"]:
        cam = None
    else:
        cam = cv2.VideoCapture(CONFIG["dispositivo"])
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG["ancho"])
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG["alto"])
        cam.set(cv2.CAP_PROP_FPS, CONFIG["fps"])
        # Buffer de un cuadro: sin esto OpenCV acumula y el video llega
        # con segundos de retraso aunque el enlace este vacio.
        cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cam.isOpened():
            print("No se pudo abrir la camara {}.".format(CONFIG["dispositivo"]))
            print("Verifique con: ls /dev/video*   y   v4l2-ctl --list-devices")
            return

    periodo = 1.0 / CONFIG["fps"]
    parametros = [int(cv2.IMWRITE_JPEG_QUALITY), CONFIG["calidad"]]
    n = 0
    t_ventana = time.monotonic()
    n_ventana = 0

    while True:
        t0 = time.monotonic()

        if CONFIG["simular"]:
            img = np.zeros((CONFIG["alto"], CONFIG["ancho"], 3), dtype=np.uint8)
            x = int((n * 7) % max(CONFIG["ancho"] - 80, 1))
            img[:, :] = (30, 30, 40)
            img[CONFIG["alto"] // 2 - 40:CONFIG["alto"] // 2 + 40,
                x:x + 80] = (0, 180, 220)
        else:
            ok, img = cam.read()
            if not ok:
                time.sleep(0.05)
                continue

        # Sello visible en la imagen: permite comprobar la latencia a ojo
        # apuntando la camara a la propia pantalla, sin instrumentacion.
        cv2.putText(img, "#{}  {:.1f} fps".format(n, estado["fps_real"]),
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        ok, jpg = cv2.imencode(".jpg", img, parametros)
        if not ok:
            continue

        n += 1
        n_ventana += 1
        ahora = time.monotonic()
        if ahora - t_ventana >= 1.0:
            estado["fps_real"] = n_ventana / (ahora - t_ventana)
            t_ventana, n_ventana = ahora, 0

        with cerrojo:
            estado["cuadro"] = jpg.tobytes()
            estado["numero"] = n
            estado["t_captura"] = ahora
            estado["bytes_cuadro"] = len(jpg)

        dormir = periodo - (time.monotonic() - t0)
        if dormir > 0:
            time.sleep(dormir)


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass          # sin registro por peticion: satura la consola

    def do_GET(self):
        if self.path.startswith("/video"):
            self.servir_video()
        elif self.path.startswith("/metricas"):
            self.servir_metricas()
        elif self.path in ("/", "/index.html"):
            self.servir_pagina()
        else:
            self.send_error(404)

    def servir_metricas(self):
        with cerrojo:
            d = {
                "numero": estado["numero"],
                "t_captura": estado["t_captura"],
                "t_servidor": time.monotonic(),
                "fps_real": round(estado["fps_real"], 2),
                "bytes_cuadro": estado["bytes_cuadro"],
                "clientes": estado["clientes"],
            }
        cuerpo = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def servir_pagina(self):
        html = ("<!doctype html><meta charset=utf-8>"
                "<title>Robot</title>"
                "<body style='background:#111;color:#eee;font-family:sans-serif'>"
                "<h3>Camara del robot</h3>"
                "<img src='/video' style='max-width:100%'>"
                "</body>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def servir_video(self):
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=cuadro")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with cerrojo:
            estado["clientes"] += 1
        ultimo = -1
        try:
            while True:
                with cerrojo:
                    jpg = estado["cuadro"]
                    n = estado["numero"]
                    t_cap = estado["t_captura"]
                if jpg is None or n == ultimo:
                    time.sleep(0.005)
                    continue
                ultimo = n
                cab = ("--cuadro\r\n"
                       "Content-Type: image/jpeg\r\n"
                       "Content-Length: {}\r\n"
                       "X-Cuadro: {}\r\n"
                       "X-Captura: {:.6f}\r\n\r\n").format(len(jpg), n, t_cap)
                self.wfile.write(cab.encode())
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with cerrojo:
                estado["clientes"] -= 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--dispositivo", type=int, default=0)
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--calidad", type=int, default=70,
                    help="Calidad JPEG 1-100. Menor calidad, menos bytes")
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    if cv2 is None:
        raise SystemExit(
            "Falta OpenCV. En la Pi:\n"
            "    sudo apt install python3-opencv\n"
            "En la computadora, para probar sin camara:\n"
            "    pip install opencv-python-headless numpy")

    CONFIG.update(vars(a))

    hilo = threading.Thread(target=capturar, daemon=True)
    hilo.start()
    time.sleep(1.0)

    servidor = ThreadingHTTPServer(("0.0.0.0", a.puerto), Manejador)
    print("=" * 62)
    print("  SERVIDOR DE VIDEO DEL ROBOT")
    print("=" * 62)
    print("  Resolucion : {}x{} a {:.0f} fps".format(a.ancho, a.alto, a.fps))
    print("  Calidad    : {} (JPEG)".format(a.calidad))
    print("  Modo       : {}".format("simulacion" if a.simular else "camara"))
    print()
    print("  Flujo      : http://10.42.0.1:{}/video".format(a.puerto))
    print("  Metricas   : http://10.42.0.1:{}/metricas".format(a.puerto))
    print("=" * 62)
    print("  Ctrl-C para detener.\n")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
        servidor.shutdown()


if __name__ == "__main__":
    main()
