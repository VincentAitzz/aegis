"""Cuánto cuesta un bloque del prompt, **en un solo proceso**.

Existe porque el primer A/B dio un número que era **8 veces mayor** que el
real, y tardó dos commits y una publicación en aceptarlo.

## El error que este instrumento no deja cometer

La primera versión (`medir-prompt-ab.py`) levantaba **dos procesos del bridge**
contra la misma GPU y alternaba los requests. Daba +31,8 s (+79 %) para las
lecciones. Remedido aquí, en un proceso: **+3,8 s (+31 %)**.

Lo que estaba midiendo era **contención**: dos procesos pidiendo al mismo Ollama,
con la VRAM de 6 GB, provocándose el uno al otro. El prompt no cuesta 32 s; el
instrumento costaba 32 s.

Por eso este script **no levanta dos nada**: pide al mismo cliente, con la misma
conexión, alternando los dos prompts. Lo que se compara es el prompt y nada más.

## Qué mide, y por qué el tiempo total no basta

El tiempo total mezcla tres cosas que no son el prompt:

1. **prefill**: procesar los tokens de entrada.
2. **generación**: cuántos tokens produce el modelo antes de parar.
3. **ruido**: la máquina, el swap, otro proceso.

Medido, el prompt de 7 953 chars cuesta **+30 ms** al primer token (la caché de
prefijo de Ollama lo absorbe casi entero) y **+3,8 s** al turno completo. Ese
salto de 30 ms a 3,8 s es generación: **con más contexto el modelo narra más
antes de llamar a la tool**, no procesa más lento.

    .venv/bin/python bin/lab/medir-prompt-costo.py [N] [modelo]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

OLLAMA = "http://127.0.0.1:11434/api/chat"


def pedir(modelo: str, system: str, user: str, num_ctx: int = 32768) -> dict:
    """Una llamada. Devuelve primer token, total, fragmentos y caracteres."""
    body = json.dumps({"model": modelo, "stream": True, "keep_alive": "30m",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "options": {"num_ctx": num_ctx}}).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    ttft = None
    frag = 0
    chars = 0
    with urllib.request.urlopen(req, timeout=300) as r:
        for linea in r:
            if not linea.strip():
                continue
            d = json.loads(linea)
            c = (d.get("message") or {}).get("content") or ""
            if c:
                if ttft is None:
                    ttft = time.monotonic() - t0
                frag += 1
                chars += len(c)
            if d.get("done"):
                break
    return {"ttft": ttft or 0.0, "total": time.monotonic() - t0,
            "frag": frag, "chars": chars}


def prompt_con_lecciones() -> str:
    """El prompt de antes del commit 0669557, reconstruido desde sus piezas.

    Se compone con las **mismas funciones** que compone el de hoy, no con una
    copia pegada: si el prompt bueno cambia, este cambia con él y la comparación
    sigue siendo de la misma cosa.
    """
    from app import lecciones as L
    from app.autopilot import SYSTEM_PROMPT
    from app.fichas import context_for
    from app.method import method_context
    from app.quien import contexto

    partes = [SYSTEM_PROMPT, method_context("aegis"), contexto(), context_for("aegis")]
    indice = L.indice("aegis")
    if indice:
        partes.append(
            "LECCIONES DE ESTE PROYECTO (índice, no el texto entero). Si una encaja "
            "con lo que te toca, pídela con la tool `lecciones(alias, tema)` antes de "
            "actuar — o léela aquí si va entera:\n" + indice)
        encaja = L.relevantes("aegis", ENCARGO)
        if encaja:
            partes.append("La que más aplica a este encargo:\n\n" + encaja[0].como_texto())
    return "\n\n".join(p for p in partes if p)


ENCARGO = ("Usa la tool projects_list para listar los proyectos y dime cuántos hay.")
PREGUNTA = "Usa la tool projects_list para listar los proyectos y dime cuántos hay."


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    modelo = sys.argv[2] if len(sys.argv) > 2 else "llama3.2:3b"

    from app.autopilot import build_system_prompt
    limpio = build_system_prompt("", "aegis", "", encargo=ENCARGO)
    viejo = prompt_con_lecciones()

    print(f"modelo: {modelo}   ·   n={n} por variante, alternando en un proceso")
    print(f"  prompt limpio:          {len(limpio):>7,} chars")
    print(f"  prompt con lecciones:   {len(viejo):>7,} chars")
    print(f"  diferencia:             {len(viejo) - len(limpio):>+7,} chars\n")

    # La primera de cada variante es de calentamiento: el modelo aún no está en
    # VRAM y el prefijo aún no está en caché. Se descarta, y se dice en pantalla,
    # porque un número que no dice qué ha descartado no es reproducible.
    acc = {"limpio": [], "con_lecciones": []}
    for i in range(n + 1):
        pares = [("limpio", limpio), ("con_lecciones", viejo)]
        if i % 2:
            pares.reverse()
        for etiqueta, sysp in pares:
            r = pedir(modelo, sysp, PREGUNTA)
            if i:
                acc[etiqueta].append(r)

    def stat(filas, clave):
        return statistics.median(f[clave] for f in filas)

    print(f"{'variante':<16} {'1er token':>11} {'total':>9} {'frag/s':>9} "
          f"{'chars':>7}")
    print("-" * 58)
    for etiqueta in ("limpio", "con_lecciones"):
        f = acc[etiqueta]
        print(f"{etiqueta:<16} {stat(f,'ttft'):>10.2f}s {stat(f,'total'):>8.1f}s "
              f"{stat(f,'frag')/stat(f,'total'):>8.1f} {int(stat(f,'chars')):>7}")
    print("-" * 58)
    d = stat(acc["con_lecciones"], "total") - stat(acc["limpio"], "total")
    dt = stat(acc["con_lecciones"], "ttft") - stat(acc["limpio"], "ttft")
    print(f"diferencia: primer token {dt:+.2f}s · total {d:+.1f}s "
          f"({d / stat(acc['limpio'],'total'):+.0%})")
    print(json.dumps({
        "n": n, "modelo": modelo,
        "limpio": {"ttft": round(stat(acc["limpio"], "ttft"), 3),
                   "total": round(stat(acc["limpio"], "total"), 1)},
        "con_lecciones": {"ttft": round(stat(acc["con_lecciones"], "ttft"), 3),
                          "total": round(stat(acc["con_lecciones"], "total"), 1)},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())