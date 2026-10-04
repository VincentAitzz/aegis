"""¿El prompt grande rompió el tool calling? No lo supongo: lo mido.

La línea base de autopilot era 205 chars de system prompt y 3/3 tools
ejecutadas. Con el método y la ficha inyectados el prompt crece. La lección
A-016 dice que un prompt grande puede dejar al modelo sin llamar a ninguna tool
sin que nada falle por fuera, así que esto se mide end-to-end.
"""
import json
import sys
import time

import httpx

BRIDGE = "http://127.0.0.1:8000"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PROYECTO = sys.argv[2] if len(sys.argv) > 2 else "aegis"
PROMPT = ("Usa la tool projects_list para listar los proyectos del workspace y "
          "dime cuántos hay.")

print(f"{'run':<4} {'tool_real':>9} {'estado':>11}  tools / fin")
print("-" * 66)
ok = 0
for i in range(N):
    rid = httpx.post(f"{BRIDGE}/autopilot/start",
                     json={"project": PROYECTO, "max_steps": 3, "prompt": PROMPT},
                     timeout=60).json()["run_id"]
    datos = {"run_id": rid, "status": "running"}
    for _ in range(120):
        datos = httpx.get(f"{BRIDGE}/autopilot/{rid}", timeout=30).json()
        if datos["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    tools = [t.get("tool") for t in datos.get("trace", []) if t.get("tool")]
    real = bool(tools)
    ok += real
    print(f"[{i+1}] {'SI' if real else 'NO':>9} {datos['status']:>11}  "
          f"{','.join(tools) or '-'} / {datos.get('fin')}")
    time.sleep(1)

print("-" * 66)
print(f"AUTOPILOT con prompt ampliado: {ok}/{N} con tool realmente ejecutada")