"""Igual que medir-autopilot, pero para el motor Hermes vía /tasks.

El método y la ficha se inyectan por `instructions`, encima del system prompt
propio de Hermes. La línea base (memoria limpia, sin método) fue 20/20; esto
comprueba que añadir 5 kB de contexto no la rompe.
"""
import json
import os
import sys
import time

import httpx

BRIDGE = "http://127.0.0.1:8000"
RUNS = "/RUTA/AL/REPO/bridge/data/logs/runs"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
PROYECTO = sys.argv[2] if len(sys.argv) > 2 else "aegis"
PROMPT = ("Usa la tool projects_list para ver qué proyectos hay en el workspace. "
          "Cuando termine, responde SOLO con la palabra OK.")

print(f"{'run':<4} {'tool_real':>9} {'estado':>11}  tools")
print("-" * 60)
ok = 0
for i in range(N):
    payload = {"prompt": PROMPT}
    if PROYECTO:
        payload["project"] = PROYECTO
    rid = httpx.post(f"{BRIDGE}/tasks", json=payload, timeout=60).json()["run_id"]
    estado = "?"
    for _ in range(120):
        estado = httpx.get(f"{BRIDGE}/tasks/{rid}", timeout=30).json()["status"]
        if estado in ("completed", "failed", "stopped"):
            break
        time.sleep(2)
    time.sleep(1.5)
    ruta = f"{RUNS}/{rid}.jsonl"
    tools = []
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.strip()
            if not linea or '"tool.completed"' not in linea:
                continue
            ev = json.loads(linea)
            if ev.get("event") != "tool.completed":
                continue
            d = (ev.get("payload") or {}).get("data") or {}
            if d.get("tool") and not d.get("error"):
                tools.append(d["tool"])
    ok += bool(tools)
    print(f"[{i+1}] {'SI' if tools else 'NO':>9} {estado:>11}  {','.join(tools) or '-'}")
    time.sleep(2)

print("-" * 60)
print(f"HERMES con método+ficha inyectados: {ok}/{N} con tool realmente ejecutada")