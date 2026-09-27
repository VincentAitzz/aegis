# AGENTS.md — aegis

> [!IMPORTANT]
> En este repo **opencode no es el autor**: es el supervisor de Aegis. El código
> de producto lo escribe Aegis (el agente local) y opencode hace el spec, revisa,
> corrige y **deja la lección**. Ver §2.

## 1. Qué es Aegis

Consola de operación del negocio freelance, local-first:

```
[App Flutter] ──REST/WS──► [Bridge FastAPI :8000] ──► [Hermes gateway :8642] ──► [Ollama :11434]
                                  │                          └──► MCP aegis-ops / aegis-memory
                                  ├── autopilot: bucle modelo→tool, ejecución determinista
                                  ├── memoria episódica (Chroma + SQLiteGraph)
                                  └── telemetría
```

- `bridge/` — API FastAPI, memoria, telemetría, los MCP y el autopilot.
- `mobile/` — cliente Flutter (`aegis_console`).
- `infra/` — scripts de arranque (`ollama/`, `docker/`, `tailnet/`, `mobile/`).
- `docs/` — arquitectura y runbook. **Actualízalos cuando cambie el operarlo.**

**Invariante que no se negocia:** *Aegis nunca es punto único de falla.* Si la
laptop se apaga, el negocio sigue. La autoridad vive en el Worker/Postgres del
portafolio, no aquí.

## 2. El rol de opencode aquí: consultor y corrector

El orden es siempre el mismo:

1. **Spec cerrada** — qué hacer, con qué criterio de éxito, y qué NO hacer.
2. **Delegar** — Aegis ejecuta vía `POST /autopilot` (no le escribo el código).
3. **Verificar** — `repo_verify` del proyecto + tests del bridge.
4. **Medir** — intentos hasta verde · líneas del agente / corregidas · errores
   que inventó · lecciones que aplicó solo.
5. **Corregir** — con el motivo, no solo el síntoma.
6. **Dejar la lección** — en `bridge/lessons/{proyecto}.md`.

> **Regla dura: una corrección sin lección escrita es trabajo incompleto.**
> Un arreglo que solo vive en el commit no lo ve nunca el agente: la próxima vez
> lo repite. Las lecciones se inyectan solas en el prompt (ver
> `app/autopilot.py:build_system_prompt`).

### Cuándo usar cada camino

| Necesito | Camino |
|---|---|
| Que una tool se ejecute de forma fiable | **`/autopilot`** (determinista, con traza) |
| Razonar, recordar, resumir, redactar | run de Hermes vía `/tasks` (usa memoria) |
| Cambiar el diseño, la arquitectura o los invariantes | **opencode, directamente** |

Motivo técnico: los modelos de 6 GB disponibles (`qwen2.5:7b`) **no emiten
`tool_calls` fiables** en los runs de Hermes: escriben el JSON de la llamada en
el texto. El autopilot lo resuelve parseando la intención y ejecutándola. Si
necesitas tools, va por autopilot.

## 3. Protocolo de delegación

```bash
curl -s -X POST http://127.0.0.1:8000/autopilot \
  -H 'Content-Type: application/json' \
  -d '{"project":"portafolio","max_steps":16,"instructions":"<reglas>","prompt":"<tarea>"}'
```

- `project` es lo que carga `bridge/lessons/{project}.md` y el `recall`.
- `instructions` van en el system prompt; el `prompt` es la tarea.
- Las rutas del proyecto van con prefijo de alias: `portafolio/src/lib/db.ts`.
- `repo_verify(what='check'|'test'|'build')` es la única tool de verificación, a
  propósito: un 7B rinde peor con muchas tools que con una.

**Antes de delegar, lee `bridge/lessons/{proyecto}.md`.** Si vas a repetir un
trabajo, las lecciones ya explican dónde se equivocó la última vez.

## 4. Guardarraíles: intocables

Están en `bridge/app/mcp_ops.py`. Debilitarlos "para que algo funcione" es un
retroceso, aunque haya un bug de fondo:

| Guardarraíl | Qué evita |
|---|---|
| Whitelist multi-raíz (`ROOTS`) | que el agente escriba fuera de los proyectos declarados |
| Denylist (`.git`, `node_modules`, `dist`, `build`, `.venv`…) | editar áreas generadas o versionadas a mano |
| Escaneo de secretos (escritura y lectura) | que una key acabe en un archivo o en un log |
| **Rollback de sintaxis** | un archivo roto llega al repo: si `dart format`/esbuild no parsean, se revierte |
| Parseo de tool-calls + reparación | que una llamada mal formada se cuele como texto |

Cuando un guardarraíl bloquea algo legítimo, **se amplía el guardarraíl**, no se
desactiva: el motivo de cada veto está en el mensaje.

## 5. Operación (verificar antes de asumir)

```bash
# Ollama — no es servicio de sistema
setsid nohup bash infra/ollama/start-ollama.sh > ~/.local/log/ollama.log 2>&1 &

# Gateway de Hermes — necesita el grupo docker (Gid 956) para el sandbox
newgrp docker -c 'bash infra/docker/start-gateway-docker.sh'
#   OJO: el `pkill` del script tarda ~30 s en drenar. Si arrancas antes de que
#   muera, el nuevo dice "A gateway already owns this host" y se muere. Comprueba
#   con: pgrep -f '[h]ermes gateway' || newgrp docker -c '...'

# Bridge
cd bridge && bash run.sh          # uvicorn en :8000 con --reload
```

Teléfono `galaxy-a17` (Tailscale `100.101.102.103`): el **puerto adb cambia** en
cada reinicio. Las tools lo resuelven solas por mDNS; a mano:
`adb mdns services` → `adb connect <host>:<puerto>`. Tailscale del teléfono a
veces está caído: el adb por mDNS funciona igual.

## 6. Seguridad

Ver las reglas globales en `~/.config/opencode/security.md`. Lo específico:

- **Nunca imprimas un valor de `.env`, `.env.local` ni `.dev.vars`.** Si hace
  falta comprobar algo, comprueba la **longitud** o un prefijo no sensible.
- Secretos de producción del Worker: `wrangler secret put <NOMBRE>`, uno por
  uno. **Nunca** en el repo ni en `wrangler.jsonc`.
- La clave de la API de operación se rota **por nombre versionado**
  (`AEGIS_API_KEY_V2` → `V3`): publicar la nueva, cambiar el cliente, verificar,
  recién ahí borrar la vieja.
- PII de clientes (RUT, emails) vive en Postgres, **no** en la réplica local ni
  en los logs. La réplica de `biz_cache` tiene allowlist de campos por entidad.

## 6.1 Las bases: de quién es cada una

Aegis **gestiona** las bases de los proyectos; no es dueño de sus datos. La
frontera se decidió el 2026-09-27 y está en `bridge/app/neon.py` (`PROJECTS`):

| Base | Proyecto Neon | Qué contiene | Quién manda |
|---|---|---|---|
| de **Aegis** | `el-proyecto-de-neon-aegis` | cerebro y recursos internos. **Sin esquema todavía**: la memoria sigue local (Chroma + SQLiteGraph) | Aegis |
| del **portafolio** | *(proyecto propio, pendiente de crear)* | el sistema de operación del negocio | el portafolio |
| de **compra-unida** | `young-waterfall-ace5iynr` | su dominio, con sus 24 tablas | compra-unida |

Tres reglas que no se negocian:

1. **Producción jamás desde el Bridge.** Toda operación va contra la rama
   registrada en `PROJECTS`, que es la de desarrollo. La URL de producción solo
   aparece en un despliegue, con `wrangler secret put`.
2. **Quien llama no elige base.** `db_migrate` y `neon_branch` reciben un alias
   del registro, nunca una URL, un host o un nombre de rama libre. El error
   posible no es "aplicó a producción": es "no encontré esa migración".
3. **Una sola credencial, ninguna contraseña duplicada.** `bridge/.env` tiene la
   `NEON_API_KEY`; las connection strings se piden a Neon por API en el momento
   de usarlas y se pasan a `psql` como variables `PG*`, nunca como argumento —
   en un argumento la contraseña aparece en `ps` para cualquiera de la máquina.

Estado de habilitación por proyecto (2026-09-27): el portafolio puede leer y
migrar; compra-unida **solo lee**, porque su journal de drizzle está vacío con 24
tablas vivas y `db:migrate` intentaría recrearlas; la base de Aegis se lee pero no
se migra con migraciones de proyecto.

## 7. Verificación

No afirmes que algo funciona sin ejecutarlo:

```bash
# El bridge (rápido, siempre)
cd bridge && .venv/bin/python -m unittest discover -s tests -q
cd bridge && bash bin/probe-toolcall.sh qwen2.5:7b    # capacidad de tool-calling
# El proyecto que toca el agente
node scripts/check-syntax.mjs <archivos>               # solo sintaxis
```

## 8. Proyectos que opera el agente

`ROOTS` en `bridge/app/mcp_ops.py` declara alias → ruta, y `VERIFY` el verificador de
cada una. Cada proyecto necesita las dos cosas y un `bridge/lessons/{alias}.md`.
Un archivo de lecciones que no existe se carga vacío; no es un error.

| Alias | Ruta | `check` | `test` |
|---|---|---|---|
| `aegis` | este repo | — (tests del bridge) | `.venv/bin/python -m unittest discover -s tests -q` |
| `portafolio` | `~/Workspace/web/portafolio` | `tsc --noEmit` | `vitest run` |
| `trazeurs` | `~/Workspace/mobile/trazeurs` | `flutter analyze` | `flutter test` |
| `compra-unida` | `~/Workspace/apps/compra-unida` | `tsc --noEmit` | `npm test` |
| `recepcion-persa` | `~/Workspace/apps/recepcion_persa` | `compileall` | `pytest -q` |

**`trazeurs` tiene una base roja: 452 issues de `flutter analyze`**, casi todos del
`test/widget_test.dart` de la plantilla. Antes de delegar ahí, el criterio de
éxito no puede ser "analyze limpio": es "no más de N issues nuevos", y conviene
sacar la cuenta exacta antes de empezar. Lo mismo aplica a cualquier proyecto que
llegues con tests rojos: **mide la base, o el criterio de éxito no significa nada.**

## 9. Reglas del sistema del portafolio

El otro repo tiene `AGENTS.md` propio y `docs/` con 12 documentos; el
`modelo-datos.md` §2 manda sobre cualquier doc de comportamiento. Sus 21
invariantes (§6) son **tests**, no afirmaciones. Al tocar su base:

```bash
cd ~/Workspace/web/portafolio
node scripts/neon-branch.mjs dev          # crea/reutiliza la rama dev y conecta
psql "$DATABASE_DEV_URL" -f migrations/0001_init.sql
```

**Producción no se toca sin que lo pidas explícitamente.** El desarrollo va
contra la rama `dev`; la URL de producción solo se usa con
`wrangler secret put` en un despliegue.