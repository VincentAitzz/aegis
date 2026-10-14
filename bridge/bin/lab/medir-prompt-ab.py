"""A/B del prompt: con las lecciones inyectadas y sin ellas, alternando.

Responde a la pregunta que dejó abierto la Fase A: *quitar las lecciones mejoró
algo, o solo quitó peso?* Dos cosas pueden moverse y no tienen por qué moverse
juntas:

- **tool-calling**: ¿el prompt grande dejó al modelo sin llamar a nada?
- **latencia**: ¿cuánto cuesta el prompt grande en cada paso?

Se miden los dos porque una mejora en el segundo puede tapar un problema en el
primero. Un prompt más corto que hace perder tools **es más rápido**.

## Por qué un segundo bridge y no una bandera en el código

Se podría meter `AEGIS_LAB_LECCIONES=1` en `load_lessons` y ya. No se hace, por
dos razones:

1. Es una puerta que puede quedarse encendida por accidente en producción, y este
   repo ya tiene un invariante sobre eso: **una puerta que se pasa sola no es una
   puerta**.
2. No hace falta. Se levanta un **segundo proceso del bridge** que, antes de
   servir, se parchea a sí mismo. Ningún fichero de producción cambia, y los dos
   prompts conviven en la misma máquina **en el mismo momento**, que es lo que
   permite alternar de verdad.

Y se alterna porque la alternativa es medir un bloque y luego el otro: entre
bloques la máquina se calienta, la swap se llena y el modelo se descarga, y la
diferencia que se ve es ese ruido. La lección A-080 lo dice sin rodeos: *medir dos
prompts alternando, o medir ruido*.

## El prompt «viejo» se reconstruye, no se adivina

El bloque se copia literalmente del código anterior al commit `0669557`, con
`git show 0669557:bridge/app/autopilot.py`. Si algún día alguien cambia ese
formato, este script deja de reproducirlo y hay que rehacerlo: que es preferible
a que se degrade en silencio y dé un número con el mismo aspecto que un bueno.

    .venv/bin/python bin/lab/medir-prompt-ab.py [N_PAREJAS] [proyecto]

Necesita Ollama y un bridge principal en :8000. Arranca él el suyo en :8001 y lo
para al terminar.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

RAIZ_BRIDGE = Path(__file__).resolve().parents[2]
LAB = 8001          # el bridge del grupo con lecciones; el de :8000 va sin ellas
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
PROYECTO = sys.argv[2] if len(sys.argv) > 2 else "aegis"
PROMPT = ("Usa la tool projects_list para listar los proyectos del workspace y "
          "dime cuántos hay.")

#: El launcher del bridge del laboratorio. Se parchea a sí mismo ANTES de servir,
#: así que el código de producción no sabe que este proceso existe.
LAUNCHER = f'''
import sys, json
sys.path.insert(0, {str(RAIZ_BRIDGE)!r})
from app import autopilot, lecciones as _lecciones

def _con_lecciones(project, encargo=""):
    """El bloque de antes del 0669557, copiado. Ver `git show`."""
    if not project:
        return ""
    indice = _lecciones.indice(project)
    if not indice:
        return ""
    partes = [
        "LECCIONES DE ESTE PROYECTO (índice, no el texto entero). Si una encaja "
        "con lo que te toca, pídela con la tool `lecciones(alias, tema)` antes de "
        "actuar — o léela aquí si va entera:\\n" + indice,
    ]
    encaja = _lecciones.relevantes(project, encargo)
    if encaja:
        partes.append("La que más aplica a este encargo:\\n\\n" + encaja[0].como_texto())
    return "\\n\\n".join(partes)

autopilot.load_lessons = _con_lecciones

import uvicorn
from app.main import app
uvicorn.run(app, host="127.0.0.1", port={LAB}, log_level="warning")
'''


def token() -> str:
    for linea in (RAIZ_BRIDGE / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("AEGIS_API_KEY="):
            return linea.split("=", 1)[1].strip().strip("\"'")
    return ""


CAB = {"X-Aegis-Token": token()} if token() else {}


def tamano_prompt(puerto: int) -> int:
    """Lo que ve de verdad ese bridge. No se calcula: se pregunta por HTTP."""
    from app.autopilot import build_system_prompt  # noqa: PLC0415
    # El prompt del grupo A no se puede pedir al bridge B, así que se mide el
    # propio y se reporta como referencia; la comparación real es el runtime.
    return len(build_system_prompt("", PROYECTO, PROMPT, encargo=PROMPT))


def un_run(puerto: int) -> dict:
    inicio = time.monotonic()
    r = httpx.post(f"http://127.0.0.1:{puerto}/autopilot/start", json={
        "project": PROYECTO, "max_steps": 3, "prompt": PROMPT,
    }, headers=CAB, timeout=60)
    r.raise_for_status()
    rid = r.json()["run_id"]
    for _ in range(180):
        d = httpx.get(f"http://127.0.0.1:{puerto}/autopilot/{rid}",
                      headers=CAB, timeout=30).json()
        if d.get("status") in ("completed", "failed"):
            break
        time.sleep(1)
    return {"ok_tool": bool([t for t in d.get("trace", []) if t.get("tool")]),
            "s": round(time.monotonic() - inicio, 1),
            "fin": d.get("fin")}


def arrancar_lab(tmp: Path) -> subprocess.Popen:
    """El bridge del grupo con lecciones, en :8001, con su propia `data/`."""
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCHER],
        cwd=str(RAIZ_BRIDGE),
        # Una `data/` aparte: si compartiera SQLite con el bridge principal se
        # pelean por el lock, y un run que falla por un lock no mide nada.
        env={**os.environ,
             "LOG_DIR": str(tmp / "logs"), "MEMORY_DIR": str(tmp / "memoria"),
             "AEGIS_AGENDA_DB": str(tmp / "agenda.sqlite3"),
             "AEGIS_AUTONOMIA_DB": str(tmp / "autonomia.sqlite3"),
             "AEGIS_BRIDGE_TAILNET_IP": "", "AEGIS_PHONE_SERIAL": ""},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(60):
        time.sleep(1)
        if proc.poll() is not None:
            raise SystemExit(f"el bridge del laboratorio murió al arrancar:\n"
                             f"{proc.stderr.read().decode()[-1500:]}")
        try:
            if httpx.get(f"http://127.0.0.1:{LAB}/health", timeout=3).status_code == 200:
                return proc
        except httpx.HTTPError:
            continue
    proc.kill()
    raise SystemExit("el bridge del laboratorio no respondió en 60 s")


def resumen(filas: list[dict]) -> tuple[int, float | None]:
    ok = sum(1 for f in filas if f["ok_tool"])
    tiempos = [f["s"] for f in filas]
    return ok, (statistics.median(tiempos) if tiempos else None)


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="aegis-lab-ab-"))
    print(f"A/B del prompt · {N} pares alternados · proyecto={PROYECTO}")
    print(f"  grupo SIN lecciones → :8000 (el bridge de producción)")
    print(f"  grupo CON lecciones → :{LAB} (este script lo levanta y lo para)\n")

    lab = arrancar_lab(tmp)
    try:
        print(f"{'#':<3} {'sin':>6} {'con':>6} {'s sin':>7} {'s con':>7}")
        print("-" * 40)
        filas_sin, filas_con = [], []
        for i in range(N):
            # **El orden alterna**, no siempre el mismo grupo primero: si el
            # modelo se va calentando a lo largo de la medición, siempre-A primero
            # convierte esa deriva en un sesgo del grupo A entero.
            if i % 2 == 0:
                a, b = un_run(8000), un_run(LAB)
            else:
                b, a = un_run(LAB), un_run(8000)
            filas_sin.append(a)
            filas_con.append(b)
            print(f"{i+1:<3} {'SI' if a['ok_tool'] else 'NO':>6} "
                  f"{'SI' if b['ok_tool'] else 'NO':>6} {a['s']:>7} {b['s']:>7}")

        ok_sin, med_sin = resumen(filas_sin)
        ok_con, med_con = resumen(filas_con)
        print("-" * 40)
        print(f"tool-calling   sin lecciones: {ok_sin}/{N}"
              f"     con lecciones: {ok_con}/{N}")

        def stat(nombre, filas):
            ts = sorted(f["s"] for f in filas)
            return (f"mín {ts[0]:.1f} · mediana {statistics.median(ts):.1f} · "
                    f"máx {ts[-1]:.1f}")

        print(f"latencia sin   {stat('sin', filas_sin)}")
        print(f"latencia con   {stat('con', filas_con)}")
        if med_sin and med_con:
            print(f"diferencia de mediana: {med_con - med_sin:+.1f} s "
                  f"({round(100 * (med_con - med_sin) / med_sin):+} %)")

        # **El ruido, por escrito.** Sin esto, una diferencia de 15 s con un
        # máximo de 137 s se lee como un hallazgo y no lo es: el primer run de
        # cada grupo carga el modelo y cuesta el doble. Si la diferencia es menor
        # que la dispersión, el honesto es decir «no se puede afirmar con estos
        # datos», y eso también es un resultado.
        if med_sin and med_con:
            overlap = min(f["s"] for f in filas_sin) < max(f["s"] for f in filas_con)
            if abs(med_con - med_sin) < statistics.stdev(
                    [f["s"] for f in filas_sin] + [f["s"] for f in filas_con]) / 2:
                print("\nAVISO: la diferencia es menor que la dispersión "
                      "acumulada. Con más pares se puede afirmar; con estos, no.")
        print(json.dumps({"n": N, "sin": {"tool": f"{ok_sin}/{N}", "med": med_sin},
                          "con": {"tool": f"{ok_con}/{N}", "med": med_con}},
                         ensure_ascii=False))
    finally:
        lab.terminate()
        try:
            lab.wait(timeout=10)
        except subprocess.TimeoutExpired:
            lab.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())