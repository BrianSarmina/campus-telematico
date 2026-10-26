# Módulo 3 — Cierre del proyecto (versión 3.0, Prácticas 9 y 10)

Material de las semanas 13 a 16 de Telemática. Es el último módulo: termina
el proyecto integrador y cubre de las Unidades 4 y 5 solo lo que el proyecto
necesita. Este LEEME cubre las Prácticas 9 y 10; las 11–12 y el cierre se
agregan después.

| Semana | Práctica | Tema |
|---|---|---|
| 13 | P9 | Espectro compartido: colisiones y coexistencia Wi-Fi/nRF24 |
| 14 | P10 | Prioridad de la alarma en un medio ocupado |
| 15 | P11+P12 | No perder alarmas (RNF-04/06) y seguridad esencial |
| 16 | Cierre | Demostración con la secadora y matriz de verificación |

## Contenido

| Ruta | Qué es | Dónde corre |
|---|---|---|
| `codigo/practica09/medio.py` | Simulador por eventos del medio compartido (biblioteca) | PC |
| `codigo/practica09/modelo_colisiones.py` | P9: ocupación contra colisión, ARQ, sincronía, RNF-03 | PC |
| `codigo/practica09/escaner/main.py` | Escáner de espectro con el registro RPD | Concentrador |
| `codigo/practica09/ver_espectro.py` | Visor del escáner contra el mapa Wi-Fi | PC |
| `codigo/practica09/carga_wifi.py` | Carga UDP en el Wi-Fi del robot | PC y Pi |
| `codigo/practica09/medir_enlace.py` | Entrega, primer intento, antigüedad del estado, fluctuación del ciclo | PC |
| `codigo/practica10/simular_prioridad.py` | P10: retardo de la alarma, apagón, prioridad por persistencia | PC |
| `codigo/practica10/descomponer_alarma.py` | P10: latencia de la secadora en tres tramos (sensor, persistencia, enlace) | PC |
| `codigo/practica10/latencia_algoritmo.py` | P10: latencia del `deteccion.py` real ante rampas sintéticas | PC |
| `codigo/firmware/nodo_detector/` | Nodo v3: flama por D0 y acceso al medio (`main.py`, `config.py`) | Nodo |
| `codigo/firmware/concentrador/` | Concentrador v3: duplicados, reinicios, `diag.secuencia` | Concentrador |
| `codigo/banco/` | Banco: el firmware real de varios nodos en la PC | PC |
| `codigo/infra/` | Solo Mosquitto (sin InfluxDB ni Grafana) | PC |
| `codigo/pruebas_modulo3.py` | 16 pruebas rápidas y 4 del banco | PC |

Los demás archivos del firmware (`bme280.py`, `deteccion.py`,
`formato_trama.py`, `nrf24l01.py`) son los del Módulo 1, sin cambios. El
puente serie también es el del Módulo 1, sin cambios.

## Verificación rápida, sin hardware

```bash
cd Modulo_3/codigo
pip install -r requirements.txt
pytest pruebas_modulo3.py -q                        # 16 passed, 4 deselected
pytest pruebas_modulo3.py -q -m banco               # 4 passed (unos 3 min; la
                                                    # cuarta necesita un broker)
python practica09/modelo_colisiones.py --rapido     # unos 5 s
python practica10/simular_prioridad.py --rapido     # unos 3 s
```

Versiones completas (las cifras de las guías salen de estas corridas):

```bash
python practica09/modelo_colisiones.py      # unos 3 min; 20 semillas, 24 h en la sección 6
python practica10/simular_prioridad.py      # unos 80 s; 10 semillas
python practica10/latencia_algoritmo.py     # unos segundos
```

Regresión del Módulo 2, que debe seguir en verde:

```bash
cd Modulo_2/codigo/practica08 && pytest pruebas_contrato.py -q   # 22 passed
cd ../contrato && python generar_icd.py --verificar               # SIN CAMBIOS, 6e4f2dea...
# Con el sistema en stubs (ver Modulo_2): verificar_integracion.py da 10 OK
# y pytest pruebas_contrato.py -m integracion, 4 passed.
```

## Banco de pruebas

Corre el `main.py` real del nodo y del concentrador en procesos de la PC,
con sustitutos de `machine`, `utime`, `nrf24l01` y `bme280` (`banco/mpy/`).
Un proceso `aire.py` decide colisiones, interferencia y acuses. Verifica la
lógica del firmware con varios nodos; **no** reproduce la temporización
del radio.

```bash
cd Modulo_3/codigo/banco
python correr.py --nodos 3 --duracion 60
python correr.py --nodos 2 --reiniciar 2@15                     # reinicio de un nodo
python correr.py --nodos 2 --reiniciar 2@15 --concentrador m1   # el error del Módulo 1
python correr.py --nodos 3 --puente --broker localhost          # hasta MQTT (Linux o WSL)
```

## Desplegar el firmware v3

```bash
cd Modulo_3/codigo/firmware/nodo_detector
mpremote connect COM5 fs cp config.py :config.py + fs cp main.py :main.py + reset
cd ../concentrador          # detenga antes el puente: tiene el puerto abierto
mpremote connect COM4 fs cp config.py :config.py + fs cp main.py :main.py + reset
```

`config.py` del nodo controla lo que cambia entre prácticas: `CANAL_RF`
(76 o 70), `POLITICA` (`"v3"` o `"v1"`) y `PERIODO_FIJO_S` (0.5 o 1.0 para
medir rápido; `None` en operación).

## Qué cambió fuera de `Modulo_3`

- `Modulo_2/codigo/practica08/pruebas_contrato.py`: la prueba del 503 fallaba
  de forma intermitente con un broker en `localhost` (2 de 4 corridas). La
  fixture arrancaba el cliente MQTT real de la API y su callback ponía
  `broker = True` en otro hilo. Ahora usa el doble `ClienteFalso` desde el
  arranque: 8 de 8 en verde. No cambia la interfaz ni la huella.
- `Modulo_2/codigo/practica08/pruebas_contrato.py`, otra vez: una prueba de
  integración se omitía con "el robot no responde" aunque el robot sí
  respondía. El broker de prueba entregó en el tópico de respuestas tres
  retenidos ajenos sin `id`; el `KeyError` en `on_message` mató en silencio el
  hilo de red de paho. Ahora se ignora lo que no es una respuesta: 4 de 4 en
  dos regresiones completas.
- `Modulo_2/codigo/contrato/ICD_CONGELADO.json`, `ICD_v1.0.md` y
  `openapi.json`: el repositorio no tenía el ICD congelado, así que la prueba
  `test_contrato_no_cambio_sin_declararlo` se omitía (21 passed, 1 skipped).
  Se agregan los generados con `generar_icd.py --congelar`; huella
  `6e4f2dea0c916b64...`, la misma del Módulo 2.

## Hallazgos que el material documenta

Verificados al ejecutar el código (simulación y banco):

- **El ARQ no protege contra un vecino idéntico.** Con el retardo de
  reintento fijo del driver, dos nodos que chocan vuelven a chocar en los 8
  reintentos: la pérdida queda cerca de la colisión del primer intento, no
  de p⁹ (sección 3 de `modelo_colisiones.py`).
- **El firmware del Módulo 1 agrupa a los nodos.** Duerme el periodo después
  de transmitir; dos nodos que chocan se retrasan lo mismo y siguen juntos.
  Tras un apagón, 3 nodos entregaron 23 % en los primeros 2 minutos
  (20 semillas, fluctuación de 0.2 ms).
- **Con apagón e incendio en los tres nodos, la alarma v1 tardó una mediana
  de 29 s y un máximo de 173 s** (fluctuación de 0.2 ms); la v3, 2 ms. Todo
  depende de la fluctuación natural del ciclo del ESP32, que no se conoce y
  se mide en la P10.
- **El concentrador del Módulo 1 contaba un reinicio del nodo como 65 526
  tramas perdidas** (en el banco, 65 521 y tasa de entrega 0.0005). El v3
  lo trata como reinicio.
- **RNF-01 lo domina el algoritmo de detección, no la red.** Con el
  `deteccion.py` real y muestreo de 5.17 s, la persistencia de 6 s cuesta dos
  periodos (10.34 s), y la pendiente sobre 60 s tarda en reconocer una rampa:
  de una rampa de 120 °C/min a VIGILANCIA pasan 17.2 s de mediana; con
  12 °C/min, 33.9 s (`latencia_algoritmo.py`). El presupuesto del Módulo 1
  contó 6 s de persistencia y 2.5 s de espera. En el banco, con la secadora
  simulada, el enlace y la plataforma sumaron 47 ms de 31.1 s. Con muestreo
  de 1.17 s las medianas bajan a 10.2–24.3 s según la rampa; es una
  reingeniería que afecta a RNF-05 y se decide en el cierre.
- **El intervalo de Wilson engaña con pérdidas correlacionadas.** En 24 h, la
  v1 con 3 nodos da 99.57 % con intervalo [99.54, 99.60] %, y aun así una de
  las 5 semillas quedó en 98.30 %.

Hipótesis, no verificadas con hardware:

- El escáner supone un nRF24L01**+** (el registro RPD no existe en el
  nRF24L01 original) y no se ha corrido en el concentrador real.
- Polaridad de D0 del ILMM34020: `FLAMA_NIVEL_ACTIVO = 0` está sin
  confirmar con el módulo real.
- `random.randint` y `random.random` en el MicroPython del ESP32, y la
  lectura de `OBSERVE_TX` después de `send()`: probados en el banco, no en la
  placa.
- La rampa que la secadora produce en el BME280: decide si RNF-01 se cumple.
- La fluctuación natural del ciclo del nodo; la tasa que alcanza
  `carga_wifi.py` en la Pi 3B; la forma real del espectro Wi-Fi sobre el
  canal 70.
- El `main.py` del nodo en GitHub (Módulo 1) todavía lee la flama por ADC; el
  cambio a D0 se hizo fuera del repositorio. La v3 lo incorpora.

Resueltos de la lista de problemas conocidos:

- El contrato de la acción del ventilador: `accion = "ventilador"` con
  `parametros.encendido` (`contrato_mensajes.py`).
- Un comando **rechazado** no reinicia el plazo del estado seguro; uno
  **duplicado** tampoco (`control_actuadores.py`, `Robot.atender`: ambos
  regresan antes de actualizar `ultimo_comando`).
- `infra/` del Módulo 3 levanta solo Mosquitto.
