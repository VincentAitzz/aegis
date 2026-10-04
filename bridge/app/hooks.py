"""Reacciones a eventos terminales de los runs: construir el episodio y el error.

Convierte cada `task.done` / `task.failed` en la nueva entrada de contexto del
sistema: un episodio de memoria (éxito o pitfall) más un registro de
telemetría con la traza del fallo. Error y stack trace quedan en el log
estructurado del run (`data/logs/runs/<run_id>.jsonl`).
"""

import json
import logging
import re

from .hermes_client import hermes
from .models import EventOut
from .telemetry import telemetry

log = logging.getLogger("aegis.bridge.hooks")

_CODE_FENCE = re.compile(r"```[A-Za-z0-9_-]*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> list[str]:
    if not text:
        return []
    return [b.strip() for b in _CODE_FENCE.findall(text)]


def _run_state(run_id: str) -> dict:
    from .relay import relay as relay_inst
    return relay_inst.status(run_id) or {}


def tools_executed(run_id: str) -> list[str]:
    """Tools que el run ejecutó de verdad, leídas de su traza.

    El veredicto de un run no lo da el texto del modelo: un 7B responde "OK"
    sin haber llamado a nada, y guardar eso como `success` envenena el recall
    (ver A-016). Sin tool ejecutada no hay nada que enseñarle al agente.
    """
    path = telemetry.run_path(run_id)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    names: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or '"tool.completed"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") != "tool.completed":
            continue
        data = (event.get("payload") or {}).get("data") or {}
        tool = data.get("tool")
        if not tool or data.get("error"):
            continue
        if tool not in names:
            names.append(tool)
    return names


async def build_success_episode(run_id: str) -> dict:
    state = _run_state(run_id)
    try:
        remote = await hermes.run_status(run_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("run_status %s falló: %s", run_id, exc)
        remote = {}
    final = (remote.get("final_text") or remote.get("output")
             or (remote.get("data") or {}).get("final_response") or "")
    tools = tools_executed(run_id)
    if tools:
        # Nunca ha pasado desde que el autopilot es el único que ejecuta tools
        # (2026-10-04), pero el camino se queda: si un día vuelve a haber un
        # ejecutor con tools, el veredicto tiene que ser el de la traza.
        summary = f"tools={tools}; respuesta={final}"
        outcome, error, texto = "success", "", final[:4000]
    else:
        # `conversacion`: este run respondió y no hizo nada, porque su
        # motor no tiene tools (`platform_toolsets.api_server: []` en Hermes).
        #
        # Antes se marcaba `sin_evidencia`, y eso era verdad pero **envejecía
        # mal**: cada conversación dejaba en el almacén un episodio que no
        # era ni un éxito ni un fallo, y la suma de esos `sin_evidencia` es
        # exactamente el veneno que A-016 midió —un `success` sin evidencia de
        # ejecución— con otro nombre.
        #
        # La diferencia importa para lo que viene después: `sin_evidencia` decía
        # «este run no hizo nada y debería haberlo hecho». Esto dice «este run
        # no podía hacer nada, y no era su trabajo». El recall acepta solo
        # `success`, así que ninguno se inyecta; el punto es que el almacén
        # pueda distinguir una cosa de la otra al mirarlo.
        #
        # **Y el nombre tiene que caber en 16 caracteres**: `sqlite_graph.py`
        # trunca `outcome` a `[:16]` al guardar, y `solo_conversacion` salía
        # como `solo_conversacio` — un valor corrupto que nadie iba a detectar
        # porque es texto, no un número. Un identificador truncado en silencio es
        # peor que uno largo: parece que funciona.
        summary = f"conversación, sin tools por diseño: respuesta={final}"
        outcome, error, texto = "conversacion", "sin tools: es el motor de conversación", ""
    return {
        "run_id": run_id,
        "agent": state.get("agent", ""),
        "outcome": outcome,
        "tools": tools,
        "prompt": state.get("prompt", ""),
        "summary": " ".join(summary.split())[:400],
        "text": texto,
        "code": extract_code(texto),
        "error": error,
        "at": "",
    }


async def build_failure_episode(run_id: str, payload: dict) -> dict:
    state = _run_state(run_id)
    error = str(payload.get("error") or "error desconocido")[:1500]
    return {
        "run_id": run_id,
        "agent": state.get("agent", ""),
        "outcome": "failed",
        "prompt": state.get("prompt", ""),
        "summary": f"FALLO: {error}",
        "text": error,
        "code": [],
        "error": error,
        "at": "",
    }


async def on_terminal_event(ev: EventOut) -> None:
    """Hook del relay: persiste el episodio en memoria y la telemetría del run."""
    run_id = ev.task_id
    try:
        from .memory import get_memory
        if ev.type == "task.done":
            episode = await build_success_episode(run_id)
            mem = get_memory()
            if mem:
                await mem.remember(episode)
            # El `outcome` va el que salió del episodio. Antes ponía "success"
            # aquí fijo, así que la telemetría decía «success» para un episodio
            # que no lo era: un panel que miente sobre el dato que sirve para
            # medir es peor que no tener panel.
            telemetry.record("INFO", "episode.saved", run_id=run_id,
                             outcome=episode.get("outcome", ""),
                             text_len=len(episode.get("text") or ""))
        elif ev.type == "task.failed":
            episode = await build_failure_episode(run_id, ev.payload)
            mem = get_memory()
            if mem:
                await mem.remember(episode)
            telemetry.run_failed(run_id, episode["error"])
    except Exception as exc:  # noqa: BLE001 — el hook nunca debe romper el run
        log.warning("hook de memoria falló para %s: %s", run_id, exc)