"""Relay: multiplexa tareas en ejecución de Hermes y normaliza eventos SSE→WS."""

import asyncio
import contextlib
import logging
import re
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocket

from .hermes_client import hermes
from .models import EventOut
from .telemetry import telemetry

log = logging.getLogger("aegis.bridge.relay")

# Normalización de nombres de evento SSE de Hermes → tipos amigables de la app.
_EVENT_KIND: list[tuple[re.Pattern, str]] = [
    (re.compile(r"tool.*started|tool.*start", re.I), "tool.started"),
    (re.compile(r"tool.*complet", re.I), "tool.completed"),
    (re.compile(r"approval|clarif|awaiting", re.I), "approval.request"),
    (re.compile(r"run.*completed|resp.*completed", re.I), "task.done"),
    (re.compile(r"run.*failed|resp.*failed", re.I), "task.failed"),
    (re.compile(r"run.*cancel|run.*stop", re.I), "task.stopped"),
    (re.compile(r"delta|output_text|chunk", re.I), "text.delta"),
    (re.compile(r"status", re.I), "status.changed"),
]

_TERMINAL = {"task.done", "task.failed", "task.stopped"}


def normalize_event(run_id: str, agent: str, event: str, data: dict[str, Any]) -> EventOut:
    # Hermes envuelve los eventos reales anidados: {event: "message", data: {"event": "run.completed", ...}}
    nested = data.get("event") or data.get("type")
    haystack = f"{event} {nested}" if nested else event
    kind = "raw.progress"
    for pat, t in _EVENT_KIND:
        if pat.search(haystack):
            kind = t
            break
    return EventOut(type=kind, task_id=run_id, agent=agent,
                    at=f"{time.time():.3f}",
                    payload={"event": nested or event, "data": data})


class Relay:
    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}      # run_id -> sockets
        self._readers: set[str] = set()                 # run_ids con lector activo
        self._tasks: dict[str, dict[str, Any]] = {}     # run_id -> estado local
        self._history: dict[str, list[EventOut]] = {}   # run_id -> eventos ya publicados (replay)
        self._lock = asyncio.Lock()
        # Hook opcional al terminar un run (main.py lo engancha a memoria/telemetría).
        self.on_terminal: Optional[Callable[[EventOut], Awaitable[None]]] = None

    def set_prompt(self, run_id: str, prompt: str) -> None:
        """Guarda el prompt del run: la memoria lo necesita al construir episodios."""
        self._tasks.setdefault(run_id, {"run_id": run_id, "status": "queued"})["prompt"] = prompt

    # -- suscripción ---------------------------------------------------------
    async def subscribe(self, ws: WebSocket, run_id: str, agent: str) -> None:
        async with self._lock:
            self._subs.setdefault(run_id, set()).add(ws)
            replay = list(self._history.get(run_id, ()))
            status = self._tasks.get(run_id, {}).get("status")
        # Un suscriptor tardío recibe el historial anterior completo
        # (la app deduplica por contenido, el solapamiento es seguro).
        for ev in replay:
            await self._safe_send(ws, ev)
        self._tasks.setdefault(run_id, {"run_id": run_id, "agent": agent, "status": status or "queued"})
        await self.ensure_reader(run_id, agent)

    async def ensure_reader(self, run_id: str, agent: str) -> None:
        """Arranca el lector SSE del run si no está corriendo y aún no terminó."""
        async with self._lock:
            _ = self._tasks.setdefault(run_id, {"run_id": run_id, "agent": agent, "status": "queued"})
            status = self._tasks[run_id].get("status")
            if run_id in self._readers or status in {"completed", "failed", "stopped"}:
                return
            self._readers.add(run_id)
        asyncio.create_task(self._reader(run_id, agent))

    async def unsubscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            for run_id, sockets in list(self._subs.items()):
                sockets.discard(ws)
                if not sockets:
                    self._subs.pop(run_id, None)
                    self._readers.discard(run_id)  # lector finaliza al ver cola vacía

    async def publish_to(self, run_id: str, event: EventOut) -> None:
        sockets = list(self._subs.get(run_id, ()))
        dead: list[WebSocket] = []
        for ws in sockets:
            if not await self._safe_send(ws, event):
                dead.append(ws)
        # Remueve sockets muertos del índice.
        for ws in dead:
            sockets.remove(ws)
            for rid, s in list(self._subs.items()):
                s.discard(ws)

    @staticmethod
    async def _safe_send(ws: WebSocket, event: EventOut) -> bool:
        try:
            await ws.send_text(event.model_dump_json())
            return True
        except Exception:
            return False

    # -- lector de un run ------------------------------------------------------
    _HISTORY_MAX = 2000

    async def _reader(self, run_id: str, agent: str) -> None:
        log.info("lector SSE iniciado para run %s", run_id)
        started = time.perf_counter()
        try:
            async for raw in hermes.run_events(run_id):
                ev = normalize_event(run_id, agent, raw["event"], raw["data"])
                self._tasks[run_id]["status"] = _derive_status(ev, raw)
                # Historial con tope, para reintento de suscripción y runs finalizados.
                hist = self._history.setdefault(run_id, [])
                hist.append(ev)
                if len(hist) > self._HISTORY_MAX:
                    del hist[:len(hist) - self._HISTORY_MAX]
                before = time.perf_counter()
                await self.publish_to(run_id, ev)
                # Observabilidad: cada evento normalizado queda en el log del run.
                telemetry.run_event(run_id, ev.type, ev.agent, ev.at, ev.payload)
                telemetry.run_span(run_id, "event_exec_ms",
                                   event=ev.type, ms=round((time.perf_counter() - before) * 1000.0, 2))
                if ev.type in _TERMINAL:
                    telemetry.run_span(run_id, "run_duration_s",
                                       seconds=round(time.perf_counter() - started, 3))
                    if self.on_terminal:
                        try:
                            await self.on_terminal(ev)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("hook terminal para %s falló: %s", run_id, exc)
                    break
        except Exception as exc:  # noqa: BLE001
            log.warning("lector run %s terminó con error: %s", run_id, exc)
            await self.publish_to(run_id, EventOut(
                type="task.failed", task_id=run_id, agent=agent,
                at=f"{time.time():.3f}", payload={"error": str(exc)}))
        finally:
            self._readers.discard(run_id)

    def status(self, run_id: str) -> Optional[dict[str, Any]]:
        return self._tasks.get(run_id)


def _derive_status(ev: EventOut, raw: dict[str, Any]) -> str:
    status = raw.get("data", {}).get("status")
    if status:
        return status
    return {"task.done": "completed", "task.failed": "failed",
            "task.stopped": "stopped", "approval.request": "awaiting_approval"}.get(ev.type, status or "running")


relay = Relay()


@contextlib.asynccontextmanager
async def lifespan_guard():
    yield
    await hermes.aclose()
    for coro in asyncio.all_tasks():
        if coro is not asyncio.current_task() and coro.get_name() == "aegis-relay-reader":
            coro.cancel()