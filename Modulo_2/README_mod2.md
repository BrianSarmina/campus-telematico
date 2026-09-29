# Módulo 2 — Concepción del sistema y contratos (versión 2.1)

Material de las semanas 5 a 8 de Telemática, adaptado a un grupo de dos
alumnos, robot de base fija y 2.5 h de teoría más 2.5 h de laboratorio.

## Contenido

| Archivo | Para quién |
|---|---|
| `modulo2_programa.pdf` | Documento oficial del módulo |
| `modulo2_profesor_p5p6.pdf` | Guía del profesor, prácticas 5 y 6 |
| `modulo2_profesor_p7p8.pdf` | Guía del profesor, prácticas 7 y 8 |
| `modulo2_alumnos_p5p6.pdf` | Manual del alumno, prácticas 5 y 6 |
| `modulo2_alumnos_p7p8.pdf` | Manual del alumno, prácticas 7 y 8 |
| `codigo_modulo2.zip` | Código completo, listo para Git |
| `*.tex`, `preambulo.tex` | Fuentes editables |

Para compilar, la carpeta `codigo/` debe estar junto a los `.tex`:

```bash
unzip codigo_modulo2.zip
latexmk -pdf modulo2_profesor_p7p8.tex
```

## Verificación rápida, sin hardware

```bash
cd codigo && pip install -r requirements.txt

python contrato/contrato_mensajes.py           # 10 casos del contrato
python practica07/modelo_datos.py              # idempotencia y volumen
cd practica08 && pytest pruebas_contrato.py    # 22 passed, 4 deselected
```

## El sistema completo con stubs

Siete terminales, en este orden (ver `contrato/stubs/LEEME.md`):

```bash
cd codigo/infra && docker compose up -d
cd codigo/practica07 && python ingesta.py
cd codigo/practica07 && uvicorn api:app --port 8080
cd codigo/practica06 && python control_actuadores.py --simular
cd codigo/practica06 && python servidor_video.py --simular
cd <modulo1>/practica04/puente && python puente_serie.py --simular
cd codigo/practica07 && CAMPUS_VIDEO=http://localhost:8000/video streamlit run consola.py
```

Y después:

```bash
cd codigo/practica08
python verificar_integracion.py --pi 127.0.0.1    # 10 eslabones en OK
pytest pruebas_contrato.py -m integracion -rs      # 4 passed
```

## Congelamiento del ICD

El congelamiento se hace en la Práctica 8, no antes:

```bash
cd codigo/contrato
python generar_icd.py --congelar     # huella esperada: 6e4f2dea0c916b64...
python generar_icd.py --verificar    # SIN CAMBIOS
```

Si su huella no coincide con `6e4f2dea0c916b64...`, el contrato fue
modificado respecto a este material: `git diff contrato/`.

## Hallazgos que el material documenta

Surgieron al verificar el código y se incorporaron como contenido:

- **El instrumento de medición de video medía su propia cola** (P6):
  1335 ms en bucle local por búferes llenos al abrir el flujo.
- **El interruptor de hombre muerto** (P7): el estado seguro del robot obliga
  a la consola a reenviar la orden del ventilador cada segundo.
- **Una prueba intermitente por condición de carrera** (P8): se corrigió la
  prueba, no se repitió hasta que pasara.
