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
        summary = f"tools={tools}; respuesta={final}"
    else:
        # Se guarda marcado, pero `recall` no lo inyecta: si no lo inyecta, un
        # "OK" sin tool deja de ser un ejemplo a imitar.
        summary = ("SIN EVIDENCIA: el run terminó sin ejecutar ninguna tool; "
                   f"respuesta del modelo={final}")
    return {
        "run_id": run_id,
        "agent": state.get("agent", ""),
        "outcome": "success" if tools else "sin_evidencia",
        "tools": tools,
        "prompt": state.get("prompt", ""),
        "summary": " ".join(summary.split())[:400],
        "text": final[:4000] if tools else "",
        "code": extract_code(final),
        "error": "" if tools else "run sin tool ejecutada",
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
            telemetry.record("INFO", "episode.saved", run_id=run_id,
                             outcome="success", text_len=len(episode.get("text") or ""))
        elif ev.type == "task.failed":
            episode = await build_failure_episode(run_id, ev.payload)
            mem = get_memory()
            if mem:
                await mem.remember(episode)
            telemetry.run_failed(run_id, episode["error"])
    except Exception as exc:  # noqa: BLE001 — el hook nunca debe romper el run
        log.warning("hook de memoria falló para %s: %s", run_id, exc)