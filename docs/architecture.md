# Arquitectura

## 1. Visión general

Uno de los requisitos duros del proyecto es que **el móvil no tenga ni una sola
dependencia de Internet**: el backend vive en la máquina local y el acceso se hace
vía una red de malla privada (Tailscale). El bridge convierte el API de Hermes en
un contrato simple REST+WS, y hace de **cola/proxy** de eventos.

```
[ Aegis Console ]  ──REST──►  POST /tasks {agent, prompt}
        │                 ◄──      {run_id, status}
        │                    WS connect /ws
        │                    {"type":"subscribe","run_id":...}
        ▼
[ Bridge :8000 ]  ──► Hermes  POST /v1/runs   (202)   → run_id
         │            ▲      GET  /v1/runs/{id}/events  (SSE, con API key)
         │            └────── bucle lector SSE por run (buffer de replay)
         │
         ▼  WS frames normalizados: text.delta, tool.*, approval.*, task.*, ws.status
[ Aegis Console ]
```

## 2. Componentes

### 2.1 Bridge (`bridge/app/`)

- `main.py` — API REST (`/health`, `/models`, `/tasks`, `/tasks/{id}`, `.../approval`,
  `.../steer`, `.../stop`) y WebSocket `/ws`. Al crear una tarea arranca **ya** el
  lector SSE del run (`relay.ensure_reader`): el móvil, que se suscribe 2-8 s más
  tarde (RTT de malla), recibe el historial completo.
- `relay.py` — multiplexa runs en ejecución: normaliza nombres de evento SSE de
  Hermes a tipos amigables y mantiene un **buffer de replay** (máx. 2000 eventos/run)
  para suscriptores tardíos y reconexiones. Enviar a un socket fallido lo remueve.
- `hermes_client.py` — cliente HTTP hacia el API server (`Authorization: Bearer
  <key>`). Métodos: crear run, estado, aprobar/refusar, steer, stop y stream SSE.
  Nota: `httpx.Timeout` debe recibir los 4 parámetros (`connect/read/write/pool`).
- `models.py` — contrato Pydantic REST+WS (validación estricta).
- `llm.py` — warm-up/no-bloqueante de modelo Ollama y listado.

### 2.2 App (`mobile/lib/`)

Clean architecture por capas:

```
core/        config (API_HOST via --dart-define), network (dio + socket con reconexión)
data/        models (DTOs) + repositorio (AgentRepositoryImpl)
domain/      contrato AgentRepository (interfaz)
presentation providers (repos, health, TaskSessionController), pages, widgets
```

- **`API_HOST`**: inyectado en build-time; `localhost` (emulador/adb reverse) o
  `aegis.<tailnet>.ts.net` (malla MagicDNS). Sin IPs estáticas.
- **Deduplicación**: cada evento tiene `dedupeKey` basada en `tipo + payload
  completo` (JSON). Si la clave se construye sobre un prefijo truncado, colapsa
  deltas consecutivos (el `run_id` es constante) — ver sección Pitfalls.
- **TaskSessionController** (Riverpod `Notifier`): crea el run, abre el WS,
  acumula `finalText` desde `text.delta`, gestiona aprobaciones, steer y stop.
- Reconexión del WS con backoff (2 s→30 s, máx. 8); al reconectar se re-suscribe
  y el replay + dedupe hacen el resto.

## 3. Contrato

### 3.1 REST

| Método | Ruta                       | Body                                   | Respuesta                     |
|--------|----------------------------|----------------------------------------|-------------------------------|
| GET    | `/health`                  | —                                      | estado bridge+hermes+ollama   |
| GET    | `/models`                  | —                                      | `available`, `loaded`         |
| POST   | `/tasks`                   | `{agent, prompt, instructions?}`       | `{run_id, agent, status}`     |
| GET    | `/tasks/{run_id}`          | —                                      | `{run_id, status}`            |
| POST   | `/tasks/{run_id}/approval` | `{decision: approve\|deny, comment?}`  | `{status, accepted}`          |
| POST   | `/tasks/{run_id}/steer`    | `{text}`                               | `{run_id, accepted}`          |
| POST   | `/tasks/{run_id}/stop`     | —                                      | `{run_id, status: stopping}`  |

`agent` ∈ `worker` | `orchestrator` (rutas configuradas en Hermes).

### 3.2 WebSocket `/ws`

Mensajes del cliente:

```json
{"type":"subscribe","run_id":"..."}
{"type":"approve","run_id":"...","decision":"approve","text":"ok"}
{"type":"steer","run_id":"...","text":"ahora otra cosa"}
{"type":"stop","run_id":"..."}
```

Eventos del servidor (frame JSON `EventOut`):

```json
{ "type": "text.delta", "task_id": "...", "agent": "worker", "at": "…",
  "payload": { "event": "message.delta", "data": {"event":"message.delta","run_id":"…","delta":"Hola"} } }
```

Tipos de `type`: `task.created`, `status.changed`, `reasoning`, `text.delta`,
`tool.started`, `tool.completed`, `approval.request`, `approval.resolved`,
`task.done`/`task.failed`/`task.stopped` (terminales), `raw.progress`, `ws.status`.

## 4. Malla (Tailscale)

- Hostname del nodo: `aegis` → MagicDNS `aegis.tailXXXXXX.ts.net` (`100.101.102.100`).
- El bridge escucha en `0.0.0.0:8000` → alcanzable por cualquier nodo de la malla.
- **ACL**: por defecto el tailnet permite todo. `infra/tailnet/acl-policy.json`
  restringe a: únicamente nodos Android <-> `aegis` puerto `8000`. Aplicar en la
  Admin Console (Tailscale) cuando interese endurecer.

## 5. Pitfalls aprendidos

1. **`pkill -f` se mata a sí mismo**: usar `pkill -f "[u]vicorn app.main"`.
2. **Procesos robustos**: lanzar con `setsid nohup … & disown` (o subshell `( … &)`)
   para que sobrevivan al cierre de la sesión.
3. **`httpx.Timeout`**: necesita los 4 parámetros, o lanza `ValueError` en runtime.
4. **Suscriptor tardío**: el lector SSE debe iniciar en la **creación** del run, y el
   relay debe conservar historial; si solo se lee tras el `subscribe`, el móvil
   pierde tool-calls y deltas previos.
5. **Dedupe con prefijo truncado**: al truncar el payload, la clave cae dentro del
   `run_id` (constante) y elimina todos los deltas salvo el primero.
6. **Google Android auto-retos**: pasar `--dart-define` en `flutter build` y en `run`.

## 6. Ruta futura a 14b

- Opciones: 2 GPUs / más VRAM, o modelo 8b `Q4_K_M`+ `num_ctx` bajo (Hermes exige
  64k mínimo). Documentar el presupuesto KV ~12 GB @64k no permite 14b en 6 GB VRAM.
- En ese escenario: `model_overrides.orchestrator` → `qwen2.5-coder:14b` y re-run del
  smoke worker/orchestrator.