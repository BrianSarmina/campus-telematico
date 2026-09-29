"""Generador y congelador del ICD - Modulo 2, Practica 8.

EL DOCUMENTO SE GENERA DESDE EL CONTRATO, NO AL REVES
Un ICD escrito a mano se desactualiza en cuanto alguien cambia el codigo y
olvida editar el documento. Aqui el documento se produce a partir de los
esquemas ejecutables: no puede decir algo distinto de lo que el sistema
verifica.

QUE SIGNIFICA CONGELAR
Congelar no es prometer que nadie tocara el contrato. Es registrar su HUELLA:
un resumen SHA-256 de todo lo que define la interfaz (esquemas, topicos,
calidad de servicio, trama de radiofrecuencia, rutas de la API y plazo del
estado seguro). A partir de ahi:

  - Si el contrato cambia y la version NO cambio, la verificacion falla:
    alguien modifico la interfaz sin declararlo.
  - Si el contrato cambia y la version SI cambio, la verificacion lo reporta
    como cambio declarado, y hay que volver a congelar.

La disciplina del congelamiento deja de depender de la memoria de nadie.

Uso:
    python generar_icd.py                 genera ICD_v<version>.md y openapi.json
    python generar_icd.py --congelar      ademas registra la huella
    python generar_icd.py --verificar     compara con la huella congelada
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, "..", "practica07"))

import contrato_mensajes as ct
import trama_rf

ARCHIVO_CONGELADO = os.path.join(AQUI, "ICD_CONGELADO.json")


def rutas_api():
    """Rutas de la API tomadas de la especificacion OpenAPI que genera FastAPI."""
    try:
        import api
    except ImportError as e:
        print("AVISO: no se pudo importar la API ({}). Se omite.".format(e))
        return [], None
    esquema = api.app.openapi()
    rutas = sorted("{} {}".format(m.upper(), p)
                   for p, ops in esquema["paths"].items() for m in ops)
    return rutas, esquema


def definicion():
    """Todo lo que forma parte de la interfaz, en una sola estructura."""
    rutas, _ = rutas_api()
    return {
        "version": ct.VERSION_CONTRATO,
        "esquemas": ct.ESQUEMAS,
        "topicos": ct.TOPICOS,
        "qos": ct.QOS,
        "retenido": ct.RETENIDO,
        "plazo_seguro_s": ct.PLAZO_SEGURO_S,
        "trama_rf": {"formato": trama_rf.FORMATO,
                     "version": trama_rf.VERSION_TRAMA,
                     "tamano": trama_rf.TAMANO},
        "api": rutas,
    }


def huella(defi=None):
    """SHA-256 de la definicion, sin el campo de version.

    La version se excluye a proposito: asi la huella mide si cambio la
    INTERFAZ, y la comparacion con la version dice si ese cambio se declaro.
    """
    d = dict(defi or definicion())
    d.pop("version", None)
    texto = json.dumps(d, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(texto.encode()).hexdigest()


# ------------------------------------------------------------ documento

def tabla_campos(esquema, prefijo=""):
    filas = []
    req = set(esquema.get("required", []))
    for nombre, p in esquema.get("properties", {}).items():
        tipo = p.get("type") or ("enum" if "enum" in p else "-")
        restr = []
        if "enum" in p:
            restr.append(" | ".join(str(x) for x in p["enum"]))
        if "minimum" in p or "maximum" in p:
            restr.append("{} a {}".format(p.get("minimum", "-"), p.get("maximum", "-")))
        if "pattern" in p:
            restr.append("`{}`".format(p["pattern"]))
        if "format" in p:
            restr.append(p["format"])
        filas.append("| `{}{}` | {} | {} | {} |".format(
            prefijo, nombre, tipo, "si" if nombre in req else "no",
            "; ".join(restr) or "-"))
        if p.get("type") == "object" and "properties" in p:
            filas.extend(tabla_campos(p, prefijo + nombre + "."))
    return filas


def generar_md(defi, h):
    L = []
    L.append("# Documento de Control de Interfaces - v{}".format(defi["version"]))
    L.append("")
    L.append("Campus Telematico: deteccion temprana y mitigacion de incendios.")
    L.append("")
    L.append("> Documento **generado** a partir de `contrato/contrato_mensajes.py`,")
    L.append("> `contrato/trama_rf.py` y la especificacion OpenAPI de la API.")
    L.append("> No se edita a mano: se modifica el contrato y se regenera.")
    L.append("")
    L.append("Huella del contrato: `{}`".format(h))
    L.append("")
    L.append("Generado: {}".format(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    L.append("")
    L.append("## 1. Interfaces del sistema")
    L.append("")
    L.append("| # | Interfaz | Medio | Formato | Entre |")
    L.append("|---|---|---|---|---|")
    L.append("| 1 | Trama de radiofrecuencia | nRF24L01 | binario, {} bytes | nodo detector -> concentrador |".format(defi["trama_rf"]["tamano"]))
    L.append("| 2 | Telemetria | MQTT | JSON | puente -> ingesta |")
    L.append("| 3 | Alerta | MQTT | JSON | puente -> ingesta y consola |")
    L.append("| 4 | Comando y respuesta | MQTT | JSON | API <-> robot |")
    L.append("| 5 | API de la plataforma | HTTP | JSON (OpenAPI) | consola -> API |")
    L.append("")
    L.append("## 2. Topicos y calidad de servicio")
    L.append("")
    L.append("| Clase | Topico | QoS | Retenido |")
    L.append("|---|---|---|---|")
    for clase, t in defi["topicos"].items():
        L.append("| {} | `{}` | {} | {} |".format(
            clase, t, defi["qos"][clase], "si" if defi["retenido"].get(clase) else "no"))
    L.append("")
    L.append("El topico forma parte del contrato. Los receptores clasifican los")
    L.append("mensajes por topico, nunca por la presencia de un campo.")
    L.append("")
    L.append("## 3. Trama de radiofrecuencia")
    L.append("")
    L.append("Formato `struct`: `{}` - {} bytes de los 32 disponibles, version {}.".format(
        defi["trama_rf"]["formato"], defi["trama_rf"]["tamano"], defi["trama_rf"]["version"]))
    L.append("")
    doc = trama_rf.__doc__ or ""
    ini, fin = doc.find("DISPOSICION DE LA TRAMA"), doc.find("POR QUE SE ENVIA dtemp")
    if ini >= 0 and fin > ini:
        L.append("```")
        L.append(doc[ini:fin].rstrip())
        L.append("```")
    L.append("")
    L.append("## 4. Mensajes MQTT")
    for tipo, esq in defi["esquemas"].items():
        L.append("")
        L.append("### {}".format(esq.get("title", tipo)))
        L.append("")
        L.append("| Campo | Tipo | Obligatorio | Restriccion |")
        L.append("|---|---|---|---|")
        L.extend(tabla_campos(esq))
        if esq.get("additionalProperties") is False:
            L.append("")
            L.append("No se admiten campos adicionales.")
    L.append("")
    L.append("## 5. API de la plataforma")
    L.append("")
    for r in defi["api"]:
        L.append("- `{}`".format(r))
    L.append("")
    L.append("La especificacion completa esta en `contrato/openapi.json`.")
    L.append("")
    L.append("## 6. Contrato de comportamiento")
    L.append("")
    L.append("- **Estado seguro.** Si el robot pasa {:.1f} s sin recibir comandos,".format(defi["plazo_seguro_s"]))
    L.append("  apaga el ventilador y conserva su posicion. No se recentra.")
    L.append("- **Obligacion del cliente.** Mientras se quiera el ventilador encendido,")
    L.append("  la orden debe reenviarse con un periodo menor que el plazo seguro.")
    L.append("- **Idempotencia.** Un comando con un `id` ya atendido no se ejecuta")
    L.append("  de nuevo. La ingesta descarta la telemetria repetida por `(nodo, ts)`.")
    L.append("- **Angulos absolutos.** Un comando perdido se corrige con el siguiente.")
    L.append("- **Validacion previa.** API y robot rechazan un comando que viola el")
    L.append("  contrato antes de publicarlo o de mover un actuador.")
    L.append("- **Nodo reservado.** El identificador `dff` se reserva para pruebas de")
    L.append("  integracion; sus alertas no representan eventos reales.")
    L.append("")
    L.append("## 7. Politica de versiones")
    L.append("")
    L.append("| Cambio | Version | Ejemplo |")
    L.append("|---|---|---|")
    L.append("| Agregar un campo opcional | sube MENOR | 1.0 -> 1.1 |")
    L.append("| Quitar o renombrar un campo | sube MAYOR | 1.1 -> 2.0 |")
    L.append("| Cambiar el significado o la unidad de un campo | sube MAYOR | 2.0 -> 3.0 |")
    L.append("| Cambiar un rango, un topico o el QoS | sube MAYOR | - |")
    L.append("")
    L.append("Todo cambio de la interfaz modifica la huella. Si la huella cambia y la")
    L.append("version no, `python generar_icd.py --verificar` falla.")
    L.append("")
    return "\n".join(L)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--congelar", action="store_true")
    ap.add_argument("--verificar", action="store_true")
    a = ap.parse_args()

    defi = definicion()
    h = huella(defi)

    if a.verificar:
        if not os.path.exists(ARCHIVO_CONGELADO):
            print("El contrato aun no esta congelado. Ejecute con --congelar.")
            sys.exit(2)
        c = json.load(open(ARCHIVO_CONGELADO, encoding="utf-8"))
        print("Congelado : v{}  {}".format(c["version"], c["huella"][:16]))
        print("Actual    : v{}  {}".format(defi["version"], h[:16]))
        if h == c["huella"]:
            print("\nSIN CAMBIOS. El sistema cumple el ICD congelado.")
            sys.exit(0)
        if defi["version"] == c["version"]:
            print("\nFALLA: la interfaz cambio y la version NO.")
            print("Alguien modifico el contrato sin declararlo. Opciones:")
            print("  - revertir el cambio, o")
            print("  - subir la version segun la politica y volver a congelar.")
            sys.exit(1)
        print("\nCAMBIO DECLARADO: v{} -> v{}.".format(c["version"], defi["version"]))
        print("Regenere el documento y vuelva a congelar con --congelar.")
        sys.exit(0)

    md = generar_md(defi, h)
    ruta_md = os.path.join(AQUI, "ICD_v{}.md".format(defi["version"]))
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(md)
    print("Documento   : {}".format(os.path.basename(ruta_md)))

    _, esquema_api = rutas_api()
    if esquema_api:
        with open(os.path.join(AQUI, "openapi.json"), "w", encoding="utf-8") as f:
            json.dump(esquema_api, f, indent=2, ensure_ascii=False)
        print("OpenAPI     : openapi.json ({} rutas)".format(len(defi["api"])))

    print("Version     : {}".format(defi["version"]))
    print("Huella      : {}".format(h))

    if a.congelar:
        with open(ARCHIVO_CONGELADO, "w", encoding="utf-8") as f:
            json.dump({"version": defi["version"], "huella": h,
                       "fecha": datetime.now(timezone.utc).isoformat()}, f, indent=2)
        print("\nCONGELADO. A partir de aqui, cualquier cambio de la interfaz")
        print("sin subir la version hace fallar las pruebas de contrato.")


if __name__ == "__main__":
    main()
