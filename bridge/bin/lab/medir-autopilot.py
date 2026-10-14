"""¿El prompt grande rompió el tool calling? No lo supongo: lo mido.

Mide el bucle **end-to-end** sobre un encargo real: tools ejecutadas, `fin` y
latencia. Es el único modo que vale aquí, porque el fallo que hay que detectar —
«parece que funciona pero no hace nada» — **no se ve desde dentro**: el run se
reporta como completo y ningún test se pone rojo. La lección A-016 lo medió así:
0/8 tool calls con tres episodios falsos en el prompt, 7/8 sin ellos.

## Por qué mide latencia además de tool-calling

Porque son dos preguntas distintas y se pueden oponer:

- **tool-calling**: ¿el prompt grande dejó al modelo sin llamar a nada? Si baja,
  el prompt grande rompió algo.
- **latencia**: ¿qué cuesta el prompt grande en cada paso?

Se miden los dos porque una mejora en el segundo puede esconder un problema en el
primero: un prompt más corto que hace perder tools **es más rápido**.

## Por qué se arregló el token y no solo el 401

El script llevaba desde el 2026-10-04 devolviendo `KeyError: 'run_id'` sin que
nadie lo notara, porque `/autopilot/start` pasó a pedir `X-Aegis-Token` y este
script lo seguía llamando sin cabecera. El README de esta carpeta avisa de
exactamente esto: *un instrumento que mide contra un contrato que ya no está no
mide: da un número falso*. No daba falso: daba una excepción, que es menos
peligroso y por eso nadie lo miró.

    .venv/bin/python bin/lab/medir-autopilot.py [N] [proyecto]

## Para el A/B

Este script mide **una** variante, la que tenga el bridge en marcha. Para
comparar dos prompts hay que levantar el bridge dos veces; `medir-prompt-ab.py`
lo hace alternando bloques.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

BRIDGE = os.environ.get("AEGIS_BRIDGE", "http://127.0.0.1:8000")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PROYECTO = sys.argv[2] if len(sys.argv) > 2 else "aegis"
PROMPT = ("Usa la tool projects_list para listar los proyectos del workspace y "
          "dime cuántos hay.")


def token() -> str:
    """La clave de operación, leída del `.env`. **Nunca se imprime.**

    Sin esto el script recibe un 401 y revienta con `KeyError: 'run_id'`, que es
    un error que dice que el bridge está mal cuando el que está mal es el
    instrumento. Se lee igual que lo lee `bin/api`: del fichero, y fuera de aquí.
    """
    env_file = Path(os.environ.get("AEGIS_ENV", Path(__file__).resolve().parents[2] / ".env"))
    try:
        for linea in env_file.read_text(encoding="utf-8").splitlines():
            if linea.startswith("AEGIS_API_KEY="):
                return linea.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


CABECERAS = {"X-Aegis-Token": token()} if token() else {}


def un_run(prompt: str, proyecto: str, max_steps: int = 3) -> dict:
    """Lanza un run y espera a que termine. Devuelve su veredicto y su duración."""
    inicio = time.monotonic()
    respuesta = httpx.post(f"{BRIDGE}/autopilot/start", json={
        "project": proyecto, "max_steps": max_steps, "prompt": prompt,
    }, headers=CABECERAS, timeout=60)
    respuesta.raise_for_status()
    rid = respuesta.json()["run_id"]
    datos = {"run_id": rid, "status": "running"}
    for _ in range(180):
        datos = httpx.get(f"{BRIDGE}/autopilot/{rid}", headers=CABECERAS, timeout=30).json()
        if datos.get("status") in ("completed", "failed"):
            break
        time.sleep(2)
    return {
        "run_id": rid,
        "status": datos.get("status"),
        "fin": datos.get("fin"),
        "tools": [t.get("tool") for t in datos.get("trace", []) if t.get("tool")],
        "segundos": round(time.monotonic() - inicio, 1),
    }


def main() -> int:
    if not CABECERAS:
        print("AVISO: no hay AEGIS_API_KEY en bridge/.env. Si el bridge la exige, "
              "este script recibirá 401.", file=sys.stderr)
    print(f"{'run':<4} {'tool_real':>9} {'s':>7} {'estado':>11}  tools / fin")
    print("-" * 78)
    filas = []
    for i in range(N):
        r = un_run(PROMPT, PROYECTO)
        real = bool(r["tools"])
        filas.append((real, r["segundos"]))
        print(f"[{i+1}] {'SI' if real else 'NO':>9} {r['segundos']:>7} "
              f"{r['status']:>11}  {','.join(r['tools']) or '-'} / {r['fin']}")
        time.sleep(1)

    ok = sum(1 for real, _ in filas if real)
    tiempos = [s for _, s in filas]
    print("-" * 78)
    print(f"tool-calling: {ok}/{N} con tool realmente ejecutada")
    if tiempos:
        print(f"latencia:     mediana {statistics.median(tiempos):.1f} s · "
              f"mín {min(tiempos):.1f} · máx {max(tiempos):.1f}")
    # JSON para comparar dos variantes sin tener que leer la tabla.
    print(json.dumps({"tool_calling": f"{ok}/{N}", "n": N,
                      "mediana_s": statistics.median(tiempos) if tiempos else None,
                      "filas": filas}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())