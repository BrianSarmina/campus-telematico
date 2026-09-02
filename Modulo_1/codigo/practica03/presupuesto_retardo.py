"""Presupuesto de retardo extremo a extremo - Modulo 1, Practica 3.

Descompone el retardo de una cadena en sus componentes, suma el presupuesto y
lo contrasta con el requisito. Responde la pregunta clave del modulo: que
componente domina, y por tanto donde vale la pena invertir esfuerzo.

DOS CADENAS, DOS REQUISITOS

  alarma        RNF-01, menos de 5 s. Del estimulo fisico al aviso en consola.
                Recorre el enlace de radiofrecuencia.

  teleoperacion RNF-02, menos de 150 ms. Del movimiento del operador a verlo
                en el video. Recorre el enlace Wi-Fi del robot.

Los valores marcados MEDIR deben sustituirse por mediciones propias en la
Practica 4 y en el Modulo 2. Los que estan aqui son estimaciones iniciales.

Uso:
    python presupuesto_retardo.py --cadena alarma
    python presupuesto_retardo.py --cadena teleoperacion
    python presupuesto_retardo.py --cadena teleoperacion --fps 30
"""
import argparse


def cadena_alarma(periodo_s, reintentos, t_serie_ms):
    """Del estimulo fisico al aviso en la consola del operador."""
    # El nodo solo detecta cuando toma la siguiente muestra. En promedio se
    # espera medio periodo; en el peor caso, un periodo completo.
    espera_muestreo = periodo_s * 1000 / 2.0
    return [
        ("Respuesta fisica del sensor", 2000.0, "fijo", "estimado, MEDIR"),
        ("Espera a la siguiente muestra", espera_muestreo, "variable",
         "calculado: periodo/2"),
        ("Persistencia del algoritmo", 6000.0, "fijo", "de diseno"),
        ("Calculo en el nodo", 15.0, "fijo", "estimado"),
        ("Transmision por radiofrecuencia", 1.5 * (1 + reintentos * 0.3),
         "variable", "calculado con reintentos"),
        ("Proceso en el concentrador", 20.0, "fijo", "estimado, MEDIR"),
        ("Enlace serie a la PC", t_serie_ms, "fijo", "calculado: L/R"),
        ("Puente y publicacion MQTT", 25.0, "variable", "estimado, MEDIR"),
        ("Entrega al suscriptor", 10.0, "variable", "estimado, MEDIR"),
    ]


def cadena_teleoperacion(fps, enlace_mbps, tam_cuadro_kb, distancia_km):
    """Del comando del operador a ver el resultado en el video."""
    t_captura = 1000.0 / fps
    bits = tam_cuadro_kb * 8 * 1000
    t_transmision = bits / (enlace_mbps * 1e6) * 1000
    t_propagacion = distancia_km / 200000.0 * 1000
    return [
        ("Captura del cuadro", t_captura, "fijo", "calculado: 1/fps"),
        ("Codificacion JPEG", 12.0, "fijo", "estimado, MEDIR"),
        ("Encolamiento en el emisor", 5.0, "variable", "estimado, MEDIR"),
        ("Transmision al enlace", t_transmision, "fijo", "calculado: L/R"),
        ("Propagacion", t_propagacion, "fijo", "calculado: d/v"),
        ("Encolamiento en la red", 15.0, "variable", "estimado, MEDIR"),
        ("Buffer de recepcion", 20.0, "variable", "de diseno"),
        ("Decodificacion", 8.0, "fijo", "estimado, MEDIR"),
        ("Despliegue en pantalla", 16.7, "fijo", "calculado: 1/60 Hz"),
    ]


def informe(presupuesto, requisito_ms, titulo, unidad_s=False):
    total = sum(v for _, v, _, _ in presupuesto)
    fijo = sum(v for _, v, t, _ in presupuesto if t == "fijo")
    variable = total - fijo
    esc = 1000.0 if unidad_s else 1.0
    u = "s" if unidad_s else "ms"

    print("\n" + "=" * 78)
    print("  PRESUPUESTO DE RETARDO - {}".format(titulo))
    print("=" * 78)
    print("{:<34}{:>10}{:>8}  {:<10}{:<18}".format(
        "Componente", u, "%", "Tipo", "Origen"))
    print("-" * 78)
    for nombre, valor, tipo, origen in sorted(presupuesto, key=lambda x: -x[1]):
        print("{:<34}{:>10.2f}{:>7.1f}%  {:<10}{:<18}".format(
            nombre, valor / esc, valor / total * 100, tipo, origen))
    print("-" * 78)
    print("{:<34}{:>10.2f}{:>7.1f}%".format("TOTAL", total / esc, 100.0))
    print("{:<34}{:>10.2f}{:>7.1f}%".format(
        "  componente fijo", fijo / esc, fijo / total * 100))
    print("{:<34}{:>10.2f}{:>7.1f}%".format(
        "  componente variable (jitter)", variable / esc,
        variable / total * 100))
    print("=" * 78)

    margen = requisito_ms - total
    print("\n  Requisito  : {:.2f} {}".format(requisito_ms / esc, u))
    print("  Presupuesto: {:.2f} {}".format(total / esc, u))
    print("  Margen     : {:+.2f} {}   {}".format(
        margen / esc, u, "CUMPLE" if margen > 0 else "NO CUMPLE"))

    dominante = max(presupuesto, key=lambda x: x[1])
    print("\n  Componente dominante: {} ({:.2f} {}, {:.0f}% del total)".format(
        dominante[0], dominante[1] / esc, u, dominante[1] / total * 100))
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cadena", default="alarma",
                    choices=["alarma", "teleoperacion"])
    # Cadena de alarma
    ap.add_argument("--periodo", type=float, default=5.0,
                    help="Periodo de muestreo del nodo, en s")
    ap.add_argument("--reintentos", type=int, default=5)
    ap.add_argument("--serie", type=float, default=18.0,
                    help="Retardo del enlace serie, en ms")
    # Cadena de teleoperacion
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--enlace", type=float, default=15.0, help="Mbit/s")
    ap.add_argument("--cuadro", type=float, default=35.0, help="kB")
    ap.add_argument("--distancia", type=float, default=0.05, help="km")
    a = ap.parse_args()

    if a.cadena == "alarma":
        p = cadena_alarma(a.periodo, a.reintentos, a.serie)
        informe(p, 5000.0, "CADENA DE ALARMA (RNF-01)", unidad_s=True)

        print("\n  ANALISIS DE SENSIBILIDAD: periodo de muestreo")
        print("  " + "-" * 62)
        for per in (2, 5, 10, 30, 60):
            t = sum(v for _, v, _, _ in cadena_alarma(per, a.reintentos, a.serie))
            print("   {:>3} s de periodo  ->  {:>7.2f} s   {}".format(
                per, t / 1000.0, "cumple" if t < 5000 else "NO cumple"))

        print("\n  ANALISIS DE SENSIBILIDAD: persistencia del algoritmo")
        print("  " + "-" * 62)
        for pers in (0, 3000, 6000, 12000):
            p2 = [(n, pers if n == "Persistencia del algoritmo" else v, t, o)
                  for n, v, t, o in cadena_alarma(a.periodo, a.reintentos, a.serie)]
            tot = sum(v for _, v, _, _ in p2)
            print("   {:>5.0f} ms de persistencia -> {:>7.2f} s   {}".format(
                pers, tot / 1000.0, "cumple" if tot < 5000 else "NO cumple"))

        print("\n  CONCLUSION PARA EL INFORME")
        print("  El presupuesto lo dominan tres componentes que NO son de red:")
        print("  la persistencia del algoritmo, la espera al siguiente")
        print("  muestreo y la respuesta fisica del sensor. La parte")
        print("  telematica completa (radio, serie, broker) suma menos del")
        print("  1 por ciento del total.")
        print("")
        print("  EL REQUISITO RNF-01 NO SE PUEDE CUMPLIR TAL COMO ESTA ESCRITO")
        print("  Ninguna combinacion razonable de parametros baja de 5 s")
        print("  conservando la persistencia que exige RNF-05 (menos de una")
        print("  falsa alarma cada 24 h). Los dos requisitos son incompatibles.")
        print("")
        print("  La respuesta correcta NO es forzar los numeros. Es RENEGOCIAR")
        print("  el requisito con una justificacion tecnica. Un valor")
        print("  defendible es 15 s, que deja margen para persistencia y para")
        print("  un periodo de muestreo razonable, y sigue siendo muy inferior")
        print("  al tiempo de respuesta humano ante un incendio incipiente.")
        print("")
        print("  Descubrir que un requisito es infactible ANTES de construir")
        print("  el sistema es exactamente para lo que sirve esta fase. Un")
        print("  equipo que entrega el analisis con RNF-01 en 5 s y sin")
        print("  comentario no ha hecho el trabajo.")
    else:
        p = cadena_teleoperacion(a.fps, a.enlace, a.cuadro, a.distancia)
        informe(p, 150.0, "CADENA DE TELEOPERACION (RNF-02)")

        print("\n  ANALISIS DE SENSIBILIDAD: cuadros por segundo")
        print("  " + "-" * 62)
        for fps in (10, 15, 30, 60):
            t = sum(v for _, v, _, _ in cadena_teleoperacion(
                fps, a.enlace, a.cuadro, a.distancia))
            print("   {:>3} fps  ->  {:>7.1f} ms   {}".format(
                fps, t, "cumple" if t < 150 else "NO cumple"))

        print("\n  CONCLUSION PARA EL INFORME")
        print("  Subir los fps REDUCE la latencia total, lo que parece")
        print("  contradictorio. El componente dominante es la espera hasta")
        print("  que exista el siguiente cuadro, que vale 1/fps. Mientras el")
        print("  enlace no este saturado, esa espera pesa mas que el aumento")
        print("  de trafico. La intuicion sobre que optimizar suele fallar, y")
        print("  para eso sirve construir el presupuesto.")
