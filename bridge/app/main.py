"""Bridge Aegis — puerta única para el móvil hacia Hermes (REST + WebSocket)."""

import contextlib
import logging
import socket

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .hermes_client import hermes
from .llm import ollama
from .models import ApprovalIn, EventOut, SteerIn, TaskIn, TaskOut, TaskStatus, WsMessageIn
from .relay import relay

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aegis.bridge")

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("bridge arriba (bind %s:%s -> hermes %s)",
             settings.bridge_bind, settings.bridge_port, settings.hermes_base_url)
    yield
    await hermes.aclose()


app = FastAPI(title="Aegis Bridge", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _agents() -> dict[str, str]:
    return {"worker": settings.agent_worker, "orchestrator": settings.agent_orchestrator}


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
    }


async def asyncio_gather_health():
    import asyncio
    h = await hermes.health()
    models = await ollama.list_models()
    return h, True, [m.get("name") for m in models]


@app.get("/models")
async def models() -> dict:
    import asyncio
    tags, loaded = await asyncio.gather(ollama.list_models(), ollama.loaded_models())
    return {"available": [m.get("name") for m in tags],
            "loaded": [m.get("name") for m in loaded]}


# -- tareas -------------------------------------------------------------------
@app.post("/tasks", response_model=TaskOut)
async def create_task(task: TaskIn) -> TaskOut:
    model = _agents()[task.agent]
    # asegura el modelo cargado (warm-up no bloqueante)
    import asyncio
    await ollama.ensure_model(model)
    created = await hermes.create_run(model, task.prompt, task.instructions)
    run_id = created.get("run_id") or created.get("id")
    if not run_id:
        raise RuntimeError(f"Hermes no devolvió run_id: {created}")
    # Arranca el lector SSE YA: el móvil se suscribe tarde (2-8s de malla) y
    # recibe el historial completo vía el buffer de replay del relay.
    await relay.ensure_reader(run_id, task.agent)
    return TaskOut(run_id=run_id, agent=task.agent,
                   status=created.get("status", "queued"),
                   session_id=created.get("session_id"))


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


# -- canal bidireccional (WebSocket) -------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    import asyncio
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
                model = _agents()[task.agent]
                await ollama.ensure_model(model)
                created = await hermes.create_run(model, task.prompt, task.instructions)
                run_id = created.get("run_id") or created.get("id")
                await relay.subscribe(ws, run_id, task.agent)
                await ws.send_text(EventOut(type="task.created", task_id=run_id, agent=task.agent,
                                            at="", payload=created).model_dump_json())
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