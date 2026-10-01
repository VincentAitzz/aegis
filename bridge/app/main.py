"""Bridge Aegis — puerta única para el móvil hacia Hermes (REST + WebSocket)."""

import asyncio
import contextlib
import json
import logging
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import hooks
from .autopilot import run_autopilot
from .config import get_settings
from .fichas import context_for
from .hermes_client import hermes
from .llm import ollama
from .memory import get_memory, init_memory
from .method import method_context
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
    """Aegis tiene un solo agente. `worker` es el nombre canonico.

    Antes habia tambien `orchestrator`, pero los dos valores acababan en el
    mismo modelo (Hermes usaba su default), o sea que era configuracion muerta.
    """
    return {"worker": settings.agent_worker}


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
                       instructions: Optional[str] = None,
                       project: Optional[str] = None) -> TaskOut:
    """Crea un run en Hermes con el método, la ficha y la memoria inyectados."""
    model = _agents()[agent]
    # warm-up no bloqueante del modelo
    await ollama.ensure_model(model)
    # El método va siempre; la ficha solo si se sabe de qué proyecto habla.
    bloques = []
    metodo = method_context()
    if metodo:
        bloques.append(metodo)
    if project:
        ficha = context_for(project)
        if ficha:
            bloques.append(ficha)
    ctx = await _memory_context(prompt)
    if ctx:
        bloques.append(ctx)
    if instructions:
        bloques.append(instructions)
    effective = "\n\n".join(b for b in bloques if b) or None
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


class ProyectoOut(BaseModel):
    """Un proyecto del workspace y el estado de su ficha.

    `estado` es lo que pinta el color en el móvil: `sin_ficha` en rojo,
    `parcial` en ámbar, `completa` en verde. El móvil no parsea el texto de
    `registry_list` porque eso es para personas, no para la app.
    """
    alias: str
    kind: str = ""
    root: str = ""
    area: str = ""
    estado: str = "sin_ficha"          # sin_ficha | parcial | completa
    faltan: list[str] = []
    verify: list[str] = []
    db: str = ""
    origen: str = ""                    # registro | código
    existe: bool = True


class FichaIn(BaseModel):
    """El texto de una ficha ya revisado por la persona."""
    contenido: str = Field(min_length=1, max_length=20_000)


@app.post("/fichas/{alias}")
async def escribir_ficha(alias: str, body: FichaIn) -> dict:
    """Escribe la ficha de un proyecto, **sin pasar por el modelo**.

    Existe porque la ruta por el modelo no funciona, y se comprobó: un 7B
    al que se le pide copiar un texto literal **se come los `---` del
    frontmatter**, que es lo que declara el `kind`. La ficha quedaba sin tipo y
    la puerta la rechazaba. Medido, no supuesto.

    Aquí no hay nada que el modelo pueda tocar: la persona ya revisó el texto en
    el móvil y lo manda tal cual. El modelo redacta y propone; esto es un
    guardado.

    La ruta se **deriva** de `bridge/fichas/{alias}.md`: el que llama no puede
    escribir en ningún otro sitio. Pasa por los mismos guardarraíles que
    cualquier escritura (`_safe_resolve`, secretos, reversión si no parsea).
    """
    from . import fichas as fichas_mod
    from .mcp_ops import _no_secrets, _safe_resolve, _write_guarded
    from .projects import PROJECTS

    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no es un proyecto registrado")
    try:
        # El alias es un segmento controlado por el patrón de las fichas; aun así
        # pasa por el resolutor, que es quien aplica la whitelist.
        target = _safe_resolve(f"bridge/fichas/{alias}.md")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _no_secrets(body.contenido)
    except ValueError as exc:
        # Bloqueado de verdad; lo que estaba mal era el código de respuesta:
        # un 500 esconde el motivo y hace que un rechazo correcto parezca un fallo.
        raise HTTPException(status_code=400, detail=f"contenido denegado: {exc}") from exc
    before = target.read_text() if target.exists() else None
    ok, mensaje = _write_guarded(target, body.contenido, before)
    if not ok:
        raise HTTPException(status_code=400, detail=f"escritura RECHAZADA: {mensaje}")

    ficha = fichas_mod.read_ficha(alias)
    return {
        "alias": alias,
        "escrito": True,
        "kind": ficha.kind,
        "estado": ("completa" if ficha.completa else
                   "incompleta" if ficha.existe else "sin ficha"),
        "faltan": ficha.faltan(),
        "path": str(target),
    }


@app.get("/proyectos")
async def proyectos() -> dict:
    """Los proyectos que Aegis puede operar, con lo que a cada uno le falta.

    Responde a la pregunta que el móvil necesita para pintar el selector: no
    solo qué hay, sino **en qué estado está cada ficha**, porque un proyecto sin
    ficha y uno completo se trabajan de forma distinta.
    """
    from .fichas import secciones_que_faltan
    from .projects import PROJECTS
    out: list[ProyectoOut] = []
    for alias in sorted(PROJECTS):
        cfg = PROJECTS[alias]
        tipo, legible, faltan = secciones_que_faltan(alias)
        if legible == "completa":
            estado = "completa"
        elif legible == "no tiene ficha":
            estado = "sin_ficha"
        else:
            estado = "parcial"
        partes = Path(cfg.root).relative_to(Path(settings.workspace_dir)).parts \
            if str(cfg.root).startswith(str(settings.workspace_dir)) else ()
        out.append(ProyectoOut(
            alias=alias,
            kind=tipo or cfg_note_kind(alias),
            root=str(cfg.root),
            area=partes[0] if partes else "",
            estado=estado,
            faltan=list(faltan),
            verify=sorted(cfg.verify),
            db=cfg.db_provider,
            origen="registro" if alias in PROJECTS_DATOS() else "código",
            existe=Path(cfg.root).is_dir(),
        ))
    return {"proyectos": [p.model_dump() for p in out]}


def cfg_note_kind(alias: str) -> str:
    """Tipo declarado en `registro/` para los que aún no tienen ficha."""
    import json as _json
    from .projects import REGISTRO_DIR
    try:
        return str(_json.loads((REGISTRO_DIR / f"{alias}.json").read_text(encoding="utf-8"))
                   .get("kind", ""))
    except (OSError, ValueError):
        return ""


def PROJECTS_DATOS() -> set[str]:
    from .projects import _DATOS
    return set(_DATOS)


# -- tareas -------------------------------------------------------------------
@app.post("/tasks", response_model=TaskOut)
async def create_task(task: TaskIn) -> TaskOut:
    return await _submit_task(task.agent, task.prompt, task.instructions, task.project)


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


class AutopilotStarted(BaseModel):
    """Un run de autopilot lanzado en segundo plano."""
    run_id: str
    status: str = "started"


class AutopilotStatus(BaseModel):
    """Progreso de un run en segundo plano: lo que el móvil va consultando."""
    run_id: str
    status: str                      # running | completed | failed
    steps: int = 0
    trace: list[dict] = []
    answer: Optional[str] = None
    fin: Optional[str] = None
    error: Optional[str] = None


#: Runs de autopilot en segundo plano. Con tope: un móvil que nunca cierra sesión
#: no puede dejar el bridge creciendo sin límite.
_AUTOPILOT_RUNS: dict[str, dict] = {}
_AUTOPILOT_RUNS_MAX = 50


def _autopilot_trim() -> None:
    while len(_AUTOPILOT_RUNS) > _AUTOPILOT_RUNS_MAX:
        _AUTOPILOT_RUNS.pop(next(iter(_AUTOPILOT_RUNS)))


async def _run_autopilot_once(body: AutopilotIn, ctx: str, puerta: Any,
                              run_id: str, on_step: Any = None) -> dict:
    """El bucle de verdad, con su traza, su verificador y su episodio.

    Lo comparten la ruta síncrona y la de segundo plano: que el móvil vea el
    mismo resultado por los dos caminos, no dos implementaciones que divergen.
    """
    project = body.project or ""
    result = await run_autopilot(
        body.prompt,
        ollama_url=settings.ollama_base_url,
        model=body.model or settings.autopilot_model,
        max_steps=max(1, min(body.max_steps, 16)),
        instructions=body.instructions or "",
        project=project,
        memory=ctx,
        gate=puerta,
        on_step=on_step,
    )
    log.info("autopilot %s: %d pasos, %d tools ejecutadas (proyecto=%s)",
             run_id, result["steps"], sum(1 for t in result["trace"] if t.get("tool")),
             project or "-")
    # La traza es la evidencia. El `answer` del modelo no lo es: se ha medido que
    # llega a reportar éxito sin haber escrito nada (lessons/aegis.md A-013).
    for paso in result["trace"]:
        if paso.get("gate"):
            telemetry.record("INFO", "autopilot.gate", run_id=run_id,
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
            "run_id": run_id,
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
    return result


@app.post("/autopilot", response_model=AutopilotOut)
async def autopilot(body: AutopilotIn) -> AutopilotOut:
    """Ejecuta una tarea con el bucle modelo→aegis-ops, sin depender de tool_calls.

    Es la vía fiable de autonomía: el modelo local decide QUÉ tool usar y el
    bridge la EJECUTA de verdad, con lista blanca y traza auditable.

    El run se guarda como episodio: con `project` se inyectan las lecciones
    curadas del repo y el recall, de modo que una corrección escrita a mano
    llegue sola a los intentos siguientes.

    Es síncrono a propósito. Para el móvil, que no puede dejar al usuario
    mirando un spinner dos minutos sin saber qué pasa, está
    `POST /autopilot/start` + `GET /autopilot/{run_id}`.
    """
    project = body.project or ""
    ctx = ""
    if project:
        ctx = await _memory_context(body.prompt)
    puerta = None
    if body.verificar:
        from .verifier import gate as _gate
        puerta = _gate(project, body.que)
    result = await _run_autopilot_once(
        body, ctx, puerta, f"autopilot-{int(time.time())}")
    return AutopilotOut(project=project or None, **result)


@app.post("/autopilot/start", response_model=AutopilotStarted)
async def autopilot_start(body: AutopilotIn) -> AutopilotStarted:
    """Lanza el run y devuelve ya, con la traza creciendo en GET /autopilot/{id}."""
    run_id = f"autopilot-{uuid.uuid4().hex[:12]}"
    _AUTOPILOT_RUNS[run_id] = {"run_id": run_id, "status": "running",
                               "steps": 0, "trace": [],
                               "answer": None, "fin": None, "error": None}
    _autopilot_trim()
    project = body.project or ""
    ctx = await _memory_context(body.prompt) if project else ""
    puerta = None
    if body.verificar:
        from .verifier import gate as _gate
        puerta = _gate(project, body.que)

    async def _on_step(step: int, entry: dict) -> None:
        run = _AUTOPILOT_RUNS.get(run_id)
        if run is None:
            return
        run["trace"].append(entry)
        run["steps"] = max(run["steps"], step)

    async def _runner() -> None:
        try:
            result = await _run_autopilot_once(body, ctx, puerta, run_id, on_step=_on_step)
            run = _AUTOPILOT_RUNS.setdefault(run_id, {"run_id": run_id})
            run.update(status="completed", steps=result["steps"],
                       answer=result["answer"], fin=result["fin"],
                       trace=result["trace"])
        except Exception as exc:  # noqa: BLE001 — el run no puede morir en silencio
            log.warning("autopilot %s falló: %s", run_id, exc)
            run = _AUTOPILOT_RUNS.setdefault(run_id, {"run_id": run_id})
            run.update(status="failed", error=str(exc)[:500])

    asyncio.create_task(_runner())
    return AutopilotStarted(run_id=run_id)


@app.get("/autopilot/{run_id}", response_model=AutopilotStatus)
async def autopilot_status(run_id: str) -> AutopilotStatus:
    """Progreso del run: pasos ya ejecutados, tools y por qué terminó."""
    run = _AUTOPILOT_RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run de autopilot desconocido")
    return AutopilotStatus(**run)


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
                out = await _submit_task(task.agent, task.prompt, task.instructions, task.project)
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