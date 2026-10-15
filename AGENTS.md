# AGENTS.md — aegis

> [!IMPORTANT]
> En este repo **opencode no es el autor**: es el supervisor de Aegis. El código
> de producto lo escribe Aegis (el agente local) y opencode hace el spec, revisa,
> corrige y **deja la lección**. Ver §2.

## 1. Qué es Aegis

Consola de operación del negocio freelance, local-first:

```
[App Flutter] ──REST──► [Bridge FastAPI :8000] ──► [Ollama :11434]
                                  │                          └──► autopilot: ejecuta las tools
                                  ├── autopilot: bucle modelo→tool, ejecución determinista
                                  ├── memoria episódica (Chroma + SQLiteGraph)
                                  └── telemetría
```

- `bridge/` — API FastAPI, memoria, telemetría y el autopilot.
- `mobile/` — cliente Flutter (`aegis_console`).
- `infra/` — scripts de arranque (`ollama/`, `hermes/`, `tailnet/`, `mobile/`).
- `bridge/quien-eres.md` — lo que Aegis sabe de ti. **No lo escriba Aegis solo**
  (se escribe con `quien_eres_actualiza`, nivel 3). Una sección, «Cómo hablo
  contigo», va en todos los runs con tope de 600 chars; el resto se lee con
  `aegis_read_file` cuando el encargo lo necesita (A-082: una tool propia serían
  1 500 chars de schema que se pagan aunque no se use).
- `bridge/bin/lab/` — instrumentos de **medición** (`medir-*`, `measure-models`,
  `derivar-ficha`). Nada del operarlo los llama, y por eso no están en `bin/`
  junto a `probe-toolcall.sh` y `check-imports.py`, que sí lo son.
- `docs/` — arquitectura y runbook. **Actualízalos cuando cambie el operarlo.**

## 1.1 Hacia dónde va esto

El objetivo de Aegis es ser **tu asistente ambiental**: que te oiga sin que pulses
nada, entienda lo que dices, actúe sobre tus herramientas, recuerde lo que importa
de ti, y te avise de los problemas que encuentra. Está en `docs/vision.md`, con
las fases, los números y el orden. La autoridad de cada decisión está en
`docs/decisiones/`.

Hoy Aegis es otra cosa —un agente que escribe código y deja rastro—, y por eso
las invariantes de abajo son de *trazabilidad*. **Cambaron de forma el
2026-10-05** (`docs/decisiones/001`): el objetivo sigue siendo el mismo, pero ya
no es «Aegis no hace nada por su cuenta», es «**Aegis no hace nada irreversible
por su cuenta, y siempre se puede saber qué hizo y por qué**». Lo que queda
intacto es lo importante: ninguna acción con consecuencia sin que se pueda
auditar.

**Antes de construir cualquier cosa**, lee `docs/vision.md` §2. Casi todo lo que
se ha construido aquí salió de un caso concreto, y el caso concreto es
lo único que decide si algo vale la pena.

**Invariantes vigentes (2026-10-05).** Las de esta tabla, no las de abajo, que
quedaron sustituidas:

| Invariante | Qué obliga |
|---|---|
| **Nada irreversible sin OK** | Toda acción con consecuencia pasa por aprobación de un solo uso. **Ningún pago es automático**, ni con permiso de antemano. |
| **Se apaga bien** | Todo dispositivo tiene timeout y estado seguro por defecto. Si Aegis muere, nada queda en un estado raro. |
| **Lo íntimo no sale** | Audio, fotogramas y rostros no van a terceros sin permiso explícito y medible. |
| **Se puede auditar** | Traza y veredicto de todo, incluidos los sentidos: quién vio qué, cuándo. |
| **La memoria es tuya** | Se puede ver, editar y borrar lo que Aegis sabe de ti. |

**El bridge es de un solo proceso** — esto no cambió, y sí aplica a móvil y reloj
como clientes. El estado de control de un run en marcha (parar, dirigir) vive en
memoria del proceso; con dos workers, un `stop` que llegara al otro daría un 404
que miente. `run.sh` rechaza `BRIDGE_WORKERS != 1` en vez de dejarlo pasar:
escalar por encima requiere persistir ese estado primero.

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
> Un arreglo que solo vive en el commit no lo ve nadie: la próxima vez se repite.
> La lección se escribe para quien viene, y **el agente ya no la lee** — desde el
> 2026-10-14 no van al prompt (ver §3, «Las lecciones»). Por eso la razón de una
> regla nueva va también junto al código que la impone.

### Cuándo usar cada camino

| Necesito | Camino |
|---|---|
| Que una tool se ejecute de forma fiable | **`/autopilot`** (determinista, con traza) |
| Razonar, resumir, redactar | **`/autopilot`** también. Es el único camino que queda |
| Una alarma o una nota, sin modelo | `POST /tareas` o `POST /notas`, directo |
| Cambiar el diseño, la arquitectura o los invariantes | **opencode, directamente** |

Motivo técnico: los modelos de 6 GB disponibles (`qwen2.5:7b`) **no emiten
`tool_calls` fiables** en los runs de Hermes: escriben el JSON de la llamada en
el texto. El autopilot lo resuelve parseando la intención y ejecutándola. Si
necesitas tools, va por autopilot.

### Lo que se midió, y sigue valiendo

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

Y el orden importa: **purgar la memoria es parte del arreglo**, no una limpieza
de final. Con la memoria envenenada no hay nada que medir.

Las dos reglas que salieron de eso siguen siendo la regla:

- **El veredicto sale de la traza, nunca de `final_text`.** Vive en
  `app/veredicto.py`, y lo calcula `run_autopilot` en un envoltorio —el bucle a
  secas tiene seis `return` y en cada uno eran seis copias de la misma regla.
- **Al prompt solo suben episodios `success` con tools nombradas.** Un fallo
  inyectado como solución es instrucción contraria.

### El `fin` no dice si el run terminó

Hasta la Fase 1 (2026-10-04) un run terminaba con un `fin`, y el `fin` no
distinguía "terminé" de "me rendí". `sin_tools` con una tool ejecutada y una
respuesta buena **es** un run terminado: el modelo llamó, leyó y contestó. Como
el `fin` no lo decía, **38 de los 59 runs con `fin: sin_tools`** del histórico
contabilizaban como fracasos.

Reetiquetados los 133 runs con la regla actual (`bin/medir-runs`):

| estado | n | % |
|---|---|---|
| `completado` | 60 | 45,1 % |
| `esperando_ok` | 37 | 27,8 % |
| `incompleto` | 30 | 22,6 % |
| `roto` | 4 | 3,0 % |
| `rechazado` | 1 | 0,8 % |
| `parado` | 1 | 0,8 % |

Lo grave no era que faltara el dato —la traza lo tenía todo—, sino que la
invariante de A-016 estaba **escrita y sin aplicarse**: `hooks.py` estaba cableado
a un motor que llevaba 24 h sin iniciar un run. Un invariante que nadie ejecuta
no es un invariante; es una intención.

## 3. Protocolo de delegación

### Desde la consola

Toda ruta que **cambia algo** pide `X-Aegis-Token` desde 2026-10-04. No lo pongas
a mano en los ejemplos: `bridge/bin/api` lo lee de `bridge/.env`, no lo imprime,
y existe para que la documentación no se quede mintiendo.

```bash
cd bridge
bin/api POST autopilot '{"project":"portafolio","max_steps":16,"instructions":"<reglas>","prompt":"<tarea>"}'
```

Las lecturas también pasan por ahí (`bin/api GET runs`) aunque no lo necesiten:
si el mismo comando sirve para leer y para actuar, no hay dos formas de llamar al
bridge y una de ellas se queda sin llave.

Síncrono: devuelve `answer`, `steps`, `trace` y `fin` (por qué terminó). Es lo
que usa el resto del operarlo y los scripts.

### Cuando Aegis necesita tu OK

`app/autonomy.py` reparte las 22 tools en tres niveles. Si un run topa una tool
de nivel 3 (`db_migrate`, `neon_branch`, `install_apk`, `build_apk`,
`project_create`, `adb_connect`, `deploy_smoke`), **no ejecuta**: deja una
petición y termina con `fin: "esperando_ok"`.

```bash
cd bridge
bin/api GET aprobaciones                # lo que espera tu OK
bin/api POST aprobaciones/<id> '{"decision":"aprobar"}'   # -> token
# relanzas con ese token:
bin/api POST autopilot/start '{"project":"aegis","prompt":"<lo mismo>","token":"<token>"}'
```

**Denegar con motivo** es lo que hace crecer la confianza: el motivo se inyecta
en el prompt del siguiente run, y Aegis no vuelve a proponerlo. Sin motivo,
denegar es un "no" que no se puede aplicar a la siguiente situación parecida.

El token valida **la llamada, no el run**, y es de un solo uso (A-033).

### Un solo motor: el autopilot

El autopilot es lo único que ejecuta tools, y desde la **Fase 1** (2026-10-04) es
lo único que ejecuta nada.

Hermes pasó a ser motor de conversación (`platform_toolsets.api_server: []` lo
deja sin toolsets), y luego se borró entero: `POST /tasks`, el WebSocket `/ws`,
`relay.py`, `hooks.py` y `graphiti.py`. No quedaban llamadores —los `run_*.jsonl`
de Hermes paran el 2026-10-03 y los `autopilot-*.jsonl` siguen—, y `docs/
architecture.md` seguía documentándolos como API viva en quince sitios.

Lo que **queda de Hermes** es una sonda: `GET /health` pregunta a la gateway si
está en pie, que es lo que consulta el watchdog de `infra/stack.sh`. Un semáforo
no es un motor.

Dos motores son dos sitios donde puede vivir un guardarraíl, y por eso el diseño
es: **quedarse con uno**. Un invariante que depende de un componente que ya no se
usa no es un invariante, es una intención (ver el caso de `hooks.py` en A-016).

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

### Enfoques: pensar antes de construir

Un **enfoque** son las instrucciones que solo valen mientras se piensa. Vive en
`bridge/enfoques/{nombre}.md` con su entrada en `_indice.json`, y se inyecta en el
system prompt **solo** en los runs que lo piden (`"enfoque": "arquitectura"`);
`GET /enfoques` dice cuáles hay.

No van en `metodo.md` a propósito: A-016 midió que el 7B deja de emitir
`tool_calls` cuando el prompt crece, y el prompt es el presupuesto. Un enfoque
inyectado a todo el mundo se paga en los runs de operación, que son los que más
necesitan llamar tools.

- `arquitectura`: requisitos no funcionales antes de nombrar tecnología, dos o
  tres opciones con su coste de cambio, y qué habría que falsar para estar
  equivocado.

Hubo también `idea`, y se borró: aterrizar una idea hasta poder escribir su ficha
ya lo hace `method_context()`, que va en todos los runs. Pagar lo mismo dos veces
no es un enfoque, es texto.

Añadir una fase es escribir un fichero. Sin código, sin enum, sin compilar.

### Las lecciones: ya no van al prompt

`bridge/lessons/{alias}.md` es el registro de por qué el código es como es, y
**no se borra**. Lo que cambió el 2026-10-14 es que **dejó de ser input del
modelo**: al prompt no va ni el índice ni la lección más relevante, y la tool
`lecciones(alias, tema)` se quitó del schema.

| | antes | después |
|---|---|---|
| system prompt | 17 155 chars | **7 953** |
| de los cuales, lecciones | 9 200 (**54 %**) | 0 |
| tools en el schema | 22 | 21 |

Tres razones, y las tres son mediciones:

1. **No cambiaba el comportamiento.** A-014 dice «no repitas la llamada idéntica
   que ya falló dos veces»; el modelo la repitió **3 de 3 con las lecciones
   inyectadas y 3 de 3 sin ellas**.
2. **La puerta no se usó nunca.** La tool `lecciones` tiene **0 llamadas** en los
   857 run logs del repo (`data/logs/runs/`, 2026-09-24 → 2026-10-14).
3. **El índice estaba truncado.** Con el tope de 8 000 chars listaba A-001…A-078
   de 121: se pagaba el 100 % para enseñar el 65 %.

Para volver a mirar el número: `bin/medir-prompt.py`. Y el A/B que justifica
que salieran, con su n y su comparativa, en `docs/medidas.md` §4.

**Al leer una lección, ábrela con un editor.** Si la regla te importa, está junto
al código que la impone y en el test que la comprueba; la lección entera es el
porqué, y el porqué no lo necesita un modelo de 7 GB.


### Desde el móvil, o cuando el run puede tardar

`POST /autopilot` es síncrono y un paso puede tardar medio minuto: para no
dejar al usuario mirando un spinner, están `POST /autopilot/start` (devuelve ya
un `run_id`) y `GET /autopilot/{run_id}` (la traza crece paso a paso).

```bash
RID=$(cd bridge && bin/api POST autopilot/start \
  '{"project":"aegis","prompt":"lista los proyectos"}' | jq -r .run_id)
(cd bridge && bin/api GET autopilot/$RID) | jq '{status,steps,fin}'
```

- `project` es lo que carga `bridge/lessons/{project}.md` y el `recall`.
- `instructions` van en el system prompt; el `prompt` es la tarea.
- `enfoque` es opcional y es lo único que enciende `bridge/enfoques/{enfoque}.md`.
- Las rutas del proyecto van con prefijo de alias: `portafolio/src/lib/db.ts`.
- `repo_verify(what='check'|'test'|'build')` es la única tool de verificación, a
  propósito: un 7B rinde peor con muchas tools que con una.
- Un escalar envuelto en objeto (`repo: {"type": "portafolio"}`) lo repara
  `coerce_args`: es la malformación típica del 7B y antes tumbaba el run.

**Antes de delegar, lee `bridge/lessons/{proyecto}.md`.** Si vas a repetir un
trabajo, las lecciones ya explican dónde se equivocó la última vez. Ábrelo con un
editor: ya no se inyecta en el prompt (§3).

## 4. Guardarraíles: intocables

Están en `bridge/app/mcp_ops.py`. Debilitarlos "para que algo funcione" es un
retroceso, aunque haya un bug de fondo:

| Guardarraíl | Qué evita |
|---|---|
| Whitelist multi-raíz (`PROJECTS`) | que el agente escriba fuera de los proyectos declarados |
| Denylist (`.git`, `node_modules`, `dist`, `build`, `.venv`…) | editar áreas generadas o versionadas a mano |
| Escaneo de secretos (escritura y lectura) | que una key acabe en un archivo o en un log |
| **Rollback de sintaxis** | un archivo roto llega al repo: si `dart format`/esbuild no parsean, se revierte |
| Parseo de tool-calls + reparación | que una llamada mal formada se cuele como texto |

Cuando un guardarraíl bloquea algo legítimo, **se amplía el guardarraíl**, no se
desactiva: el motivo de cada veto está en el mensaje.

## 4.1 La app se actualiza a sí misma, y por eso el puente tiene que estar al día

Hay **dos** caminos para poner una build en el móvil, y confundirlos cuesta una
tarde:

| Camino | Quién compila | Para qué |
|---|---|---|
| `bash infra/mobile/install-phone.sh` (USB) | tú, en local | **Instalación**: la primera vez, o al cambiar de firma |
| Ajustes → «Actualizar Aegis» | el bridge | **Actualización**: el día a día, sin cable |

El segundo es el día a día, y tiene una regla que no es negociable: **el bridge no
sirve un APK más viejo que su propio código.** Un APK viejo instalado como si
fuera nuevo deja la app peor que antes, y es el peor tipo de fallo posible: uno
que parece una mejora. Por eso `HEAD /apk/{base}` devuelve `409` con el motivo en
`x-aegis-motivo`, y la app lo enseña.

### La firma: por qué el camino USB **no** instala el APK de debug

Desde el 2026-10-13 la release se firma con una clave propia, en
`~/.config/aegis/key.properties` (fuera del repo, `chmod 600`). Antes usaba
`signingConfigs.getByName("debug")`, que es la clave **pública del SDK de
Android** — A-119.

No es «menos seguro»: es una vía directa a las semillas TOTP. En Android el
Keystore se indexa por paquete **y** certificado, así que cualquiera que genere un
APK con `com.aegis.aegis_console` y la clave de debug obtiene **la misma
identidad** y el mismo acceso a ese almacén. Y como una APK firmada en debug
funciona exactamente igual que una correcta, el error no se ve en la app: abre,
lista las cuentas y genera códigos buenos. Por eso `install-phone.sh`
**comprueba la firma antes de instalar** y aborta con código 1, y por eso la
build de release **falla** si no encuentra `key.properties` en vez de caer al
debug.

Para girar la clave hay que **desinstalar y reinstalar**: Android no acepta que
el sustituto venga de otro firmante.

Las dos cosas que hacen que la actualización funcione, y que ya se rompieron una
vez:

- **El motivo viaja en cabecera**, no en el cuerpo. La app pregunta con un
  `HEAD`, y un `HEAD` no tiene cuerpo. Y va **sin acentos**, porque las cabeceras
  viajan en latin-1 (A-105b).
- **Un `await` que puede fallar tiene `catch`.** Sin él, la excepción se come el
  `setState` y la pantalla se queda en «preguntando» para siempre, que es
  indistinguible de una red lenta (A-105).

Para probar el ciclo entero hacen falta **dos** builds: una que se instala a mano
con `install-phone.sh` y otra más nueva que se sirve. Con una sola, la app ve que
ya tiene la última y no hay nada que probar. Detalle en `docs/runbook.md` §4.1.2.

## 5. Operación (verificar antes de asumir)

**Antes de nada, en una máquina nueva:**

```bash
bash infra/setup.sh              # venv, .env, y comprobaciones. Idempotente.
```

Dice lo que falta en vez de fallar con un error de Python, y se puede volver a
ejecutar sin romper nada. Donde está el toolchain se decide en `bridge/app/entorno.py`
—variable de entorno, luego `PATH`, luego las rutas estándar—, no en un literal:
si añades una ruta de tu máquina a un fichero, el repo deja de arrancar en la de
los demás. El CI lo comprueba: la suite del bridge corre **sin Flutter, sin JDK y
sin SDK de Android**, a propósito.

## 5.0 Encender Aegis: lo normal es que ya esté encendido

Desde el 2026-10-14 hay unidades **systemd de usuario** (`aegis-ollama`,
`aegis-gateway`, `aegis-bridge`) y un timer de vigilancia. Si están instaladas,
**no hay que arrancar nada**: `bash infra/stack.sh estado` lo dice.

```bash
bash infra/systemd/instalar.sh      # instalar y activar (una vez)
bash infra/systemd/instalar.sh --desinstalar
journalctl --user -u aegis-bridge -f
```

De **usuario** y no de sistema a propósito: Aegis no es punto único de falla, y
un servicio de sistema lo haría depender de que la máquina esté encendida.
`infra/stack.sh` sigue existiendo porque funciona en todas partes —no hay
`systemd --user` en macOS— y porque es lo que se usa cuando algo va mal.

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

El teléfono (Tailscale `100.101.102.103`, que es un ejemplo): el **puerto adb
cambia en cada reinicio**. Las tools lo resuelven solas por mDNS; a mano:
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
- La PII de tus proyectos vive en sus bases, **no** en `bridge/data/` ni en los
  logs, y no se versiona. `bridge/fichas-privadas/` existe exactamente para eso y
  está fuera de git por construcción.

## 6.1 Las bases: de quién es cada una

Aegis **gestiona** las bases de los proyectos; no es dueño de sus datos. La
frontera se decidió el 2026-09-27 y está en `bridge/app/neon.py` y en
`bridge/app/projects.py`.

Tres reglas que no se negocian:

1. **Producción jamás desde el Bridge.** Toda operación va contra la rama
   registrada en el proyecto, que es la de desarrollo. La URL de producción solo
   aparece en un despliegue, con `wrangler secret put`.
2. **Quien llama no elige base.** `db_migrate` y `neon_branch` reciben un alias
   del registro, nunca una URL, un host o un nombre de rama libre. El error
   posible no es «aplicó a producción»: es «no encontré esa migración».
3. **Una sola credencial, ninguna contraseña duplicada.** `bridge/.env` tiene la
   `NEON_API_KEY`; las connection strings se piden a Neon por API en el momento
   de usarlas y se pasan a `psql` como variables `PG*`, nunca como argumento —
   en un argumento la contraseña aparece en `ps` para cualquiera de la máquina.

**Cada base se declara, no se supone.** Un proyecto dice qué motor usa (`neon`,
`supabase`, `postgresql`…) en su `registro/{alias}.json`, y solo entonces se le
puede dar un id de Neon: una base de otro motor no lleva id, y declararlo es un
error, no un detalle. La base propia de Aegis **no se migra con migraciones de
proyecto**, porque aún no tiene esquema: la memoria sigue siendo local.

Y por qué el id no está en el código: es de una organización concreta y no
significa nada en la máquina de nadie. Va en `bridge/.env`
(`NEON_PROJECT_AEGIS=`). Un repositorio público que lleva dentro el id de Neon de
alguien es un repositorio que ha enviado una credencial sin querer.

## 7. Verificación

No afirmes que algo funciona sin ejecutarlo:

```bash
# El bridge (rápido, siempre)
cd bridge && .venv/bin/python -m unittest discover -s tests -q   # ~700 tests
cd bridge && .venv/bin/python bin/check-imports.py               # el verificador de `aegis`
cd bridge && .venv/bin/python bin/medir-runs                     # reparto de estados del histórico
cd bridge && bash bin/probe-toolcall.sh qwen2.5:7b    # capacidad de tool-calling
# El proyecto que toca el agente
node scripts/check-syntax.mjs <archivos>               # solo sintaxis
```

En local, los tres comandos de `bridge/` tienen que estar en verde sin Flutter,
sin JDK y sin SDK de Android. No es que «no se usen»: es que **si dependen del
entorno, el CI no los puede correr** y el repo deja de ser verificable por quien
no tiene esa máquina. El CI hace los dos trabajos: corre la suite sin toolchain y
comprueba que, efectivamente, no lo hay.

`bin/medir-runs` es el que **no** puede faltar cuando se toca `app/veredicto.py`
o el bucle: sin él no hay forma de saber si un cambio mejoró o empeoró el
comportamiento, porque la etiqueta `fin` por sí sola cuenta los runs que
terminaron como fracasos. Es el mismo criterio que aplica a los ficheros, que es
lo que hace comparables el antes y el después.

## 7.1 La autonomía, en una frase

Aegis lee y comprueba lo que quiera sin avisarte. Para **escribir** necesita que
le marques el proyecto en `Ajustes → Proyectos` del móvil, y el interruptor solo
se activa si ese proyecto **tiene verificador declarado**: sin él no hay contra
qué comprobar que el trabajo quedó bien. Y lo que sale de tu disco te lo pregunta
siempre, con el motivo escrito.

```bash
cd bridge
bin/api GET autonomy                      # modo, proyectos marcados, pendientes
bin/api POST autonomy/modo '{"modo":"solo"}'    # solo|permiso|pleno
```

`pleno` **no** significa "sin preguntar": el nivel 3 pregunta en los tres modos.
No existe un modo que dispense de la cola (A-036).

## 7.2 Planes, cierre y lo irreversible

Tres cosas que se decidieron el 2026-10-14 y que cambian cómo encaja un encargo.

### El plan es lo que Aegis está trabajando

`bridge/app/plan.py`. **Solo uno está `en_curso` a la vez** —sin eso, «esto se
replanifica» no tiene sujeto— y cada uno lleva **prioridad** (0-100, el 50 es
neutro a propósito). Un plan nuevo solo desplaza al que corre si es
**estrictamente mayor**.

| | |
|---|---|
| `GET /planes` | la cola, ordenada como se trabaja |
| `GET /planes/en_curso` | el único que está corriendo, o `null` |
| `GET /planes/siguiente` | con qué debería trabajar ahora |
| `POST /planes` | encola; devuelve `desplaza` |
| `POST /planes/{id}/tomar` | pasa a `en_curso` **y suelta el que hubiera** |

El plan desplazado **vuelve a la cola con su prioridad**. Abandonar no es cancelar.

**`cerrar` exige el cierre.** Sin él, `cerrado` sería la palabra del modelo
diciendo que acabó: el falso éxito de A-016 con otro nombre.

### El cierre dice solo lo que importa

`bridge/app/cierre.py` y `GET /cierre/{run_id}`. Cinco apartados: `resultados`,
`cambios_drasticos`, `errores`, `decisiones`, `recomendaciones`.

- **Sale de la traza, nunca del texto del modelo.** Tercera vez que se aplica la
  misma regla, y aquí es donde más importa: el cierre es lo único que se lee
  cuando Aegis trabaja en tu ausencia.
- **Las recomendaciones no las escribe el modelo.** Salen de cinco reglas que
  están a la vista, y como mucho tres por run. Una recomendación que siempre sale
  es ruido.
- **Un run donde no pasó nada no produce informe.** Y lo que está vacío no se
  imprime: cinco títulos vacíos dicen «nada» en 200 caracteres.
- El campo `sostiene` dice de qué dato sale cada apartado, para que el informe sea
  **auditable** y no haya que creerle.

### Lo irreversible, por categoría y no por lista

`bridge/app/autonomy.py::IRREVERSIBLES`. Las cuatro son: **pago**, **despliegue**,
**migracion**, **contacto**. Siempre preguntan, en los tres modos.

**Dos están vacías** — Aegis no tiene forma de pagar ni de escribir a nadie — y
eso es una **propiedad a mantener**, no un hueco: si alguien añade `enviar_correo`,
`tests/test_irreversible.py` falla y obliga a decidir.

Y **escribir código no pregunta**: `aegis_write_file` está en `CON_PERMISO`, que
es la marca por proyecto, no la cola. La diferencia importa porque «con permiso» y
«requiere OK» suenan igual y no son lo mismo: la primera la resolviste una vez,
la segunda pregunta cada vez.

**Lo que se sabe y no está en las cuatro categorías**: `project_create` (escribe
fuera de los proyectos declarados) y `quien_eres_actualiza` (reescribe lo que
Aegis sabe de ti, y eso entra en el prompt de **todos** los runs). Siguen
preguntando, a propósito.

### `procede` ya no es un agujero

Era el **19 % de tus prompts reales** y no casaba con nada. Ahora hay intent, y
distingue el gesto solo del gesto **con requisitos pegados** —que son la mitad de
los reales—: en el segundo caso **reformula el plan en curso** y escribe el
motivo.

Para medir cuánto de lo que pides lo entiende sin modelo:

```bash
cd bridge && bin/medir-cobertura --detalle
```

Lee tus sesiones de `aegis` y **solo** de `aegis`: los otros proyectos no están
en `PROJECTS`, no se abren, y redacta IPs, UUID y claves de la salida.

### El trabajo en vuelo sobrevive al reinicio

`app/recuperacion.py`, y el JSONL de cada run es **append-only**: `task.created`
al arrancar, cada `tool.completed` en cuanto termina su paso, y el terminal al
cerrar.

Al arrancar, el bridge relee `data/logs/runs/autopilot-*.jsonl` y devuelve los
runs al buffer. Los que **no tienen evento terminal** se sellan con
`fin: interrumpido` y cuentan como estado aparte: un corte no es un fallo, y
meterlo en `roto` escondería los pasos que sí se hicieron.

Ningún run restaurado dice `running`. La tarea no existe tras el reinicio, y un
cliente esperando a un `running` que no va a llegar espera para siempre.

> **El reloj de un run no sobrevive.** Se sabe que estaba en marcha y hasta qué
> paso llegó; no se reanuda solo. Relanzar es una decisión, y no se toma sola.

## 8. Proyectos que opera el agente

`PROJECTS` en `bridge/app/projects.py` declara alias → raíz, raíz y verificador de
cada una. No hay una lista en `mcp_ops.py`: la whitelist se deriva en runtime de
ahí y del registro `bridge/registro/*.json`, para que un proyecto nuevo sea un
fichero y no un cambio de código. Cada proyecto necesita las dos cosas y un `bridge/lessons/{alias}.md`.
Un archivo de lecciones que no existe se carga vacío; no es un error.

El repo **solo declara el suyo**:

| Alias | Raíz | `check` | `test` |
|---|---|---|---|
| `aegis` | este repo, derivado de `app/entorno.py` | `bridge/bin/check-imports.py` | `bridge/.venv/bin/python -m unittest discover -s bridge/tests -q` |

Los demás proyectos se dan de alta con `registro/{alias}.json` —ver
`registro/_plantilla.json`—, que es un fichero y no una edición de Python. Antes
había cinco entradas más aquí con rutas concretas; en un clon de otra persona
apuntan a directorios que no existen, y un registro que miente hace creer a Aegis
que puede operar algo que no.

**`aegis_console` es la app, y su puerta es aparte.** Está en `mobile/` y no en
`PROJECTS`, porque no es un proyecto que el agente opere: es el cliente. Pero es
lo más grande de este repo por superficie, y por eso su puerta también es
**completa**:

```bash
export PATH="$HOME/development/flutter/bin:$PATH"
export JAVA_HOME="$HOME/jdk"                      # sin esto, gradle no arranca
cd mobile
flutter analyze && flutter test                  # 0 issues / verde: ambos exactos
flutter test integration_test/                   # contra el Keystore del emulador
flutter build apk --debug --dart-define=API_HOST=10.0.2.2
```

- **La base es 0 issues de `flutter analyze` y verde.** Se midió antes de
  empezar (2026-10-07) y el criterio de éxito es «cero nuevos», no «no más de
  N».
- **`flutter test integration_test/` no es opcional.** Hay cosas que no existen
  en el host: `flutter_secure_storage` habla con el Keystore de Android, y un
  doble en memoria daría verde sobre lo único que hay que demostrar. Empieza el
  emulador antes (§5).
- **`flutter analyze` sobre `test/` y `integration_test/` también.** Los tests
  son código y pagan el mismo coste de análisis que el resto.
- **Si la app dice «el APK no corresponde al código de ahora»** (un 409 en
  `GET /apk/telefono`), no es que el APK sea viejo: es que el sello no cuadra
  con la firma. Se comprueba sin adb con
  `PYTHONPATH=. bridge/.venv/bin/python -c "from pathlib import Path; from app.deploy import apk_desactualizado; print(apk_desactualizado(Path('mobile/build/app/outputs/flutter-apk/app-release-telefono.apk')))"`
  — y la respuesta vacía es la buena. El motivo de fondo está en A-112.

**Mide la base de cada proyecto antes de delegar en él.** Para `aegis_console`
es **0 issues de `flutter analyze`** y verde, y el criterio de éxito es «cero
nuevos».

Para cualquier otro proyecto que llegue con tests rojos, el criterio de éxito no
puede ser «analyze limpio»: es «no más de N issues nuevos», y hay que sacar la
cuenta exacta **antes** de empezar. Y hay que sacarla en la máquina donde se va a
medir: una base tomada de otro sitio es peor que no tenerla, porque el «antes» y
el «después» no son comparables.

## 9. Proyectos que no son este repo

Este repo no declara los proyectos que Aegis opera: van en
`registro/{alias}.json`, y sus reglas son las suyas, no las de aquí. El patrón es
siempre el mismo, y aplica a cualquiera:

- El proyecto tiene su propio `AGENTS.md` o documentación, y **manda sobre este
  fichero** para todo lo que toque a ese proyecto.
- Se mide su base antes de delegar en él (ver §8).
- **Producción no se toca sin que lo pidas explícitamente.** El desarrollo va
  contra la rama de desarrollo; la de producción solo aparece en un despliegue.
- Sus connection strings no están aquí. Se piden en el momento de usarlas.

Ese patrón es lo único que Aegis impone a un proyecto ajeno, y no es poco: es la
diferencia entre un asistente que puede tocar tu base de datos y uno que no.

## 10. Lo que no se versiona, y por qué

Desde que el repo es público, la regla no es solo «no metas secretos»: es que
hay cosas de la persona que lo usa que **no son del proyecto**, y por eso no
viajan:

| Qué | Por qué |
|---|---|
| `bridge/quien-eres.md` | Cómo quieres que te hable. Es tuyo; la plantilla sí está (`quien-eres.ejemplo.md`) y `infra/setup.sh` la copia. |
| `bridge/fichas/{alias}.md` | Ficha técnica de tus proyectos: es información de tu negocio. Las plantillas y la de `aegis` sí viajan. |
| `bridge/registro/*.json` | Los mismos proyectos por su nombre real. `_plantilla.json` sí viaja. |
| `bridge/lessons/{alias}.md` | Lecciones de proyectos que no son este repo. `aegis.md` sí viaja. |
| `bridge/fichas-privadas/` | La parte comercial: quién es el cliente y qué se le cobran. |
| `bridge/.env`, `bridge/data/` | Secretos, logs, memoria y SQLite. |

**El `.gitignore` es parte del diseño, no un convenience.** Es bidireccional: lo
que hay dentro no se cuela, y lo que tiene que viajar (`aegis.md`,
`_plantilla.json`) sigue versionado. Un `.gitignore` demasiado ancho se come
código sin avisar —lección A-017— y uno demasiado estrecho manda tu `.env` a
internet. Hay un job de CI que falla si alguien hace `git add -f` de lo primero,
justamente porque la regla escrita sola no se aplica sola.

Si añades un fichero nuevo y no sabes en qué columna va, la respuesta por defecto
es que **no se versiona** y se pregunta.

