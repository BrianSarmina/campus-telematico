"""Controlador de actuadores del robot - Modulo 2, Practica 7.

Se ejecuta en la Raspberry Pi. Suscribe comandos por MQTT, mueve el pan-tilt,
enciende el ventilador y responde correlacionando por identificador.

IMPLEMENTA EL CONTRATO DEFINIDO EN LA SEMANA 6
El contrato (contrato/contrato_mensajes.py) se escribio una semana antes que
este programa. Esa separacion es deliberada: es la que demuestra para que
sirve un ICD cuando no hay equipos separados que negociar entre si.

CONEXIONADO (Raspberry Pi 3B, numeracion BCM)

    Servo pan       ->  GPIO18   (PWM por hardware)
    Servo tilt      ->  GPIO13   (PWM por hardware)
    Ventilador      ->  GPIO17   (a traves de transistor o rele)
    Camara USB      ->  cualquier puerto USB

ADVERTENCIA DE ALIMENTACION
    Los servos NO se alimentan de los pines de 5 V de la Pi. Un SG90 pide
    picos de varios cientos de mA al arrancar y la Pi se reinicia. Fuente de
    5 V / 3 A independiente, con la tierra unida a la de la Pi.

COMPORTAMIENTO SEGURO
    Si no llega ningun comando durante PLAZO_SEGURO_S, el robot apaga el
    ventilador y CONSERVA su posicion. No se recentra: un movimiento
    inesperado ante una perdida de enlace es peor que quedarse quieto.

Uso:
    python control_actuadores.py --broker 10.42.0.10
    python control_actuadores.py --broker 10.42.0.10 --simular
"""
import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

sys.path.insert(0, "../contrato")
import contrato_mensajes as ct

PIN_PAN, PIN_TILT, PIN_VENTILADOR = 18, 13, 17


class Actuadores:
    """Abstrae el hardware. En modo simulacion imprime en lugar de mover.

    La abstraccion no es adorno: permite ejecutar y probar todo el lazo de
    control en cualquier computadora, sin la Pi montada. Es el mismo
    principio que el stub, aplicado al otro lado de la interfaz.
    """

    def __init__(self, simular=False):
        self.simular = simular
        self.pan = 0.0
        self.tilt = 0.0
        self.ventilador = False

        if simular:
            print("Modo simulacion: no se toca el hardware.")
            return

        try:
            from gpiozero import AngularServo, OutputDevice
            from gpiozero.pins.pigpio import PiGPIOFactory
        except ImportError:
            sys.exit("Falta gpiozero. En la Pi: sudo apt install python3-gpiozero\n"
                     "O ejecute con --simular para probar sin hardware.")

        # pigpio da PWM por hardware: sin el, los servos tiemblan porque el
        # PWM por software lo interrumpe cualquier otro proceso.
        # Requiere: sudo systemctl enable --now pigpiod
        try:
            fabrica = PiGPIOFactory()
        except OSError:
            print("AVISO: pigpiod no responde. Los servos van a temblar.")
            print("       sudo systemctl enable --now pigpiod")
            fabrica = None

        opciones = {"pin_factory": fabrica} if fabrica else {}
        self.servo_pan = AngularServo(
            PIN_PAN, min_angle=-90, max_angle=90,
            min_pulse_width=0.5 / 1000, max_pulse_width=2.5 / 1000, **opciones)
        self.servo_tilt = AngularServo(
            PIN_TILT, min_angle=-45, max_angle=45,
            min_pulse_width=0.5 / 1000, max_pulse_width=2.5 / 1000, **opciones)
        self.rele = OutputDevice(PIN_VENTILADOR, **opciones)

    def apuntar(self, pan=None, tilt=None):
        if pan is not None:
            self.pan = max(-90.0, min(90.0, float(pan)))
            if not self.simular:
                self.servo_pan.angle = self.pan
        if tilt is not None:
            self.tilt = max(-45.0, min(45.0, float(tilt)))
            if not self.simular:
                self.servo_tilt.angle = self.tilt

    def soplar(self, encendido):
        self.ventilador = bool(encendido)
        if not self.simular:
            self.rele.on() if self.ventilador else self.rele.off()

    def parar(self):
        """Estado seguro: ventilador apagado, posicion conservada."""
        self.soplar(False)

    def posicion(self):
        return {"pan_grados": round(self.pan, 1),
                "tilt_grados": round(self.tilt, 1),
                "ventilador": self.ventilador}


class Robot:
    def __init__(self, cliente, actuadores):
        self.cliente = cliente
        self.act = actuadores
        self.ultimo_comando = time.monotonic()
        self.atendidos = 0
        self.rechazados = 0
        self.vistos = set()      # identificadores ya atendidos
        self.lock = threading.Lock()

    def responder(self, id_cmd, resultado, detalle=""):
        msg = {
            "version": ct.VERSION_CONTRATO,
            "id": id_cmd,
            "ts": datetime.now(timezone.utc).isoformat(),
            "resultado": resultado,
            "posicion": self.act.posicion(),
        }
        if detalle:
            msg["detalle"] = detalle
        self.cliente.publish(ct.TOPICOS["respuesta"], json.dumps(msg),
                             qos=ct.QOS["respuesta"])

    def atender(self, crudo):
        try:
            cmd = json.loads(crudo)
        except json.JSONDecodeError:
            return

        # VALIDACION CONTRA EL CONTRATO, antes de tocar el hardware.
        # Un comando malformado no debe poder mover un actuador.
        errores = ct.validar("comando", cmd)
        if errores:
            self.rechazados += 1
            id_cmd = cmd.get("id", "desconocido")
            print("  RECHAZADO {}: {}".format(id_cmd, errores[0][:60]))
            self.responder(id_cmd, "rechazado", errores[0][:120])
            return

        id_cmd = cmd["id"]

        with self.lock:
            # Idempotencia: un comando reenviado no se ejecuta dos veces.
            # Con QoS 0 el duplicado es raro, pero la consola puede reenviar
            # si no ve respuesta, y repetir un movimiento seria visible.
            if id_cmd in self.vistos:
                self.responder(id_cmd, "ok", "duplicado ignorado")
                return
            self.vistos.add(id_cmd)
            if len(self.vistos) > 500:
                self.vistos = set(list(self.vistos)[-250:])

            self.ultimo_comando = time.monotonic()

        accion = cmd["accion"]
        p = cmd.get("parametros", {})

        if accion == "apuntar":
            self.act.apuntar(p.get("pan_grados"), p.get("tilt_grados"))
        elif accion == "ventilador":
            self.act.soplar(p.get("encendido", False))
        elif accion == "centrar":
            self.act.apuntar(0.0, 0.0)
        elif accion == "parar":
            self.act.parar()

        self.atendidos += 1
        self.responder(id_cmd, "ok")
        print("[{:04d}] {:<11} {}".format(
            self.atendidos, accion, self.act.posicion()))

    def vigilar_enlace(self):
        """Hilo que aplica el estado seguro ante silencio del operador."""
        anunciado = False
        while True:
            time.sleep(0.25)
            with self.lock:
                silencio = time.monotonic() - self.ultimo_comando
            if silencio > ct.PLAZO_SEGURO_S:
                if self.act.ventilador or not anunciado:
                    if self.act.ventilador:
                        print("  ESTADO SEGURO: {:.1f} s sin comandos".format(
                            silencio))
                    self.act.parar()
                    anunciado = True
            else:
                anunciado = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--puerto", type=int, default=1883)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    act = Actuadores(simular=a.simular)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="robot")
    cliente.will_set(ct.TOPICOS["estado"].format(componente="robot"),
                     json.dumps({"estado": "offline", "motivo": "inesperado"}),
                     qos=1, retain=True)
    try:
        cliente.connect(a.broker, a.puerto, keepalive=10)
    except OSError as e:
        sys.exit("No se pudo conectar al broker {}:{} ({}).\n"
                 "Verifique que la Pi alcanza a la computadora: ping {}"
                 .format(a.broker, a.puerto, e, a.broker))

    robot = Robot(cliente, act)
    cliente.on_message = lambda c, u, m: robot.atender(m.payload.decode())
    cliente.subscribe(ct.TOPICOS["comando"], qos=ct.QOS["comando"])
    cliente.publish(ct.TOPICOS["estado"].format(componente="robot"),
                    json.dumps({"estado": "online"}), qos=1, retain=True)

    hilo = threading.Thread(target=robot.vigilar_enlace, daemon=True)
    hilo.start()

    print("Robot escuchando en {}".format(ct.TOPICOS["comando"]))
    print("Estado seguro tras {:.1f} s sin comandos.".format(ct.PLAZO_SEGURO_S))
    print("Ctrl-C para detener.\n")

    try:
        cliente.loop_forever()
    except KeyboardInterrupt:
        print("\n\nComandos atendidos : {}".format(robot.atendidos))
        print("Comandos rechazados: {}".format(robot.rechazados))
        act.parar()
        cliente.publish(ct.TOPICOS["estado"].format(componente="robot"),
                        json.dumps({"estado": "offline", "motivo": "normal"}),
                        qos=1, retain=True)
        time.sleep(0.5)
        cliente.disconnect()


if __name__ == "__main__":
    main()
