#!/usr/bin/env python
"""Medir el prompt del autopilot: tamaño y de qué está hecho.

Existe porque «el prompt es el cuello de botella» es una afirmación que hay que
poder repetir. Un número que se mira una vez en un terminal no es una medición:
es una impresión. Este script la hace reproducible y **descompuesta**, que es lo
que permite saber qué parte grew y cuál no.

    .venv/bin/python bin/medir-prompt.py
    .venv/bin/python bin/medir-prompt.py --json

## Qué mide y qué no

Mide **caracteres**, no tokens. Los dos están correlacionados y los caracteres se
cuentan sin depender del tokenizador, así que la comparación entre «antes» y
«después» no se mueve porque cambiara el modelo. No mide latencia: eso exige un
Ollama encendido y comparar la misma llamada con y sin variante, y está en
`docs/medidas.md`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def bloques(proyecto: str, encargo: str) -> list[tuple[str, int]]:
    """Cada pieza del system prompt con su tamaño, preguntándoselo a su módulo.

    ## Por qué esto y no parsear el prompt
    La primera versión de este script partía el prompt buscando líneas con dos
    puntos y%+ una línea en blanco detrás, y salió un desglose que sumaba más que
    el prompt entero. Un medidor que no cuadra no es un medidor defectuoso: es
    un medidor que miente, y un medidor que miente en un repo cuyo invariante
    central es *el veredicto sale de la evidencia* es el peor sitio para que
    ocurra.

    Así que no se parsea nada: se llama a cada productor —`method_context`,
    `quien_context`, `context_for`, `indice`— y se mide lo que devuelve. Si un
    bloque crece, el número lo dice y en la función exacta que lo hizo crecer.
    """
    from app.autopilot import SYSTEM_PROMPT, load_lessons
    from app.fichas import context_for
    from app.lecciones import indice
    from app.method import method_context
    from app.quien import contexto as quien_context

    piezas = [
        ("identidad (SYSTEM_PROMPT)", SYSTEM_PROMPT),
        ("método", method_context(proyecto)),
        ("tu perfil", quien_context()),
        ("ficha del proyecto", context_for(proyecto)),
        ("lecciones (índice + la más relevante)", load_lessons(proyecto, encargo)),
        # El índice se mide siempre, esté o no en el prompt: es el número
        # que dice cuánto se quitó, y no solo cuánto queda.
        ("— el índice, que ya NO va al prompt", indice(proyecto)),
    ]
    return [(n, len(v)) for n, v in piezas if v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="solo JSON, sin texto")
    ap.add_argument("--proyecto", default="aegis")
    args = ap.parse_args()

    # Un entorno limpio: si el `.env` de quien lo ejecuta tiene AEGIS_API_KEY o
    # lo que sea, el prompt no cambia, pero las measurements comparables
    # necesitan que el punto de partida sea el mismo.
    from app.autopilot import _tools_schema, build_system_prompt
    from app import method

    prompt = build_system_prompt("", args.proyecto, "", encargo="una tarea cualquiera")
    try:
        n_tools = len(_tools_schema())
    except Exception:  # noqa: BLE001 — sin Ollama se mide igual, menos el schema
        n_tools = -1

    desglose = bloques(args.proyecto, 'una tarea cualquiera')
    total = len(prompt)

    if args.json:
        print(json.dumps({"total": total, "n_tools": n_tools, "bloques": desglose},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"prompt del system: {total:,} caracteres")
    if n_tools >= 0:
        print(f"schema de tools:   {n_tools} tools")
    print()
    print("de qué está hecho:")
    suma = 0
    for nombre, chars in desglose:
        # Las líneas que empiezan por «—» son un **desglose** de la anterior, no
        # un bloque más. Sumarlas daría un resto negativo, que es exactamente el
        # tipo de número que hace que alguien deje de mirar el instrumento.
        if nombre.startswith("—"):
            print(f"  {chars:>7,}  {'':>4}      └─ (fuera del prompt)")
            continue
        suma += chars
        pct = round(100 * chars / total) if total else 0
        print(f"  {chars:>7,}  {pct:>3}%  {'#' * max(1, round(pct / 3))} {nombre}")
    resto = total - suma
    pct_resto = round(100 * resto / total) if total else 0
    print(f"  {resto:>7,}  {pct_resto:>3}%  "
          f"{'#' * max(1, round(pct_resto / 3))} (separadores \"\n\n\" y bloques vacíos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())