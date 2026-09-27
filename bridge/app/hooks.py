"""Reacciones a eventos terminales de los runs: construir el episodio y el error.

Convierte cada `task.done` / `task.failed` en la nueva entrada de contexto del
sistema: un episodio de memoria (éxito o pitfall) más un registro de
telemetría con la traza del fallo. Error y stack trace quedan en el log
estructurado del run (`data/logs/runs/<run_id>.jsonl`).
"""

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


async def build_success_episode(run_id: str) -> dict:
    state = _run_state(run_id)
    try:
        remote = await hermes.run_status(run_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("run_status %s falló: %s", run_id, exc)
        remote = {}
    final = (remote.get("final_text") or remote.get("output")
             or (remote.get("data") or {}).get("final_response") or "")
    return {
        "run_id": run_id,
        "agent": state.get("agent", ""),
        "outcome": "success",
        "prompt": state.get("prompt", ""),
        "summary": " ".join(final.split())[:400],
        "text": final[:4000],
        "code": extract_code(final),
        "error": "",
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