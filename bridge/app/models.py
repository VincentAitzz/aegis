"""Esquemas Pydantic del API del bridge (contrato REST + WS hacia la app)."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TaskIn(BaseModel):
    """Petición de lanzar una tarea en un agente de Hermes."""
    agent: Literal["worker", "orchestrator"] = "worker"
    prompt: str = Field(min_length=1, max_length=1_000_000)
    instructions: Optional[str] = None
    title: Optional[str] = None


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