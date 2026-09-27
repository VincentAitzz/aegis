"""Telemetría estructurada del bridge (capa de observabilidad).

Escribe logs JSON (JSONL) en dos planos:

  * `data/logs/bridge.jsonl`        — cada evento/error del bridge, con duración.
  * `data/logs/runs/<run_id>.jsonl` — secuencia completa de eventos de un run,
    con hora, tipo, agente y payload, para depurar y re-alimentar al agente.

Cuando un run falla, `run_failed()` graba error + traza de pila en ambos planos;
ese archivo concreto es lo que el flujo de memoria usa como episodio negativo
(ver `app/hooks.py`).
"""

import contextlib
import json
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("aegis.bridge.telemetry")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Telemetry:
    """Emisor de eventos JSONL. Hilo-seguro (apéndice atómico con lock)."""

    def __init__(self, base_dir: str = "data/logs") -> None:
        self.base_dir = base_dir
        self._lock = threading.Lock()
        self.bridge_path = os.path.join(base_dir, "bridge.jsonl")
        self.runs_dir = os.path.join(base_dir, "runs")
        os.makedirs(self.runs_dir, exist_ok=True)

    # -- escritura ----------------------------------------------------------
    def _append(self, path: str, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def record(self, level: str, event: str, run_id: Optional[str] = None, **fields: Any) -> None:
        rec: dict[str, Any] = {"at": _iso(), "level": level, "event": event}
        if run_id:
            rec["run_id"] = run_id
        rec.update(fields)
        self._append(self.bridge_path, rec)

    # -- plano por-run ------------------------------------------------------
    def run_path(self, run_id: str) -> str:
        return os.path.join(self.runs_dir, f"{run_id}.jsonl")

    def run_event(self, run_id: str, event_type: str, agent: str,
                  at_event: str, payload: dict[str, Any]) -> None:
        """Registra un evento normalizado del relay en el log del run."""
        self._append(self.run_path(run_id), {
            "at": _iso(),
            "run_id": run_id,
            "event": event_type,
            "agent": agent,
            "at_run": at_event,
            "payload": payload,
        })

    def run_span(self, run_id: str, metric: str, **values: float) -> None:
        """Métricas del run (tiempos de evento, duración total, etc.)."""
        rec: dict[str, Any] = {"at": _iso(), "run_id": run_id, "metric": metric}
        rec.update(values)
        self._append(self.run_path(run_id), rec)

    def run_failed(self, run_id: str, error: str) -> None:
        """Registra el fallo con traza de pila en el log del run y el global."""
        detail = traceback.format_exc() or ""
        self.record("ERROR", "run.failed", run_id=run_id, error=error, trace=detail)
        self._append(self.run_path(run_id), {
            "at": _iso(), "run_id": run_id, "event": "run.failed.detail",
            "error": error, "trace": detail,
        })


# Instancia global; `configure()` la re-construye con el LOG_DIR de .env.
telemetry = Telemetry()


def configure(base_dir: str) -> None:
    global telemetry
    telemetry = Telemetry(base_dir)
    log.info("telemetría JSON en %s (runs: %s)", telemetry.bridge_path, telemetry.runs_dir)


@contextlib.contextmanager
def stopwatch() -> Any:
    """Cronómetro ligero: `with stopwatch() as ms:` → `ms()` devuelve ms transcurridos."""
    start = time.perf_counter()

    def elapsed() -> float:
        return (time.perf_counter() - start) * 1000.0

    yield elapsed