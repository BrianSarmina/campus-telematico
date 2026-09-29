# Stubs del sistema

Un *stub* sustituye a una pieza que todavía no existe, o que no está
disponible, respetando su contrato. Permite desarrollar y probar el resto del
sistema sin esperarla.

Ninguno de estos es un programa aparte: son los programas reales en modo de
simulación. Así el stub nunca se desvía del contrato, porque es el mismo código.

| Sustituye a | Stub | Contrato que respeta |
|---|---|---|
| Nodo detector y enlace RF | `practica04/puente/puente_serie.py --simular --escenario incendio` | Telemetría, alertas y estado `puente-rf` |
| Nodo detector (sin puente) | `practica01/publicador.py --escenario incendio` (Módulo 1) | Telemetría y alertas |
| Robot | `practica06/control_actuadores.py --simular` | Comando, respuesta, estado seguro |
| Cámara | `practica06/servidor_video.py --simular` | Flujo MJPEG y `/metricas` |
| Cliente MQTT de la API | `ClienteFalso` en `practica08/pruebas_contrato.py` | Tópico y QoS del comando |

Con los cuatro primeros, el sistema completo corre en una sola computadora sin
ningún hardware: así se desarrolló y verificó la consola de la Práctica 7.
