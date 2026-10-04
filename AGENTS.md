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
- `infra/` — scripts de arranque (`ollama/`, `hermes/`, `tailnet/`, `mobile/`).
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

### Lo que se midió, y cambia la regla

`/tasks` **sí** ejecuta tools de forma fiable una vez limpio el resto:
**20/20 runs** con tool realmente ejecutada y 0 falsos éxitos, en tres rondas.
No era el modelo: era la memoria.

El bucle que lo rompía (lección A-016):

1. `hooks.py` marcaba `success` a cualquier `task.done`, sin mirar la traza.
2. Esos episodios entraban a memoria con `final_text = "OK"`.
3. El `recall` los reinyectaba como *"Episodios similares resueltos antes"*.
4. El modelo aprendía que la respuesta era "OK" y contestaba **sin llamar a nada**.
5. Sin tool → `task.done` → otro falso éxito.

Ablación medida (n=8): con 3 episodios falsos, **0/8** tool calls; sin el
bloque de memoria, **7/8**. Tres episodios falsos bastaban.

Por eso Hermes se queda, pero con dos reglas que no son opcionales:

- **El veredicto sale de la traza, nunca de `final_text`.** Sin tool ejecutada
  el resultado es `sin_evidencia`, y así se graba.
- **Al prompt solo suben episodios `success` con tools nombradas.** Un fallo
  inyectado como solución es instrucción contraria.

Y el orden importa: **purgar la memoria es parte del arreglo**, no una limpieza
de final. Con la memoria envenenada no hay nada que medir.

## 3. Protocolo de delegación

### Desde la consola

```bash
curl -s -X POST http://127.0.0.1:8000/autopilot \
  -H 'Content-Type: application/json' \
  -d '{"project":"portafolio","max_steps":16,"instructions":"<reglas>","prompt":"<tarea>"}'
```

Síncrono: devuelve `answer`, `steps`, `trace` y `fin` (por qué terminó). Es lo
que usa el resto del operarlo y los scripts.

### Cuando Aegis necesita tu OK

`app/autonomy.py` reparte las 18 tools en tres niveles. Si un run.topa una tool
de nivel 3 (`db_migrate`, `neon_branch`, `install_apk`, `build_apk`,
`project_create`, `adb_connect`, `deploy_smoke`), **no ejecuta**: deja una
petición y termina con `fin: "esperando_ok"`.

```bash
curl -s localhost:8000/aprobaciones                # lo que espera tu OK
curl -s -X POST localhost:8000/aprobaciones/<id> \
  -H 'Content-Type: application/json' -d '{"decision":"aprobar"}'   # -> token
# relanzas con ese token:
curl -s -X POST localhost:8000/autopilot/start \
  -H 'Content-Type: application/json' \
  -d '{"project":"aegis","prompt":"<lo mismo>","token":"<token>"}'
```

**Denegar con motivo** es lo que hace crecer la confianza: el motivo se inyecta
en el prompt del siguiente run, y Aegis no vuelve a proponerlo. Sin motivo,
denegar es un "no" que no se puede aplicar a la siguiente situación parecida.

El token valida **la llamada, no el run**, y es de un solo uso (A-033).

Un permiso aprobado y no gastado **no se pierde**: `GET /aprobaciones` devuelve
también `aprobadas`, con su token, y el móvil tiene un botón **Ejecutar** para
cobrarlo ahí mismo y otro de **Relanzar** para que el run siga. Caducan a 24 h,
porque un permiso que nadie recuerda aprobar es ruido.

- **Ejecutar** (`POST /aprobaciones/{id}/ejecutar`) corre la llamada con los
  argumentos **que aprobaste**, sin modelo en medio. Es lo fiel: el token valida
  la llamada, y medido el modelo no la repite igual ni una de cada cuatro veces.
- **Relanzar** repite el run con el token, y es lo correcto cuando lo que quieres
  es que Aegis **continúe** working. Si pide la misma tool con otros argumentos,
  vuelve a preguntar: es lo correcto, y ahora sin quemar el permiso.
- Si el token se gastara y el run volviera a pedir lo mismo, vuelve a preguntar.

### Fases: pensar antes de construir

Una **fase** son las instrucciones que solo valen mientras se piensa. Viven en
`bridge/fases/{nombre}.md` y se inyectan en el system prompt **solo** en los runs
que la piden (`"fase": "idea"` o `"arquitectura"`); `GET /fases` dice cuáles hay.

No van en `metodo.md` a propósito: A-016 midió que el 7B deja de emitir
`tool_calls` cuando el prompt crece, y el prompt es el presupuesto. Una fase
inyectada a todo el mundo se paga en los runs de operación, que son los que más
necesitan llamar tools.

- `idea`: aterriza el problema, las alternativas y lo que se descarta. No escribe
  código —la puerta se lo negaría, porque la ficha está vacía.
- `arquitectura`: requisitos no funcionales antes de nombrar tecnología, dos o
  tres opciones con su coste de cambio, y qué habría que falsar para estar
  equivocado.

Añadir una fase es escribir un fichero. Sin código, sin enum, sin compilar.

### Las lecciones: índice, no el fichero entero

`bridge/lessons/{alias}.md` es el registro de por qué el código es como es, y
**no se borra**. Al prompt solo va:

1. un **índice** con número, título y cuándo aplica;
2. la lección **más relevante** para el encargo, entera;
3. el resto, con `lecciones(alias, tema)` — una tool de lectura, nivel libre.

Medido el 2026-10-04 (n=5, intercalado): con las 120 KB enteras cada llamada
tardaba **60,2 s**; con el índice, **11,9 s**. Y el comportamiento que las
lecciones describen no cambia: A-014 dice «no repitas la llamada idéntica que ya
falló dos veces» y el modelo la repitió 3 de 3 **con** las lecciones y 3 de 3
**sin** ellas.

Cada lección puede declarar su criterio con `> Aplica cuando: …`. Las que no lo
declaran usan la primera frase de su «qué pasó», y **no se inventa uno**: un
disparador inventado suena específico y no sirve.

### Desde el móvil, o cuando el run puede tardar

`POST /autopilot` es síncrono y un paso puede tardar medio minuto: para no
dejar al usuario mirando un spinner, están `POST /autopilot/start` (devuelve ya
un `run_id`) y `GET /autopilot/{run_id}` (la traza crece paso a paso).

```bash
RID=$(curl -s -X POST http://127.0.0.1:8000/autopilot/start \
  -H 'Content-Type: application/json' \
  -d '{"project":"aegis","prompt":"lista los proyectos"}' | jq -r .run_id)
curl -s http://127.0.0.1:8000/autopilot/$RID | jq '{status,steps,fin}'
```

- `project` es lo que carga `bridge/lessons/{project}.md` y el `recall`.
- `instructions` van en el system prompt; el `prompt` es la tarea.
- `fase` es opcional y es lo único que enciende `bridge/fases/{fase}.md`.
- Las rutas del proyecto van con prefijo de alias: `portafolio/src/lib/db.ts`.
- `repo_verify(what='check'|'test'|'build')` es la única tool de verificación, a
  propósito: un 7B rinde peor con muchas tools que con una.
- Un escalar envuelto en objeto (`repo: {"type": "portafolio"}`) lo repara
  `coerce_args`: es la malformación típica del 7B y antes tumbaba el run.

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
bash infra/stack.sh arrancar     # Ollama :11434 + gateway :8642 + bridge :8000
bash infra/stack.sh estado       # salud de los tres + qué puede escribir Aegis
bash infra/stack.sh parar        # los tres, y comprueba que mueren
```

`estado` es lo que hay que mirar antes de delegar: la última línea dice el modo
de autonomía y qué proyectos están marcados para escritura.

Dos cosas que el script hace y que a mano fallaron de verdad:

- **Apagar no es `pkill`.** Comprobado: `pkill -f 'ollama serve'` no mata nada, y
  quedan hijos vivos (`llama-server` sobrevive al `ollama serve`). El script mata
  por PID, al grupo de proceso, y verifica que el puerto quedó libre.
- **El gateway drena ~30 s.** Arrancar el nuevo antes de que muera el anterior lo
  mata con `A gateway already owns this host`.

Lo que hay dentro, por si hay que hacerlo a mano:

```bash
setsid nohup bash infra/ollama/start-ollama.sh > ~/.local/log/aegis/ollama.log 2>&1 &
bash infra/hermes/start-gateway.sh
cd bridge && bash run.sh          # uvicorn en :8000; --reload con BRIDGE_RELOAD=1
```

Y la traza se lee desde la terminal, venga el run del móvil o de curl:
`tail -f bridge/data/logs/bridge.jsonl`, o el JSONL del run en
`bridge/data/logs/runs/<run_id>.jsonl`. Ver `docs/runbook.md` §1.1.

# App: se prueba en el emulador, no en el teléfono
bash infra/mobile/emulador.sh arrancar   # AVD aegis-a17: API 36, 1080x2340, 450 dpi
bash infra/mobile/emulador.sh estado
bash infra/mobile/emulador.sh parar

La app **se prueba en el emulador**. Tu teléfono solo se toca con la puerta
completa (analyze + tests + humo en el emulador) y tu aprobación de un solo uso:
`install_apk(target='telefono')`. Ver `docs/runbook.md` §4.

Teléfono `galaxy-a17` (Tailscale `100.101.102.103`): el **puerto adb cambia** en
cada reinicio. Las tools lo resuelven solas por mDNS; a mano:
`adb mdns services` → `adb connect <host>:<puerto>`. Tailscale del teléfono a
veces está caído: el adb por mDNS funciona igual.

**Por USB** el serial es de hardware (`SERIAL1234567`) y no parece ni a mDNS ni a
`ip:puerto`, así que Aegis **no lo adivina**: se declara en `bridge/.env` con
`AEGIS_PHONE_SERIAL`. Sin Tailscale en el teléfono, el APK se compila contra la
IP de la LAN con `AEGIS_BRIDGE_TAILNET_IP`. La puerta comprueba que el teléfono
llegue antes de instalar, y con `ufw` hay que abrir el puerto (ver runbook §4.1).

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

## 7.1 La autonomía, en una frase

Aegis lee y comprueba lo que quiera sin avisarte. Para **escribir** necesita que
le marques el proyecto en `Ajustes → Proyectos` del móvil, y el interruptor solo
se activa si ese proyecto **tiene verificador declarado**: sin él no hay contra
qué comprobar que el trabajo quedó bien. Y lo que sale de tu disco te lo pregunta
siempre, con el motivo escrito.

```bash
curl -s localhost:8000/autonomy            # modo, proyectos marcados, pendientes
curl -s -X POST localhost:8000/autonomy/modo -d '{"modo":"solo"}'   # solo|permiso|pleno
```

`pleno` **no** significa "sin preguntar": el nivel 3 pregunta en los tres modos.
No existe un modo que dispense de la cola (A-036).

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