"""Bridge Aegis — puerta única para el móvil hacia Hermes (REST + WebSocket)."""

import asyncio
import contextlib
import json
import logging
import socket
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import hooks
from .autopilot import run_autopilot
from .config import get_settings
from .hermes_client import hermes
from .llm import ollama
from .memory import get_memory, init_memory
from .models import ApprovalIn, EventOut, SteerIn, TaskIn, TaskOut, TaskStatus, WsMessageIn
from .relay import relay
from .telemetry import configure as configure_telemetry
from .telemetry import stopwatch, telemetry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aegis.bridge")

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry(settings.log_dir)
    init_memory(settings)                       # 'cerebro' del proyecto (capa 3)
    relay.on_terminal = hooks.on_terminal_event  # episodios + telemetría al terminar
    log.info("bridge arriba (bind %s:%s -> hermes %s)",
             settings.bridge_bind, settings.bridge_port, settings.hermes_base_url)
    yield
    await hermes.aclose()


app = FastAPI(title="Aegis Bridge", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _store_bytes() -> int:
    """Bytes que ocupa el store local de memoria (Chroma + grafo)."""
    total = 0
    for carpeta in (Path(settings.memory_dir),):
        if carpeta.is_dir():
            for f in carpeta.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
    return total


def _agents() -> dict[str, str]:
    return {"worker": settings.agent_worker, "orchestrator": settings.agent_orchestrator}


async def _memory_context(prompt: str) -> str:
    """Recupera experiencias previas y las devuelve listas para inyectar."""
    mem = get_memory()
    if not mem:
        return ""
    try:
        with stopwatch() as ms:
            results = await mem.recall(prompt)
            ctx = mem.render_context(results)
        if ctx:
            telemetry.record("INFO", "memory.recall", prompt_len=len(prompt),
                             ms=round(ms(), 1), chars=len(ctx))
        return ctx
    except Exception as exc:  # noqa: BLE001 — la memoria nunca bloquea la tarea
        log.warning("recall de memoria falló: %s", exc)
        return ""


async def _submit_task(agent: str, prompt: str,
                       instructions: Optional[str] = None) -> TaskOut:
    """Crea un run en Hermes con el contexto de memoria inyectado (capa 3)."""
    model = _agents()[agent]
    # warm-up no bloqueante del modelo
    await ollama.ensure_model(model)
    # experiencias previas → instructions extra para el agente
    effective = instructions
    ctx = await _memory_context(prompt)
    if ctx:
        effective = f"{instructions}\n\n{ctx}" if instructions else ctx
    created = await hermes.create_run(model, prompt, effective)
    run_id = created.get("run_id") or created.get("id")
    if not run_id:
        raise RuntimeError(f"Hermes no devolvió run_id: {created}")
    # Arranca el lector SSE YA: el móvil se suscribe tarde (2-8s de malla) y
    # recibe el historial completo vía el buffer de replay del relay.
    relay.set_prompt(run_id, prompt)
    await relay.ensure_reader(run_id, agent)
    return TaskOut(run_id=run_id, agent=agent,
                   status=created.get("status", "queued"),
                   session_id=created.get("session_id"))


# -- health / estado ----------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    hermes_h, ollama_cap, models = await asyncio_gather_health()
    hostname = socket.gethostname()
    return {
        "status": "ok",
        "bridge": {"host": hostname, "bind": settings.bridge_bind, "port": settings.bridge_port},
        "hermes": hermes_h,
        "ollama": {"ok": ollama_cap, "models": models},
        "agents": list(_agents().keys()),
        "memory": {**(get_memory().status() if get_memory() else {}),
                   # El tamaño del store es lo que decide si el cerebro debería
                   # mudarse a Postgres. Medirlo es lo que hace que la pregunta se
                   # responda con un número y no con una corazonada.
                   "store_bytes": _store_bytes()},
    }


async def asyncio_gather_health():
    h = await hermes.health()
    models = await ollama.list_models()
    return h, True, [m.get("name") for m in models]


@app.get("/models")
async def models() -> dict:
    tags, loaded = await asyncio.gather(ollama.list_models(), ollama.loaded_models())
    return {"available": [m.get("name") for m in tags],
            "loaded": [m.get("name") for m in loaded]}


# -- tareas -------------------------------------------------------------------
@app.post("/tasks", response_model=TaskOut)
async def create_task(task: TaskIn) -> TaskOut:
    return await _submit_task(task.agent, task.prompt, task.instructions)


@app.get("/tasks/{run_id}", response_model=TaskStatus)
async def task_status(run_id: str) -> TaskStatus:
    state = relay.status(run_id) or {}
    try:
        remote = await hermes.run_status(run_id)
    except Exception as exc:  # noqa: BLE001
        remote = {"status": "unknown", "error": str(exc)}
    return TaskStatus(run_id=run_id,
                      status=state.get("status") or remote.get("status", "unknown"),
                      agent=state.get("agent", ""),
                      final_text=(remote.get("final_text") or remote.get("output")
                                  or (remote.get("data") or {}).get("final_response")),
                      pending_approval=state.get("status") == "awaiting_approval")


@app.post("/tasks/{run_id}/approval")
async def approve(run_id: str, body: ApprovalIn) -> dict:
    return await hermes.approve(run_id, body.decision, body.comment)


@app.post("/tasks/{run_id}/steer")
async def steer(run_id: str, body: SteerIn) -> dict:
    return await hermes.steer(run_id, body.text)


@app.post("/tasks/{run_id}/stop")
async def stop(run_id: str) -> dict:
    return await hermes.stop(run_id)


class AutopilotIn(BaseModel):
    prompt: str
    model: Optional[str] = None
    max_steps: int = 6
    project: Optional[str] = None
    instructions: Optional[str] = None
    remember: bool = True
    # Con `verificar`, cada escritura pasa por el verificador del proyecto y el
    # run se detiene si el rojo no mejora. Sin esto el run termina cuando el
    # modelo deja de pedir tools, que no dice nada del código.
    verificar: bool = False
    que: str = "check"


class AutopilotOut(BaseModel):
    model: str
    answer: str
    steps: int
    trace: list[dict]
    project: Optional[str] = None
    # Por qué terminó el run: sin_tools | respuesta_vacia | max_steps | puerta.
    # "agotó los pasos" y "el modelo respondió" se confundían, y ese dato es el
    # que mide si el bucle funciona.
    fin: str = "max_steps"


@app.post("/autopilot", response_model=AutopilotOut)
async def autopilot(body: AutopilotIn) -> AutopilotOut:
    """Ejecuta una tarea con el bucle modelo→aegis-ops, sin depender de tool_calls.

    Es la vía fiable de autonomía: el modelo local decide QUÉ tool usar y el
    bridge la EJECUTA de verdad, con lista blanca y traza auditable.

    El run se guarda como episodio: con `project` se inyectan las lecciones
    curadas del repo y el recall, de modo que una corrección escrita a mano
    llegue sola a los intentos siguientes.
    """
    project = body.project or ""
    ctx = ""
    if project:
        ctx = await _memory_context(body.prompt)
    puerta = None
    if body.verificar:
        from .verifier import gate as _gate
        puerta = _gate(project, body.que)
    result = await run_autopilot(
        body.prompt,
        ollama_url=settings.ollama_base_url,
        model=body.model or settings.autopilot_model,
        max_steps=max(1, min(body.max_steps, 16)),
        instructions=body.instructions or "",
        project=project,
        memory=ctx,
        gate=puerta,
    )
    log.info("autopilot: %d pasos, %d tools ejecutadas (proyecto=%s)",
             result["steps"], sum(1 for t in result["trace"] if t.get("tool")),
             project or "-")
    # La traza es la evidencia. El `answer` del modelo no lo es: se ha medido que
    # llega a reportar éxito sin haber escrito nada (lessons/aegis.md A-013).
    for paso in result["trace"]:
        if paso.get("gate"):
            telemetry.record("INFO", "autopilot.gate", run_id=f"autopilot-{int(time.time())}",
                             paso=paso["step"], tool=paso.get("tool"),
                             **{k: v for k, v in paso["gate"].items()
                                if k in ("ok", "problemas", "delta", "mismo_error", "stop")})
    if body.remember and get_memory():
        tools_used = [t for t in result["trace"] if t.get("tool")]
        # Una tool puede "funcionar" y aun así rechazar la edición (guardarraíl de
        # sintaxis, whitelist). Eso es un fallo del agente, no un acierto: si no se
        # cuenta, el recall le va a enseñar los runs como exitosos.
        failures = [t for t in tools_used
                    if t.get("ok") is False
                    or "RECHAZADO" in str(t.get("result", ""))
                    or "no se encontró" in str(t.get("result", ""))
                    or "ERROR:" in str(t.get("result", ""))]
        used = [t["tool"] for t in tools_used]
        await get_memory().remember({
            "run_id": f"autopilot-{int(time.time())}",
            "agent": "autopilot",
            "outcome": "failed" if failures else "success",
            "prompt": f"[{project}] {body.prompt}".strip(),
            "summary": f"tools={used or 'ninguna'}; pasos={result['steps']}; "
                       f"rechazos={len(failures)}; respuesta={result['answer'][:200]}",
            "text": json.dumps(result["trace"], ensure_ascii=False)[:4000],
            "code": [],
            "error": "; ".join(str(t.get("result"))[:200] for t in failures),
            "at": "",
        })
    return AutopilotOut(project=project or None, **result)


# -- canal bidireccional (WebSocket) -------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("cliente WS conectado")
    try:
        while True:
            raw = await ws.receive_text()
            msg = WsMessageIn.model_validate_json(raw)
            if msg.type == "subscribe":
                if not msg.run_id:
                    await ws.send_text(EventOut(type="error", task_id="", agent="",
                                                at="", payload={"error": "run_id requerido"}).model_dump_json())
                    continue
                agent = (relay.status(msg.run_id) or {}).get("agent", "worker")
                await relay.subscribe(ws, msg.run_id, agent)
                # estado actual inmediato
                await ws.send_text(EventOut(type="status.changed", task_id=msg.run_id, agent=agent,
                                            at="", payload={"status": "subscribed"}).model_dump_json())
            elif msg.type == "create_task":
                task = msg.task or TaskIn()
                out = await _submit_task(task.agent, task.prompt, task.instructions)
                run_id = out.run_id
                await relay.subscribe(ws, run_id, task.agent)
                await ws.send_text(EventOut(type="task.created", task_id=run_id, agent=task.agent,
                                            at="", payload=out.model_dump()).model_dump_json())
            elif msg.type == "approve" and msg.run_id and msg.decision:
                result = await hermes.approve(msg.run_id, msg.decision, msg.text)
                await ws.send_text(EventOut(type="approval.resolved", task_id=msg.run_id,
                                            agent=(relay.status(msg.run_id) or {}).get("agent", ""),
                                            at="", payload=result).model_dump_json())
            elif msg.type == "steer" and msg.run_id and msg.text:
                result = await hermes.steer(msg.run_id, msg.text)
                await ws.send_text(EventOut(type="steer.sent", task_id=msg.run_id,
                                            agent=(relay.status(msg.run_id) or {}).get("agent", ""),
                                            at="", payload=result).model_dump_json())
            elif msg.type == "stop" and msg.run_id:
                result = await hermes.stop(msg.run_id)
                await ws.send_text(EventOut(type="task.stopped", task_id=msg.run_id,
                                            agent=(relay.status(msg.run_id) or {}).get("agent", ""),
                                            at="", payload=result).model_dump_json())
    except WebSocketDisconnect:
        log.info("cliente WS desconectado")
    except Exception as exc:  # noqa: BLE001
        log.warning("ws error: %s", exc)
    finally:
        await relay.unsubscribe(ws)