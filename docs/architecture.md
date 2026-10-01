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
- `llm.py` — warm-up/no-bloqueante de modelo Ollama, listado y **embeddings**
  locales (`/api/embed`) para la memoria.
- `telemetry.py` — observabilidad: eventos JSON estructurados en
  `data/logs/bridge.jsonl` y por run en `data/logs/runs/<run_id>.jsonl` (cada
  evento con su duración; en `task.failed` queda error + traza de pila).
- `memory/` — 'cerebro' del proyecto: `sqlite_graph.py` (grafo conceptual
  persistente, backend por defecto), `episodic.py` (ChromaDB embebido +
  embeddings Ollama), `graphiti.py` (backend avanzado opt-in), fachada
  `ProjectMemory` (remember/recall/render).
- `hooks.py` — reacción a eventos terminales: construye el episodio (éxito o
  pitfall con error) y lo persiste en memoria + telemetría.
- `mcp_memory.py` — fase 2: servidor MCP (stdio) para que el agente consulte la
  memoria a demanda.

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
| POST   | `/autopilot`               | AutopilotIn                            | `{model, answer, steps, trace, fin}` (síncrono) |
| POST   | `/autopilot/start`         | AutopilotIn                            | `{run_id, status}` (devuelve ya) |
| GET    | `/autopilot/{run_id}`      | —                                      | `{run_id, status, steps, trace, answer, fin, error}` |

Aegis tiene **un solo agente**: `agent = "worker"`. Antes también aceptaba
`orchestrator`, pero ambos valores terminaban en el mismo modelo (Hermes usaba su
default), así que era configuración muerta que solo sugería un equipo inexistente.
El bridge normaliza el alias legacy a `worker` para no romper apps viejas.

Se elige **motor**, no rol:

| Motor | Ruta | Para qué | Cómo se ve el avance |
|---|---|---|---|
| Hermes | `POST /tasks` | razonar, recordar, resumir | streaming por WS (`text.delta`) |
| Autopilot | `POST /autopilot/start` | **ejecutar tools** | `GET /autopilot/{run_id}`, traza por paso |

Autopilot es el que ejecuta: el modelo elige QUÉ tool usar y el bridge la corre
con lista blanca, dejando traza. Es la única vía cuyo resultado se puede citar
como evidencia.

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
7. **`/tasks` es asíncrono**: devuelve `{"status":"started"}`. Si esperas el
   resultado con un `sleep` corto, lees una traza que aún no existe y mides **0/8**
   sin que nada esté roto. Un 0 sin verificar el instrumento no es un dato.
8. **La memoria puede ser la causa, no el efecto**: un `success` sin evidencia se
   reinyecta al prompt como "episodio similar resuelto" y el modelo copia el
   patrón. Medido: 3 episodios falsos ⇒ 0/8 tool calls; sin ellos, 7/8. Por eso
   `hooks.py` exige tool ejecutada en la traza y el `recall` solo inyecta
   `success` (lección A-016).
9. **Un prompt grande no es el problema por ser grande**: recortar 10 kB a 2 kB no
   cambió nada, porque el bloque tóxico eran 788 chars de recall. Ablar por capas
   antes de parchear la primera que se ve.

## 6. Ruta futura a 14b

- Opciones: 2 GPUs / más VRAM, o modelo 8b `Q4_K_M`+ `num_ctx` bajo (Hermes exige
  64k mínimo). Documentar el presupuesto KV ~12 GB @64k no permite 14b en 6 GB VRAM.
- En ese escenario: un solo agente, sin overrides por rol, y re-run del smoke.
  Nota: hoy Hermes **sí** ejecuta tools (20/20) con `qwen2.5:7b` una vez purgada
  la memoria; el límite de 6 GB era el del sandbox por contenedor, ya retirado.

## 7. Capas críticas de ejecución

El entorno de ejecución se estructura en tres capas: **aislamiento**,
**observabilidad** y **memoria**. Dibujo del flujo completo:

```
[Móvil] → REST/WS → [Bridge :8000]
                        ├─ HERMES:  POST /tasks ─► stream WS (razonar)
                        │      ├─ recall(prompt) ──► memoria: SOLO episodios success
                        │      └─ instructions + contexto previo
                        │            ▼
                        │         [Hermes API :8642] ──► [aegis-ops MCP]  (capA: guardarraíles)
                        │            ├─ whitelist + rollback de sintaxis
                        │            └─ trazas → data/logs/runs/<id>.jsonl
                        │            ▼
                        │         events SSE → relay ──► telemetry
                        │
                        └─ AUTOPILOT: POST /autopilot/start ─► bucle propio
                                 (el modelo elige QUÉ tool; el bridge la EJECUTA)
                                      ▼
                                   traza por paso → GET /autopilot/{run_id}

   Veredicto de un run (ambos motores):  traza  ──► ¿hubo tool con ok?
     sí → outcome=success  ·  no → outcome=sin_evidencia   ← nunca desde final_text
   Memoria: solo se inyecta al prompt un `success` con tools nombradas.
```

### 7.0 Dónde se prueba la app (y por qué no en tu teléfono)

El emulador de `infra/mobile/emulador.sh` replica el galaxy a17: **Android 16
(API 36), 1080x2340, 450 dpi**, la misma versión y geometría reales (medidas
con adb). Lo que **no** se replica es la ABI: el teléfono es arm64-v8a y esta
máquina es x86_64.

- `install_apk` apunta al emulador por defecto. `resolver()` **no tiene** un valor
  por defecto que alcance el teléfono: el destino se nombra, siempre.
- Instalar en el teléfono pasa por `app/deploy.py`: verificación (analyze, tests
  y humo en emulador), **autorización de un solo uso** aprovada en el móvil, y un
  aviso al teléfono. Instalar y abrir son pasos separados, y por defecto solo se
  instala.
- El humo no basta con que la app arranque: exige que el bridge reciba una
  llamada marcada como del emulador. Sin la cabecera `X-Aegis-Origen`, el
  emulador y el teléfono serían la misma línea en el log —los dos llegan por
  `adb reverse`— y no habría forma de probar que la prueba fue donde debía.
- `app/dispositivos.py` y `app/deploy.py` viven aparte de `mcp_ops.py`: son
  lógica de dispositivos con frontera de seguridad, no guardarraíles de ruta.

- **Un APK por destino**, y el destino en el nombre del fichero
  (`app-debug-emulador.apk`, `app-debug-telefono.apk`). Flutter deja siempre
  `app-debug.apk`, así que `build_apk` lo mueve. La razón no es de limpieza: son
  binarios distintos (`localhost` frente a la IP de la tailnet) y cruzarlos produce
  una app que **arranca y no ve nada**, sin error ni aviso.
- **La IP del bridge no se inventa.** Se pregunta a `tailscale ip -4`, o se exporta
  `AEGIS_BRIDGE_TAILNET_IP`. Una IP de reserva "razonable" en una dirección es peor
  que ninguna: antes `telefono` caía por defecto en la IP del propio teléfono.

> **Dos procesos, un estado.** El MCP de `aegis-ops` corre aparte del bridge
> FastAPI. Por eso el registro de orígenes va por HTTP y el estado de
> despliegue a un fichero: en memoria, el botón de aprobar del móvil nunca
> habría visto la petición y el humo siempre habría fallado.

### 7.1 Aislamiento (guardarraíles, no contenedor)

- **Retirado el 2026-09-30 el sandbox por contenedor.** Arrancaba un contenedor
  `aegis-sandbox` en cada run que el agente no podía usar: `terminal` nunca estuvo
  habilitada en `api_server`, y su `/workspace` era un directorio vacío. Coste
  (683 MB de imagen + arranque por run) sin beneficio.
- `terminal.backend` es `local`. El aislamiento real lo dan los guardarraíles de
  `bridge/app/mcp_ops.py`, que se aplican **sin importar quién llame a la tool**:
  whitelist multi-raíz, denylist (`.git`, `.env*`, binarios), escaneo de secretos
  y rollback de sintaxis.
- Consecuencia asumida: `repo_verify` y `build_apk` ejecutan en el host. Es
  aceptable en una laptop de un solo usuario; no lo sería en un runner compartido.

### 7.2 Observabilidad (telemetría estructurada)

- `bridge/app/telemetry.py` emite JSONL en dos planos:
  - `data/logs/bridge.jsonl` — eventos globales (recall de memoria, episodios
    guardados, fallos con traza).
  - `data/logs/runs/<run_id>.jsonl` — la secuencia completa del run: cada evento
    normalizado con `event_exec_ms`, y `run.failed.detail` con **línea y traza de
    pila** del fallo. Es el artefacto que el flujo de memoria usa como episodio
    negativo.
- `GET /health` incluye `memory` (estado de los almacenes) y la telemetría se
  configura en `lifespan` desde `LOG_DIR` (`.env`).
- Extra (documentado): `hermes monitoring` exporta métricas OTLP si se desea.

### 7.3 Memoria ('cerebro' del proyecto)

Tres niveles, cada uno con su rol:

| Nivel | Almacén | Backend | Rol |
|-------|---------|---------|-----|
| (c) Nativa | Hermes memory graph (`hermes journey`) | incl. Hermes | autobiografía del agente (se llena con el uso) |
| (b) Conceptual | grafo de conceptos, episodios ligados | `sqlite` (por defecto) o `graphiti` (opt-in) | enlaces entre conceptos descubiertos juntos |
| (a) Episódica | embeddings + índice vectorial | ChromaDB embebido + Ollama (`nomic-embed-text`) | recuperación semántica "¿ya resolvimos algo así?" |

Ciclo de vida (automatizado en el bridge):

1. **Recordar** — `hooks.on_terminal_event` en `relay._reader`: al terminar un
   run, construye el episodio (prompt, resumen, código extraído de bloques
   fenced, error si falló) y llama a `ProjectMemory.remember()`:
   - guarda el episodio en el grafo (SQLite o Graphiti) con sus conceptos,
   - lo indexa por embedding (Chroma + Ollama) cuando está disponible.
   - **el veredicto lo decide la traza, no el texto**: `hooks.tools_executed()`
     lee `data/logs/runs/<id>.jsonl` y, si no hay ninguna tool ejecutada sin
     error, el episodio se graba como `sin_evidencia` (no `success`) y con el
     texto del modelo descartado. La razón: un falso éxito reinyectado como
     "episodio similar resuelto" hace que el modelo responda sin llamar a nada
     (A-016, medido 0/8 → 7/8 al quitarlo).
2. **Recordar antes de crear** — `POST /tasks` (y WS `create_task`) calcula
   `recall(prompt)` y, si hay contexto, lo inyecta como `instructions` extra
   bajo `## Contexto de experiencia previa`. El modelo (64k de contexto) lo
   asimila sin coste.
   - **el filtro es en `render_context`**: `recall` devuelve lo semánticamente
     más cercano sin mirar el `outcome`, así que el filtrado a `success` ocurre
     justo en la frontera de inyección. Un `failed` presentado bajo "resueltos
     antes" es instrucción contraria, y el 7B la copia.
3. **Consultar a demanda (fase 2)** — `app/mcp_memory.py` expone
   `memory_search`/`memory_status` como tools MCP sobre stdio, para que el
   propio agente consulte dentro del run.

Config (`.env`): `MEMORY_ENABLED`, `MEMORY_DIR`, `MEMORY_RECALL_K`,
`MEMORY_GRAPH_BACKEND` (`sqlite`|`graphiti`|`off`), `EMBED_MODEL`.

Degradación intencionada: sin `chromadb`/Ollama la memoria **no rompe el
bridge** — la episódica se desactiva sola y el grafo (SQLite, sin deps)
sigue sirviendo recuperación léxica. Los tests (`tests/test_memory.py`)
verifican este comportamiento.