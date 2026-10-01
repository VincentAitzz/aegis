"""Esquemas Pydantic del API del bridge (contrato REST + WS hacia la app)."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: Roles que el bridge acepta. Aegis tiene UN agente. `orchestrator` se acepta
#: solo por compatibilidad con apps viejas: antes ambos valores terminaban en el
#: mismo modelo (Hermes caía a su default), así que era configuracion muerta
#: que solo sugeria un equipo que no existia.
_LEGACY_AGENTS = {"orchestrator"}
_CANONICAL_AGENT = "worker"
_KNOWN_AGENTS = {"worker"} | _LEGACY_AGENTS


class TaskIn(BaseModel):
    """Petición de lanzar una tarea en el agente de Aegis."""
    agent: Literal["worker", "orchestrator"] = _CANONICAL_AGENT
    prompt: str = Field(min_length=1, max_length=1_000_000)
    instructions: Optional[str] = None
    title: Optional[str] = None
    #: Alias del proyecto del workspace. Carga su ficha y su memoria; sin esto
    #: el agente razona sin saber de qué se trata, que es justo lo que el
    #: método prohíbe. Ver `app/fichas.py`.
    project: Optional[str] = None

    @field_validator("agent", mode="before")
    @classmethod
    def _un_unico_agente(cls, value: Any) -> Any:
        if isinstance(value, str) and value in _LEGACY_AGENTS:
            return _CANONICAL_AGENT
        return value


class TaskOut(BaseModel):
    """Respuesta de creación de tarea. run_id = id del run en Hermes."""
    run_id: str
    agent: str
    status: str
    session_id: Optional[str] = None


class TaskStatus(BaseModel):
    run_id: str
    status: str
    agent: str
    final_text: Optional[str] = None
    pending_approval: Optional[bool] = False


class ApprovalIn(BaseModel):
    decision: Literal["approve", "deny"]
    comment: Optional[str] = None


class SteerIn(BaseModel):
    text: str = Field(min_length=1)


class WsMessageIn(BaseModel):
    type: Literal["subscribe", "create_task", "approve", "steer", "stop"]
    run_id: Optional[str] = None
    task: Optional[TaskIn] = None
    decision: Optional[str] = None
    text: Optional[str] = None


class EventOut(BaseModel):
    """Evento normalizado empujado al WebSocket de la app."""
    type: str
    task_id: str
    agent: str
    at: str
    payload: dict[str, Any] = Field(default_factory=dict)