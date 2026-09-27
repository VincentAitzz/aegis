# Runbook

Guía de operación del backend Aegis (post-reinicio), pruebas y resolución de
problemas. Máquina: CachyOS (Arch), usuario `demo`, sin sudo automático.

## 1. Arranque tras un reinicio

Ollama y el gateway de Hermes **no** son servicios de sistema; hay que levantarlos
a mano en este orden (Tailscale sí usa `systemd` y arranca solo).

```bash
# 1) Ollama con contexto 64k (imprescindible para Hermes)
env OLLAMA_HOST=127.0.0.1 OLLAMA_CONTEXT_LENGTH=64000 ~/.local/bin/ollama serve \
  > ~/.local/ollama.log 2>&1 &
# alternativa: ./infra/ollama/start-ollama.sh

# 2) Gateway/API server de Hermes
setsid nohup ~/.local/bin/hermes gateway run > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &

# 3) Bridge Aegis
cd /RUTA/AL/REPO/bridge
( env BRIDGE_BIND=0.0.0.0 BRIDGE_PORT=8000 PYTHONPATH=app \
    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > ~/.local/bridge.log 2>&1 & )

# 4) Devolución de bueno
curl -s http://127.0.0.1:8000/health   # espera status ok + agents [worker, orchestrator]
```

Logs:

| Servicio | Log                                   |
|----------|---------------------------------------|
| Ollama   | `~/.local/ollama.log`                 |
| Hermes   | `~/.hermes/logs/gateway.log`          |
| Bridge   | `~/.local/bridge.log`                 |
| Bridge (JSON) | `bridge/data/logs/bridge.jsonl`  |
| Bridge (por run) | `bridge/data/logs/runs/<run_id>.jsonl` |

## 2. Credenciales y secretos

| Variable         | Dónde vive                     | Uso                                      |
|------------------|--------------------------------|------------------------------------------|
| `API_SERVER_KEY` | `~/.hermes/.env`               | autenticación del API server de Hermes   |
| `HERMES_API_KEY` | `bridge/.env` (gitignored)     | el bridge se autentica ante Hermes       |

- **Nunca** se versionan `.env*` (salvo `.env.example`). `bridge/.env` está en
  `.gitignore`; verifica con `git status --ignored | grep .env` antes de commitear.
- Regeneración: `openssl rand -hex 32` → actualiza ambos `.env` y reinicia
  gateway + bridge.

## 2.1. Instalaciones pendientes (el agente las dejó para ti)

```bash
# CAPA 1 — Aislamiento (Docker) + imagen del sandbox
sudo pacman -S docker
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"          # cierra y abre sesión (o newgrp docker)
./infra/docker/enable-docker-backend.sh  # construye aegis-sandbox y aplica hermes config set
# reinicia el gateway para que Hermes tome el backend docker: el proceso debe
# heredar el grupo docker (Gid 956). Si tu shell no lo tiene (=sesión anterior
# al usermod), arráncalo así:
newgrp docker -c 'bash infra/docker/start-gateway-docker.sh'   # ver advertencia abajo

# CAPA 3 — Memoria episódica (vectorial)
bridge/.venv/bin/pip install -r requirements.txt   # instala chromadb; mcp<2 por la API FastMCP
ollama pull nomic-embed-text                        # modelo de embeddings local

# FASE 2 (opcional) — consulta de memoria por el agente vía MCP
bridge/.venv/bin/pip install 'mcp>=1.0,<2'

# Nota: si el storage driver de docker no soporta cuota por contenedor
# (overlay2 sobre XFS+pquota), Hermes avisa y el límite container_disk se
# ignora. Es benigno: CPU/memoria sí se aplican.
```

Verificación de la memoria activa:

```bash
curl -s 127.0.0.1:8000/health | python3 -m json.tool | grep -A8 '"memory"'
# espera: episodic_enabled: true, graph_backend: "SQLiteGraph"
```

## 3. Malla (Tailscale)

Diagnóstico:

```bash
tailscale status            # nodos online; espera aegis + galaxy-a17
tailscale ip -4             # 100.101.102.100
tailscale set --operator=$USER   # (una vez) para `tailscale up` sin sudo
```

Verificación con el bridge por la malla:

```bash
curl http://aegis.tailXXXXXX.ts.net:8000/health      # MagicDNS
curl http://100.101.102.100:8000/health                 # IP de malla
```

En el **acceso log del bridge** la prueba real se distingue porque el request llega
con la IP Tailscale del otro nodo (p. ej. `100.101.102.103`), no `127.0.0.1`.

ACL (endurecimiento opcional): aplicar `infra/tailnet/acl-policy.json` en
https://login.tailscale.com/admin/acls . Limita nodos Android → `aegis:8000`.
> Si el tailnet tiene MagicDNS roto por wiring de resolver local, la app aún
> conecta por IP `100.x`; `aegis.tailXXXXXX.ts.net` es el camino preferido.

## 4. App en el teléfono

Depuración inalámbrica (puertos giran):

```bash
adb mdns services                       # puerto actual mDNS
adb connect 192.168.0.5:<puerto>        # o directamente del número de pantalla
adb -s <serial> shell am start -n com.aegis.aegis_console/.MainActivity
```

- **Sin malla aún**: `adb reverse tcp:8000 tcp:8000 tcp:11434 tcp:11434` y usar
  `API_HOST=localhost` → `./infra/mobile/install-phone.sh`.
- **Con malla**: recompilar con `--dart-define=API_HOST=aegis.<tailnet>.ts.net` y
  reinstalar. La app muestra el host en la página Conectividad.
- Si ADB cae tras un reinicio: re-activar "Depuración inalámbrica" en el teléfono
  (Ajustes → Opciones de desarrollador) y re-conectar con el puerto nuevo.
- Las tools de `aegis-ops` resuelven el dispositivo solas: `adb_connect()` usa
  mDNS + la IP de la tailnet, y `install_apk`/`verify_deploy` prefieren el
  nombre mDNS estable del teléfono. Funcionan con o sin Tailscale (misma Wi-Fi).

## 4.1. Agente autónomo (`/autopilot`)

Los modelos locales de 6 GB **no emiten `tool_calls` fiables** dentro de los runs
de Hermes: escriben el JSON de la llamada en el texto (a veces envuelto en
`<stdlib_response>`) y se detienen. Medido:

| Modelo | `tool_calls` en sonda |
|---|---|
| `qwen2.5-coder:7b` | nunca (siempre texto) |
| `qwen2.5:7b` | sí, de forma fiable |
| `qwen3:4b` | intermitente; cuelga en modo no-stream |

Por eso el puente tiene su propio bucle agente→tool (`bridge/app/autopilot.py`):
el modelo decide QUÉ tool usar y el bridge la EJECUTA con lista blanca y traza
auditable. Endpoint:

```bash
curl -X POST http://127.0.0.1:8000/autopilot -H 'Content-Type: application/json' -d '{
  "prompt": "pon el tono en verde, compila e instala en el teléfono",
  "max_steps": 12
}'
# -> {"answer": "...", "steps": N, "trace": [{"tool": "...", "arguments": {...}, "ok": true}]}
```

Garantías de `aegis-ops` (sin importar quién la llame):

- **Whitelist**: solo 8 tools del repo; cualquier otro nombre se rechaza.
- **Rutas**: solo dentro del repo; veta `.git/`, `.env*` y binarios.
- **Secretos**: se niega a escribir contenido que parezca una clave (redactada).
- **Rollback**: si un `.dart` deja de parsear tras editar, se revierte y se le
  devuelve el contenido actual al modelo para que reintente.
- **Trazabilidad**: cada paso queda en `trace[]` con argumentos y resultado.

## 5. Pruebas

Unitarias (capa observabilidad + memoria + autopilot; corren SIN chromadb — degradan):

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

# ciclo real contra Ollama (el modelo decide y ejecuta de verdad)
cd bridge && AEGIS_SLOW_TESTS=1 .venv/bin/python -m unittest tests.test_autopilot -v

# sonda de capacidad de tool-calling del modelo
cd bridge && bash bin/probe-toolcall.sh qwen2.5:7b
```

Funcionales (host):

```bash
# E2E REST+WS (subscribe tardío → replay completo, verifica buffer)
cd bridge && .venv/bin/python tests/e2e_ws.py

# Contrato de control
curl -X POST http://127.0.0.1:8000/tasks -d '{"agent":"worker","prompt":"hola"}'
curl -X POST http://127.0.0.1:8000/tasks/$RUN/steer -d '{"text":"cancela"}'
curl -X POST http://127.0.0.1:8000/tasks/$RUN/stop
```

App:

```bash
cd mobile
flutter analyze && flutter test       # espera 0 issues / verde
flutter build apk --debug --dart-define=API_HOST=…   # luego adb install -r
```

Smoke de Hermes directo (tool-calling):

```bash
source ~/.hermes/.env
curl -H "Authorization: Bearer $API_SERVER_KEY" http://127.0.0.1:8642/health
```

## 6. Troubleshooting

| Síntoma                                | Causa probable / remedio                                             |
|----------------------------------------|---------------------------------------------------------------------|
| `httpx.Timeout must either include…`   | falta un parámetro del Timeout; ver `hermes_client.py`              |
| bridge 000 pero proceso arriba         | matado por cierre de sesión: relanzar con `setsid nohup`/subshell   |
| App: sin `text.delta` aunque completó  | dedupe truncado (bug viejo) o suscripción tardía sin replay; compilar con el código actual |
| App no conecta; chip "connecting" fijo | WS no llega: verifica MagicDNS `aegis.tailXXXXXX.ts.net` e IP 100.x |
| `pkill uvicorn` mata la propia shell   | usar patrón `[u]vicorn` (evita auto-match)                          |
| Ollama OOM a 64k                       | RAM libre ~5 GB es justo; evitar construir contexto +44k sin cache_read |
| Tailscale "Logged out" tras reboot     | `sudo tailscale up --hostname aegis` y completar login (URL impresa)|
| `health.memory.episodic_enabled=false` | chromadb o `nomic-embed-text` sin instalar (ver §2.1); el grafo SQLite sigue funcionando |
| `health.memory.graph_backend` = graphiti pero cae a SQLite | falta `pip install graphiti-core falkordb` o la API cambió; reinicia y mira `bridge/data/logs/bridge.jsonl` (error `run.failed`) |
| quiero borrar la memoria acumulada     | `rm -rf bridge/data/memory` + reiniciar bridge (¡ojo! el móvil no depende de ella) |
| `memory.recall` tarda o falla          | el modelo de embeddings no está cargado: `ollama pull nomic-embed-text` y `ollama run nomic-embed-text` una vez |

## 6.1. Cerebro (memoria) — inspección y fase 2 (MCP)

Cada run resuelto o fallido genera un episodio; inspección rápida del grafo y la
telemetría:

```bash
ls bridge/data/logs/runs/                          # logs por run (JSONL)
python3 -c "import sqlite3;
c=sqlite3.connect('bridge/data/memory/brain.db');
print([r for r in c.execute('select run_id,outcome,substr(summary,1,80) from episodes order by rowid desc limit 5')])"
grep -l '"event":"run.failed.detail"' bridge/data/logs/runs/*.jsonl   # runs que fallaron (pitfalls)
```

Fase 2 — exponer la memoria al agente como tools MCP. El servidor debe arrancar
con `PYTHONPATH=ruta_a_app` y sus rutas de datos (Hermes spawna el proceso con
su propio CWD y en v0.21 `hermes mcp add` NO traspasa `--env` a los stdio:
los mete como `args` y el proceso muere al no encontrar el paquete `app`).
Por eso hay un launcher `bridge/bin/mcp-memory.sh` que fija el entorno y es el
comando del server. Ya está registrado en `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  aegis-memory:
    command: "/RUTA/AL/REPO/bridge/bin/mcp-memory.sh"
    args: []
    enabled: true
```

Verificación (conexión + tools):

```bash
hermes mcp list && hermes mcp test aegis-memory
# Prueba manual del server (debe quedar esperando en stdio, no exit):
cd bridge && timeout 10 env PYTHONPATH=app .venv/bin/python -m app.mcp_memory
```

Prerrequisito: el venv debe llevar `mcp<2` (en mcp 2.x FastMCP se renombró a
MCPServer y este servidor aún usa la API clásica):

```bash
cd bridge && .venv/bin/pip install 'mcp>=1.0,<2'
```

Al reiniciar el gateway, el agente tendrá `memory_search(query, k)` y
`memory_status()` disponibles como herramientas. El gateway se conecta al MCP
**al arrancar**: reinícialo después de registrar el servidor. El gateway debe
correr además con el grupo `docker` (ver §2) para que la terminal del sandbox
pueda usar el daemon.

## 7. Puertos

| Puerto | Servicio      | Bind        |
|--------|---------------|-------------|
| 11434  | Ollama        | 127.0.0.1   |
| 8642   | Hermes API    | 127.0.0.1   |
| 8000   | Bridge Aegis  | 0.0.0.0 (malla) |
## 8. Bases de datos (Neon)

Aegis gestiona la topología de las bases: la **key** vive en `bridge/.env`
(`NEON_API_KEY`, ámbito de organización) y las connection strings se piden a Neon
por API cuando hacen falta, así que no hay contraseñas duplicadas en ningún repo.

```bash
# Estado de las ramas de un proyecto
bridge$ .venv/bin/python -c "from app import neon; print(neon.neon_branch('portafolio'))"

# Verificar contra la base real (la rama de desarrollo, siempre)
bridge$ .venv/bin/python -c "from app import neon; print(neon.db_query('portafolio',
  'select count(*) from information_schema.tables where table_schema=\'public\''))"

# Aplicar migraciones
bridge$ .venv/bin/python -c "from app import neon; print(neon.db_migrate('portafolio'))"
```

También están disponibles como tools del agente: `db_query`, `db_migrate`,
`neon_branch`.

| Problema | Causa |
|---|---|
| `401 supplied credentials do not pass authentication` | key inválida o revocada, **o** de alcance de proyecto pidiendo otro proyecto. El mensaje de Neon es engañoso: un 404 `not allowed to perform actions outside the project` también aparece como 401 según la ruta |
| `la rama 'dev' de 'X' no existe` | crear la rama: `neon_branch(project='X')` |
| `no hay migraciones en …` | el proyecto no tiene `migrations/`, o su estrategia es `drizzle` y hay que usar su CLI |
| `400 Bad Request` en `connection_uri` | los query params tienen que ir como dict en `httpx`; interpolados a mano salen con `%20` y Neon los rechaza |
| `psql` busca un socket local | falta pasar la URL: se hace con variables `PG*` (`neon._libpq_env`), nunca como argumento |

**Sobre las credenciales:** `bridge/.env` está en el `.gitignore` (`.env` y
`.env.*`). Si alguna vez hay que recuperar el valor de una variable, comprueba su
**longitud** o un prefijo, no lo imprimas.
