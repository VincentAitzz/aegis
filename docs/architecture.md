# Arquitectura

## 1. Visión general

Uno de los requisitos duros del proyecto es que **el móvil no tenga ni una sola
dependencia de Internet**: el backend vive en la máquina local y el acceso se hace
vía una red de malla privada (Tailscale). El bridge expone un contrato REST y es
el **único** que ejecuta tools.

```
[ Aegis Console ]  ──REST──►  POST /autopilot/start {prompt, project}
        │                 ◄──      {run_id}                (y ya)
        │                    GET /autopilot/{run_id}      (la traza crece)
        ▼
[ Bridge :8000 ]  ──►  bucle modelo→tool propio (autopilot.py)
                        │  el modelo elige QUÉ tool; el bridge la EJECUTA
                        │  whitelist + rollback de sintaxis + cola de aprobación
                        ▼
                   [ Ollama :11434 ]  ──►  el modelo local
                        │
                        ▼
              traza por paso ──► data/logs/runs/<run_id>.jsonl
```

> **Este diagrama cambió en la Fase 1 (2026-10-04).** Antes tenía dos motores:
> `POST /tasks` creaba runs en Hermes (`:8642`) empujados por un WebSocket, y
> `POST /autopilot` ejecutaba tools. Los dos con capacidad de actuar. Se borró
> el de Hermes: `docs/motores.md` §6 — *"dos motores con tools son dos sitios
> donde puede vivir un guardarraíl"* — y el hecho de que nada lo iniciara desde
> el 2026-10-03. Este documento describía las dos rutas como API viva en quince
> sitios, que es lo que hace que un documento desactualizado sea peor que
> ninguno: da la seguridad de que el otro se leyó.

## 2. Componentes

### 2.1 Bridge (`bridge/app/`)

- `main.py` — API REST y **nada más**: 33 rutas, todas detrás de `exigir_token`
  salvo las seis de lectura de `LECTURAS_ABIERTAS`. El WebSocket `/ws` y las cuatro
  rutas `/tasks*` se quitaron en la Fase 1 (ver §1).
- `hermes_client.py` — **solo el health check** de la gateway. Alcanzable desde
  `GET /health`, que es lo que consulta el watchdog de `infra/stack.sh`. No crea
  runs ni los gobierna: `create_run`, `approve`, `steer`, `stop` y el consumidor
  SSE se fueron con el motor.
- `autopilot.py` — el bucle modelo→tool. `run_autopilot` es un envoltorio que
  llama a `_bucle` y le pone el veredicto (`app/veredicto.py`); el bucle a secas
  tiene seis `return`, y calcular el veredicto en cada uno eran seis copias de la
  misma regla.
- `veredicto.py` — qué pasó en un run, con un dato: `completado`,
  `esperando_ok`, `incompleto`, `parado`, `roto`, `rechazado`. Se calcula desde
  la **traza**, nunca desde `final_text` (A-016).
- `llm.py` — listado de modelos y **embeddings** locales (`/api/embed`). Con tope
  de 60 s: se awaita al empezar y al terminar cada run, y sin tope un `/api/embed`
  colgado colgaba el run sin límite.
- `telemetry.py` — observabilidad: eventos JSON en `data/logs/bridge.jsonl` y por
  run en `data/logs/runs/<run_id>.jsonl`.
- `memory/` — 'cerebro' del proyecto: `episodic.py` (ChromaDB + embeddings de
  Ollama) y `sqlite_graph.py` (grafo conceptual), con `ProjectMemory` como
  fachada. El backend `graphiti` se borró en la Fase 1: sus requisitos estaban
  comentados en `requirements.txt` y el módulo se declaraba a sí mismo "sin
  verificar, nunca ejecutado".
- `verifier.py` — la puerta: convierte "el modelo dijo que lo hizo" en "lo
  comprobamos". El `gate` ejecuta el comando del proyecto **en un hilo**; llamado
  en el event loop congelaba el bridge entero durante `tsc`/`vitest`.

### 2.2 App (`mobile/lib/`)

Clean architecture por capas:

```
core/        theme (aegis_palette + aegis_theme), config (API_HOST), network,
             widgets (glifo, arranque, panel, LED, superposición)
data/        models (DTOs) + repositorio (AgentRepositoryImpl)
domain/      contrato AgentRepository (interfaz)
presentation shell (AegisSection + AegisShell), providers, pages, widgets
```

#### El shell: una sección es una entrada, no una pantalla

`presentation/shell/aegis_section.dart` tiene el registro `kSecciones`. **Añadir
un apartado es añadir una línea ahí**: `alias`, etiqueta, iconos, la fábrica de
su pantalla y si necesita el puente. El shell (`AegisShell`) pinta la barra y
un `IndexedStack` —que conserva el estado de todas las secciones—, y pone la
puerta puesta a las que lo necesitan: sin bridge, la sección explica en vez de
quedarse en blanco.

Esto existe porque antes `app.dart` iba directo a `HomePage`, que eran 626 líneas
con tres widgets privados dentro. Cuando por fin haya cuatro apartados, nadie
recuerda qué había en la línea 300.

#### La marca es código, no imágenes

El glifo se pinta en vivo con `CustomPaint` (`core/widgets/aegis_mark.dart`), con
el núcleo latiendo. **No hay ninguna imagen de marca en el APK**: lo único que se
empaqueta de `assets/` son las tipografías. Los PNG de `assets/brand/derivados/`
son solo para el lanzador, que no admite un widget, y salen de
`assets/brand/derivados/aegis_mark.svg`. `assets/brand/inbox/` es el almacén de
referencias del usuario: no se declara en `pubspec.yaml`, así que no entra en el
build. Ver `mobile/assets/brand/README.md`.

El color de marca (`aegis_palette.dart`) es lo que `mcp_ops.current_brand()` lee
para no compilar un APK sin identidad. Busca en `RUTAS_PALETA` —varios nombres,
el bueno el primero— y si no encuentra ninguna **niega en vez de adivinar**
(A-028).

#### El arranque solo dice lo comprobado

`core/widgets/boot_screen.dart` recibe de `app.dart` lo que el provider de salud
**sabe de verdad**, y lo imprime línea a línea. No anuncia nada que no haya
preguntado: si el puente no contesta, lo dice. Antes anunciaba `handshake ok` y
`auth ok` a ciegas (A-031).

- **`API_HOST`**: inyectado en build-time; `localhost` (emulador/adb reverse) o
  `aegis.<tailnet>.ts.net` (malla MagicDNS). Sin IPs estáticas.
- **Deduplicación**: cada evento tiene `dedupeKey` basada en `tipo + payload
  completo` (JSON). Si la clave se construye sobre un prefijo truncado, colapsa
  deltas consecutivos (el `run_id` es constante) — ver sección Pitfalls.
- **TaskSessionController** (Riverpod `Notifier`): crea el run, abre el WS,
  acumula `finalText` desde `text.delta`, gestiona aprobaciones, steer y stop.
- Reconexión del WS con backoff (2 s→30 s, máx. 8); al reconectar se re-suscribe
  y el replay + dedupe hacen el resto.

### 2.3 Qué puede hacer sin preguntar (`app/autonomy.py`)

Aegis tiene 18 herramientas deterministas. Lo que faltaba era una respuesta a
*¿qué puede hacer sin preguntarme?*. Sin ella hay dos opciones y las dos son
malas: no dejarle hacer nada —y entonces es un buscapersonas— o dejarle todo —y
entonces la confianza es un acto de fe que se gasta la primera vez que se
equivoca.

La autonomía es una **lista explícita en tres niveles**, y la decide el **nombre**
de la tool, no el contexto:

| Nivel | Tools | Qué hace |
|---|---|---|
| `libre` | `aegis_read_file`, `repo_verify`, `projects_list`, `registry_list`, `ficha_read`, `db_query`, `adb_devices`, `deploy_estado`, `verify_deploy` | Sin preguntar, sin avisar |
| `con_permiso` | `aegis_write_file`, `aegis_patch_file` | Solo en proyectos marcados. Los tres guardarraíles intactos |
| `requiere_ok` | `db_migrate`, `neon_branch`, `build_apk`, `install_apk`, `project_create`, `adb_connect`, `deploy_smoke` | Siempre pregunta, en los tres modos |

Un tool nueva cae en `requiere_ok`: un nivel por defecto permisivo concede
permisos a medida que se añaden herramientas, sin que nadie lo decida.

**El ciclo**: Aegis se para con `fin: "esperando_ok"` y una petición con el motivo
en sus palabras. Apruebas → token de un solo uso → relanzas con `token` y sigue.
Deniegas con un motivo → ese motivo se inyecta en el prompt del siguiente run
bajo *Lo que ya me dijiste que no*. No hay modo que dispense de la cola (A-036).

El token valida **la llamada, no el run**: un permiso para
`aegis_write_file(path=X)` no autoriza `aegis_write_file(path=Y)` (A-033).

**El proyecto marcado es la puerta principal**, y por algo concreto: sin
verificador declarado no hay contra qué comprobar que el trabajo quedó bien. Tres
de los ocho proyectos del registro no lo tienen, así que sus interruptores están
deshabilitados y **dicen cuál falta** (A-035).

**La base se mide antes de escribir**, una vez por run, y se compara por **número
de problemas**, no por rojo/verde: `trazeurs` llega con 452 issues de la
plantilla, así que "está en rojo" es su estado normal. Y un verificador que no se
puede ejecutar da `rojo: None`, no `True`: un freno permanente es un freno que
nadie mira (A-035).

### 2.4 Tus cosas y lo que Aegis recuerda

`app/notas.py` guarda notas, tareas y recordatorios en `data/aegis/notas.sqlite3`.
**No van a la memoria del agente** a propósito: `app/memory` guarda episodios de
runs y solo se inyectan al prompt; una nota tuya no es un episodio, y mezclarlas
haría que borrar una nota tocara la memoria del modelo.

Lo que sí se expone de la memoria (`GET /memoria`) es **solo metadato** —qué
hizo, cuándo, con cuántas herramientas— y **solo `outcome == success`**. El
prompt y la respuesta se quedan en su almacén: todo lo que le cuentas a Aegis
queda a un `GET` de distancia, y el texto no aporta para la lista que se pinta
(A-016).

`GET /runs` lee los JSONL de disco. Antes el historial vivía solo en
`_AUTOPILOT_RUNS`, un dict en memoria con tope de 50: eso no era una caché, era
una pérdida de datos disfrazada de feature. Y **los runs de autopilot no
escribían JSONL** —los escribía `relay`, que solo ve Hermes—, así que la
persistencia fue A-034 hasta que `_run_autopilot_once` los escribió.

## 3. Contrato

### 3.1 REST

Las 33 rutas de API. Las de lectura sin token son las seis de `LECTURAS_ABIERTAS`
(`/health`, `/models`, `/enfoques`, `/actividad`, `/origen`, `/proyectos`); todo lo
demás pide `X-Aegis-Token`.

**Correr un run**

| Método | Ruta                       | Body                | Respuesta |
|--------|----------------------------|---------------------|-----------|
| POST   | `/autopilot`               | AutopilotIn         | `{model, answer, steps, trace, fin, estado, duracion_s}` (síncrono) |
| POST   | `/autopilot/start`         | AutopilotIn         | `{run_id}` (devuelve ya) |
| GET    | `/autopilot/{run_id}`      | —                   | traza por paso, `fin`, `estado` |
| POST   | `/autopilot/{run_id}/steer`| `{text}`            | — (entra como turno más) |
| POST   | `/autopilot/{run_id}/stop` | —                   | — (corte entre pasos) |

**La puerta de aprobación**

| Método | Ruta                              | Para qué |
|--------|-----------------------------------|----------|
| GET    | `/aprobaciones`                   | pendientes + aprobadas sin gastar |
| POST   | `/aprobaciones/{id}`              | aprobar/denegar → token de un solo uso |
| POST   | `/aprobaciones/{id}/motivo`       | el motivo de una denegación (se inyecta al run siguiente) |
| POST   | `/aprobaciones/{id}/ejecutar`     | cobrar la llamada aprobada **sin modelo de por medio** |

**Autonomía, ficha, historial, notas, despliegue**

`GET /autonomy` · `POST /autonomy/modo` · `POST|DELETE /autonomy/{alias}` ·
`GET|POST /fichas/{alias}` · `GET /memoria` · `GET /runs` · `GET /runs/{run_id}` ·
`GET|POST /notas` · `DELETE /notas/{id}` · `GET|POST /tareas` · `PATCH /tareas/{id}` ·
`GET /deploys` · `POST /deploys/{id}` · `POST /deploys/{id}/instalar` ·
`GET /actividad` · `GET /origen` · `GET /proyectos` · `GET /enfoques` ·
`GET /models` · `GET /health`.

**Una sola puerta, y es `exigir_token`.** No hay segunda superficie. Antes había
tres caminos —HTTP, WebSocket y Hermes— y cada uno necesitaba su propia
comprobación: el WS tenía su propia porque la API de WebSocket del navegador no
puede poner cabeceras en el handshake. Un canal más es un guardarraíl más que
nadie recuerda. `tests/test_puerta_http.py` lo verifica contando rutas, no
confiando en la lista.

### 3.2 El `fin` de un run, y el estado que va con él

`fin` dice **por qué paró**; `estado` dice **si terminó**. Son preguntas distintas
y hasta la Fase 1 solo había una, lo que hacía que 38 de los 59 runs con
`fin: sin_tools` del histórico —que habían ejecutado su tool y contestado bien—
contaran como fracasos.

`estado` sale de `app/veredicto.py` y tiene seis valores, no dos:

| estado | significa |
|---|---|
| `completado` | el modelo paró solo, hubo tool en verde, y respondió |
| `esperando_ok` | esperando a una persona (no es un fallo) |
| `incompleto` | se paró sin responder, o sin ninguna tool verde |
| `parado` | lo paró quien lo lanzó |
| `roto` | el modelo no respondió, o el run reventó |
| `rechazado` | la puerta o la autonomía lo frenaron |

`completado` **no** significa "el trabajo estaba bien hecho": significa que el
agente cree que terminó y hay una tool que lo sostiene. La calidad la pone
`verifier.py`. Y `bin/medir-runs` aplica **la misma regla** a los ficheros del
histórico, que es lo que hace comparables el antes y el después.

### 3.3 WebSocket

No hay. Se quitó en la Fase 1 con el motor de Hermes. La traza se lee por
`GET /autopilot/{run_id}`, que ya devuelve los pasos según ocurren.

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
4. **Google Android auto-retos**: pasar `--dart-define` en `flutter build` y en `run`.
5. **La memoria puede ser la causa, no el efecto**: un `success` sin evidencia se
   reinyecta al prompt como "episodio similar resuelto" y el modelo copia el
   patrón. Medido: 3 episodios falsos ⇒ 0/8 tool calls; sin ellos, 7/8. Por eso el
   veredicto exige tool ejecutada en la traza y el `recall` solo inyecta
   `success` (lección A-016).
6. **Un prompt grande no es el problema por ser grande**: recortar 10 kB a 2 kB no
   cambió nada, porque el bloque tóxico eran 788 chars de recall. Ablar por capas
   antes de parchear la primera que se ve.
7. **`fin` no dice si el run terminó** (Fase 1). 38 de los 59 runs con
   `fin: sin_tools` del histórico habían ejecutado su tool y contestado bien;
   el `fin` los enterraba como fracasos y el sistema no tenía forma de distinguir
   "terminé" de "me rendí". La etiqueta se calculaba en `hooks.py`, cableado a un
   motor que llevaba 24 h sin iniciar un solo run. Lo grave no es que faltara el
   dato: es que la invariante estaba **escrita y sin aplicarse**.
8. **Un `subprocess.run` en una corrutina congela el bridge entero** (Fase 1).
   `verifier.gate` es `async def` y llamaba a `ejecutar()` —`tsc`, `vitest`, minutos—
   directamente. `/health`, el poll del móvil y el propio
   `POST /autopilot/{run_id}/stop` no se atendían hasta terminar la verificación:
   **parar un run durante su propia verificación era imposible**. El mismo
   razonamiento ya estaba escrito en `autopilot._bucle` para las tools; aquí no
   se aplicó.
9. **Un timeout `read=None` en la memoria cuelga los runs** (Fase 1).
   `embed_texts` se awaita al empezar **y al terminar** cada run. Un
   `/api/embed` que acepta la conexión y no contesta dejaba el run colgado sin
   límite ni `fin` que lo explicara. La memoria es degradable en todas partes, y
   ese timeout era la excepción que la hacía capaz de tumbar lo que no debía.
10. **Un instrument que no corre se disfraza de instrumento** (A-090, y el
    `graphiti` borrado en la Fase 1): un backend de grafo con los requisitos
    comentados en `requirements.txt` y cuyo módulo decía "nunca ejecutado". Una
    rama que nadie ha ejecutado no es una opción, es una suposición con `import`
    debajo.

## 6. Ruta futura

La ruta de modelos la fija `docs/motores.md` (clases de latencia T0/T1/T2,
flota con turnos, tabla de asignación derivada de perfiles medidos). Aquí solo lo
que este documento necesita:

- **T0 no pasa por el modelo**: alarma, nota, listar y leer son deterministas. Hoy
  existen como REST (`POST /notas`, `POST /tareas`) pero **no están en el schema del
  agente**, así que un encargo de ese tipo sí paga un run completo. Es el
  camino corto que falta.
- **Presupuesto de latencia**: `run_duration_s` valía `0.0` **hardcodeado** y ahora
  se mide en `autopilot.py`, con `ms` por paso en la traza. Sin ese número no hay
  clase de latencia posible, y por eso el orden de las fases de `motores.md`
  empieza midiendo.
- **Más VRAM**: 6 GB no dan para convivencia de modelos; por eso el diseño es de
  turnos y no de flags.

## 7. Capas críticas de ejecución

Tres capas: **aislamiento**, **observabilidad** y **memoria**. Un solo motor:

```
[Bridge :8000]
      │
      ├─ POST /autopilot/start
      │     ├─ build_system_prompt: metodo + quien eres + ficha + enfoque
      │     │                     + recall + denegaciones   (7 953 chars)
      │     ├─ Ollama :11434 ──► el modelo elige QUÉ tool
      │     ├─ autonomy.decide() ANTES de ejecutar  (niveles: libre / con permiso / requiere OK)
      │     ├─ _execute en un hilo  ──► mcp_ops: whitelist, denylist,
      │     │                              escaneo de secretos, rollback de sintaxis
      │     ├─ verifier.gate en un hilo ──► el comando del proyecto (tsc, vitest…)
      │     └─ traza por paso ──► data/logs/runs/<run_id>.jsonl
      │
      └─ al terminar: _registrar_run ──► memoria (SOLO success con tools)
                          + veredicto (app/veredicto.py) + duracion_s

   Veredicto: traza ──► ¿hubo tool en verde? ¿respondió?   ← nunca desde final_text
   Memoria:   al prompt solo sube un `success` con tools nombradas.
```

Las dos reglas que hacen que esto no se rompa, y las dos son de la Fase 1:

- **El veredicto se calcula en un solo sitio.** `autopilot._bucle` tiene seis
  `return`; el veredicto se añade en el envoltorio, no en cada uno.
- **El veredicto sale de la traza, y la traza se escribe entera.** El JSONL recorta
  el `answer` a 1.000 chars, así que un veredicto recalculado sobre lo escrito daría
  un número distinto del que tuvo el run.

### 7.0 Dónde se prueba la app (y por qué no en tu teléfono)

El emulador de `infra/mobile/emulador.sh` replica el galaxy a17: **Android 16
(API 36), 1080x2340, 450 dpi**, la misma versión y geometría reales (medidas
con adb). Lo que **no** se replica es la ABI: el teléfono es arm64-v8a y esta
máquina es x86_64.

- `install_apk` apunta al emulador por defecto. `resolver()` **no tiene** un valor
  por defecto que alcance el teléfono: el destino se nombra, siempre.
- Instalar en el teléfono pasa por `app/deploy.py`: verificación (analyze, tests
  y humo en emulador), **autorización de un solo uso** aprovada en el móvil.
  Instalar y abrir son pasos separados, y por defecto solo se instala.
- **El aviso lo publica Aegis, no el shell.** El puente solo despierta al
  receptor (`am broadcast`); la notificación la pone `NotificacionReceiver`, que
  lee `/deploys` y la publica con el icono, el canal y el toque de Aegis. Con
  `cmd notification post` la firmaba `com.android.shell`: sin su icono, sin su
  permiso (`POST_NOTIFICATIONS` es de la app) y sin nada que abrir. Es A-042.
- **La entrega se comprueba.** `_verificar_aviso` lee `dumpsys notification` y, si
  el registro no está, devuelve `"AVISO NO LLEGÓ"` con el `appop` incluido. Un
  `exit=0` no es prueba de nada: durante un tiempo el puente escribió «aviso
  enviado» de algo que no existía.
- **Un aviso, y uno solo.** La app publica un aviso con **ID fijo** y el número de
  pendientes, así que se actualiza en sitio en vez de acumularse; el puente
  deduplica por motivo dentro de `VENTANA_AVISO` (300 s). El aviso va **al
  teléfono** (`AVISO_INTERMEDIO`, configurable con `AEGIS_AVISO_INTERMEDIO`),
  porque se aprueba desde ahí: un aviso que hay que decidir en el móvil tiene que
  llegar al móvil. Sin teléfono a mano cae al emulador. Antes iba al emulador
  siempre, y la razón era buena (el aviso viejo no era accionable) pero ya no
  aplica (A-042, A-043).
- **Aprobar instala, sin intermediarios.** `POST /deploys/{id}/instalar` canjea el
  token **dentro del bridge** y llama a `adb install` en un hilo. Antes aprobar
  devolvía un token y el agente tenía que volver a pedir la instalación para
  gastarlo: eso no era segundo plano, era que el agente se enterara. El token no
  sale de ahí, que es lo único que lo mantiene de un solo uso.
- **Lo aprobado y lo ejecutado son el mismo binario.** La petición guarda
  `tamaño-mtime` del APK; al instalar se vuelve a mirar y, si cambió, se niega.
  Entre pedir el OK y pulsar «sí» pueden pasar minutos, y en ese rato una
  compilación deja otro APK en la misma ruta.
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

> **Dos procesos, un estado — y por qué ya no hay dos procesos.** El MCP de
> `aegis-ops` corría aparte del bridge FastAPI, y por eso el registro de orígenes
> va por HTTP y el estado de despliegue a un fichero: en memoria, el botón de
> aprobar del móvil nunca habría visto la petición y el humo siempre habría
> fallado.
>
> **El perfil del usuario va en un fichero, y en dos tramos.** OpenClaw inyecta
> un `SOUL.md` y un `USER.md` en cada turno; aquí el prompt es el presupuesto
> —A-016: este 7B deja de emitir `tool_calls` cuando crece, y A-080: se
> re-evalúa en cada paso—, así que `bridge/quien-eres.md` se parte: la sección
> «Cómo hablo contigo» (543 de 600 chars) va en todos los runs, y el resto se lee
> con `aegis_read_file` cuando hace falta. No hay tool propia de lectura: duplicar
> `aegis_read_file` costaría 1 500 caracteres de schema en cada paso de cada run
> por no tener que escribir el nombre de un fichero (A-082).

> Ese camino se retiró el 2026-10-04 y el módulo se borró del todo en la Fase 1:
> el agente que Hermes lanzaba desde `POST /tasks` corría con
> `platform_toolsets.api_server: []`, es decir **sin toolsets**, así que los MCP
> `aegis-ops` y `aegis-memory` no los veía nadie. Y el repo ya había medido que un
> 7B dentro de Hermes no emite `tool_calls` fiables: el autopilot existe por eso.
> `app/mcp_ops.py` **sigue existiendo** —el autopilot lo usa como librería, que es
> de donde salen las 22 tools del schema—; lo que se quitó fue la exposición MCP
> (`mcp.run()`) y, en la Fase 1, `app/mcp_memory.py`.

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
  - `data/logs/runs/<run_id>.jsonl` — la secuencia completa del run. Lo escribe
    `main._escribir_jsonl_de_autopilot`: `task.created`, un `tool.completed` por
    paso, `run_duration_s` y el terminal (`task.done`/`task.failed`/
    `task.stopped`) con `fin`, `estado`, `completado`, `resumen` y `error`.
- **`run_duration_s` se mide de verdad** (Fase 1). Valía `0.0` hardcodeado con la
  forma del métrico ya lista: un dato falso con forma de dato, que es la clase de
  hueco más difícil de ver porque produce números. Además, `autopilot` anota `ms`
  por paso en la traza, que es lo que hace falta para un presupuesto de latencia.
- `GET /health` incluye `memory` (estado de los almacenes) y la telemetría se
  configura en `lifespan` desde `LOG_DIR` (`.env`).
- `bin/medir-runs` reetiqueta el histórico con la regla actual y da el reparto de
  estados. Es el instrumento de la línea base: un número que solo existe en una
  conversación no es una línea base.

### 7.3 Memoria ('cerebro' del proyecto)

**Dos** niveles, cada uno con su rol (ver §7.1 para el porqué de que sean dos y no
tres):

| Nivel | Almacén | Backend | Rol |
|-------|---------|---------|-----|
| (b) Conceptual | grafo de conceptos, episodios ligados | `sqlite` (el único) | enlaces entre conceptos descubiertos juntos |
| (a) Episódica | embeddings + índice vectorial | ChromaDB embebido + Ollama (`nomic-embed-text`) | "¿ya resolvimos algo así?" |

Ciclo de vida (automatizado en el bridge):

1. **Recordar** — `main._registrar_run`, al terminar un run de autopilot:
   `ProjectMemory.remember()` guarda el episodio en el grafo SQLite con sus
   conceptos y lo indexa por embedding cuando Chroma está disponible.
   **El veredicto lo decide la traza, no el texto**: `app/veredicto.py`. Sin una
   tool en verde, el episodio no se graba como `success` (A-016, medido 0/8 → 7/8
   al quitar el veneno).
2. **Recordar antes de crear** — `POST /autopilot` y `/autopilot/start` llaman
   `recall(prompt)` y lo inyectan como bloque `EXPERIENCIA PASADA RELEVANTE`.
   **El filtro está en `render_context`**: `recall` devuelve lo más cercano
   semánticamente sin mirar el `outcome`, así que el filtrado a `success` ocurre en
   la frontera de inyección. Un `failed` bajo el rótulo de "resueltos antes" es
   instrucción contraria, y el 7B la copia.
3. ~~**Consultar a demanda** — `lecciones(alias, tema)`.~~ **Retirado el
   2026-10-14**, junto con el índice del prompt: ocupaban el 54 % del system
   prompt, la tool tuvo **0 llamadas** en los 857 run logs del repo, y el
   comportamiento que describen no cambiaba con ellas (A-014 se repitió 3/3 con y
   sin). `lessons/{alias}.md` sigue en el repo como documentación; los números
   están en el docstring de `load_lessons` (`app/autopilot.py`).

   El servidor MCP de memoria (`app/mcp_memory.py`) se borró en la Fase 1 con el
   resto de la exposición MCP: era un segundo camino de entrada a la memoria y no
   lo usaba nadie.

Config (`.env`): `MEMORY_ENABLED`, `MEMORY_DIR`, `MEMORY_RECALL_K`,
`MEMORY_GRAPH_BACKEND` (`sqlite`|`off`; `graphiti` se retiró en la Fase 1),
`EMBED_MODEL`.

Degradación intencionada: sin `chromadb`/Ollama la memoria **no rompe el
bridge** — la episódica se desactiva sola y el grafo (SQLite, sin deps)
sigue sirviendo recuperación léxica. Los tests (`tests/test_memory.py`)
verifican este comportamiento.
