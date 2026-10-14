#!/usr/bin/env python3
"""Mide modelos para decidir cuál usa Hermes y cuál el autopilot.

No es una subjective: qué modelo hace qué se decide con la salida de esto. Se
miden cuatro cosas, porque una sola no alcanza para repartir el trabajo:

1. **Carga**: cuánto tarda en entrar en VRAM. Define si se puede pagar por fase.
2. **Velocidad**: tokens/s con una salida realista de plan. Un modelo que razona
   bien pero va a 2 tok/s no sirve para un bucle de tools.
3. **Tool-calling**: ¿devuelve `tool_calls` estructurado o el JSON dentro del
   texto? De esto depende si el modelo puede pilotar Hermes o si hace falta el
   autopilot.
4. **Calidad**: la pregunta que más importa y la menos obvia — ¿el plan que
   propone menciona archivos que **existen**? Un modelo que inventa rutas es
   peor que uno lento, porque el trabajo se pierde en silencio.

Uso:
    python3 bin/measure-models.py                 # todos los candidatos
    python3 bin/measure-models.py qwen2.5:14b     # uno solo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"
CANDIDATOS = ["qwen2.5:7b", "qwen2.5:14b", "gemma3:4b", "llama3.2:3b", "qwen3:4b"]

# Una tarea real de este repo, con respuesta verificada a mano. Mide lo que la
# fase "entender" hará de verdad: receives la EVIDENCIA y la sintetiza. La
# evidencia son los tres manifests del proyecto Flutter y lo que declara cada
# uno; el acierto es que la causa es el manifest `main`, que es el único sin el
# permiso y el único que entra en release.
TAREA = {
    "objetivo": (
        "La app Flutter de Aegis se conecta al bridge en debug y en profile, pero "
        "en una build de release no se conecta a nada. Diagnostica la causa y di "
        "qué archivo hay que cambiar."
    ),
    "evidencia": (
        "Evidencia de los manifests de este proyecto:\n"
        "  android/app/src/main/AndroidManifest.xml    -> 0 uses-permission\n"
        "  android/app/src/debug/AndroidManifest.xml  -> INTERNET\n"
        "  android/app/src/profile/AndroidManifest.xml-> INTERNET\n"
        "  (el manifest de una build debug sí trae INTERNET tras el merge)"
    ),
    "archivo_correcto": "mobile/android/app/src/main/AndroidManifest.xml",
}
#: La raíz del repo, derivada de la posición de este fichero
#: (`bridge/bin/lab/` → cuatro niveles arriba) y no escrita a mano. Antes era una
#: ruta absoluta de una máquina, y el script solo servía en ella.
PREFIX_RAIZ = Path(__file__).resolve().parents[3]


def _post(url: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _generar(modelo: str, prompt: str, num_predict: int = 200,
             system: str = "", timeout: int = 900,
             num_ctx: int | None = None) -> dict:
    """Una generación. **`timeout` es un parámetro de la función**, no solo de `_post`.

    ## Por qué el parámetro es explícito
    Estaba roto desde hacía meses: `medir_carga` pasaba `timeout=900` a `_generar`,
    que no lo aceptaba, así que **toda** la medición moría con
    `TypeError: _generar() got an unexpected keyword argument 'timeout'` antes de
    tocar un modelo. Un instrumento que no corre no mide nada, y se dejaba
    como si midiera: por eso está en `bin/lab/` y ahora tiene un comprobador.
    """
    opciones: dict = {"num_predict": num_predict, "temperature": 0.2}
    if num_ctx:
        # El contexto por defecto son 64 000 tokens en una tarjeta de 6 GB, y
        # carga la KV cache antes que los pesos. Medido: de 64k a 16k, un paso
        # real pasa de 11,2 s a 8,3 s. Ver A-089.
        opciones["num_ctx"] = num_ctx
    cuerpo = {"model": modelo, "prompt": prompt, "stream": False,
              "options": opciones}
    if system:
        cuerpo["system"] = system
    return _post(f"{OLLAMA}/api/generate", cuerpo, timeout=timeout)


def medir_carga(modelo: str) -> float:
    """Segundos desde pedir el modelo hasta tener su primer token, en frío."""
    subprocess.run(["ollama", "stop", modelo], capture_output=True, timeout=120)
    inicio = time.monotonic()
    try:
        _generar(modelo, "di OK", num_predict=1, timeout=900)
    except (urllib.error.URLError, subprocess.TimeoutExpired):
        return -1.0
    return round(time.monotonic() - inicio, 1)


def medir_velocidad(modelo: str, tokens: int = 256) -> tuple[float, int]:
    """(tokens/s, tokens generados) con una salida larga de verdad."""
    r = _generar(modelo, "Explica en detalle cómo funciona un servidor HTTP: "
                         "aceptar conexiones, parsear peticiones, responder. "
                         "Sin listas, en prosa.", num_predict=tokens)
    n = r.get("eval_count", 0)
    segundos = r.get("eval_duration", 0) / 1e9
    return (round(n / segundos, 1) if segundos > 0 else 0.0), n


TOOLS = [{
    "type": "function",
    "function": {
        "name": "aegis_write_file",
        "description": "Escribe contenido completo en un archivo del repo",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]},
    },
}]
PREGUNTA_TOOL = ('Escribe un archivo nuevo en el proyecto aegis que se llame '
                 'notas.md con el texto "hola". Usa la tool aegis_write_file.')


def medir_tool_call(modelo: str) -> str:
    """'tool_calls' (estructurado) | 'texto' (el JSON va en el texto) | 'nada'."""
    r = _post(f"{OLLAMA}/v1/chat/completions", {
        "model": modelo, "stream": False,
        "messages": [{"role": "user", "content": PREGUNTA_TOOL}],
        "tools": TOOLS,
    })
    msg = r["choices"][0].get("message") or {}
    if msg.get("tool_calls"):
        return "tool_calls"
    texto = str(msg.get("content") or "")
    if '"name"' in texto and "aegis_write_file" in texto:
        return "texto"
    return "nada"


def _estructura() -> str:
    """Dos niveles del repo, para que el modelo pueda mirar en vez de adivinar.

    La primera versión de esta prueba no incluía nada de esto y TODOS los modelos
    fallaron, incluido el que knew la respuesta: estaban adivinando la raíz del
    proyecto, no razonando. Un agente real lista el directorio. Medir la
    adivinanza en vez del razonamiento no sirve para decidir quién hace qué.
    """
    lineas = []
    try:
        for hijo in sorted(PREFIX_RAIZ.iterdir()):
            if hijo.name.startswith("."):
                continue
            if hijo.is_dir():
                lineas.append(hijo.name + "/")
                for nieto in sorted(hijo.iterdir()):
                    if nieto.is_dir() and not nieto.name.startswith("."):
                        lineas.append(f"  {hijo.name}/{nieto.name}/")
            else:
                lineas.append(hijo.name)
    except OSError:
        return "(no se pudo listar)"
    return "\n".join(lineas[:60])


def medir_calidad(modelo: str, con_estructura: bool = True) -> dict:
    """¿El plan menciona archivos que existen? ¿Trae criterio comprobable?"""
    sistema = (
        "Eres el director técnico de Aegis. Analizas el proyecto y respondes SOLO "
        "con un JSON literal, sin texto antes ni después, con esta forma exacta:\n"
        '{"archivos": ["ruta/relativa"], "causa": "una frase", '
        '"criterio_de_exito": "cómo se comprueba", "riesgo": "una frase"}\n'
        "Las rutas son relativas a la raíz del proyecto aegis y tienen que existir "
        "de verdad. No inventes archivos: usa solo lo que está en la estructura."
    )
    peticion = TAREA["objetivo"] + "\n\n" + TAREA["evidencia"]
    if con_estructura:
        peticion += "\n\nRutas disponibles:\n" + _estructura()
    try:
        r = _generar(modelo, peticion, num_predict=400, system=sistema)
    except (urllib.error.URLError, json.JSONDecodeError):
        return {"json": False, "acierto": False, "criterio": False,
                "inventados": 0, "archivos": []}

    texto = str(r.get("response") or "")
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return {"json": False, "acierto": False, "criterio": False,
                "inventados": 0, "archivos": []}
    try:
        plan = json.loads(texto[inicio:fin + 1])
    except json.JSONDecodeError:
        return {"json": False, "acierto": False, "criterio": False,
                "inventados": 0, "archivos": []}

    archivos = [a for a in (plan.get("archivos") or []) if isinstance(a, str)]
    existen = [a for a in archivos if (PREFIX_RAIZ / a.lstrip("./")).exists()]
    return {
        "json": True,
        "acierto": any(TAREA["archivo_correcto"] in a for a in archivos),
        "existentes": len(existen),
        "inventados": len(archivos) - len(existen),
        "criterio": bool(str(plan.get("criterio_de_exito") or "").strip()),
        "archivos": archivos[:4],
    }


def medir(modelo: str, con_carga: bool = True) -> dict:
    print(f"\n=== {modelo} ===", flush=True)
    fila: dict = {"modelo": modelo}
    if con_carga:
        fila["carga_s"] = medir_carga(modelo)
        print(f"  carga:      {fila['carga_s']} s", flush=True)
    t0 = time.monotonic()
    tok_s, n = medir_velocidad(modelo)
    fila["tok_s"] = tok_s
    fila["tokens"] = n
    print(f"  velocidad:  {tok_s} tok/s  ({n} tokens en "
          f"{round(time.monotonic()-t0,1)} s)", flush=True)
    try:
        fila["tool_call"] = medir_tool_call(modelo)
    except Exception as exc:                      # noqa: BLE001
        fila["tool_call"] = f"error: {type(exc).__name__}"
    print(f"  tool_call:  {fila['tool_call']}", flush=True)
    fila["calidad"] = medir_calidad(modelo)
    c = fila["calidad"]
    print(f"  calidad:    json={c['json']} acierto={c['acierto']} "
          f"inventados={c.get('inventados')} criterio={c['criterio']}", flush=True)
    if c.get("archivos"):
        print(f"              dijo: {c['archivos']}", flush=True)
    return fila


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modelos", nargs="*", default=None)
    ap.add_argument("--sin-carga", action="store_true",
                    help="no medir el arranque en frío (más rápido)")
    ap.add_argument("--salida", default="", help="volcar JSON a este archivo")
    args = ap.parse_args()

    modelos = args.modelos or CANDIDATOS
    resultados = []
    for m in modelos:
        try:
            resultados.append(medir(m, con_carga=not args.sin_carga))
        except Exception as exc:                  # noqa: BLE001
            print(f"\n=== {m} === falló la medición: {type(exc).__name__}: {exc}")
            resultados.append({"modelo": m, "error": str(exc)})

    print("\n" + "=" * 78)
    print(f"  {'modelo':16}{'carga':>7}{'tok/s':>8}{'tool_call':>12}"
          f"{'acierto':>9}{'inventa':>8}{'criterio':>10}")
    print("  " + "-" * 74)
    for r in resultados:
        if "error" in r:
            print(f"  {r['modelo']:16}  ERROR: {r['error'][:30]}")
            continue
        c = r["calidad"]
        print(f"  {r['modelo']:16}{r.get('carga_s', 0):>7}{r.get('tok_s', 0):>8}"
              f"{r.get('tool_call', '?'):>12}{str(c.get('acierto')):>9}"
              f"{str(c.get('inventados', '-')):>8}{str(c.get('criterio')):>10}")
    if args.salida:
        Path(args.salida).write_text(json.dumps(resultados, ensure_ascii=False, indent=2))
        print(f"\nvolcado a {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
