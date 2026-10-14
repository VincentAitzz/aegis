# Runbook

Guía de operación del backend Aegis (post-reinicio), pruebas y resolución de
problemas.

## Sobre esta guía

Está escrita para **Linux con `systemd`** y verificada en una máquina con CachyOS
(Arch), sin sudo automático. Donde el comando no sea el de tu distribución, lo
importante es **qué comprueba cada script**, no el nombre del gestor de servicios:
`infra/stack.sh` es el sitio donde se ajusta.

Las direcciones IP y los seriales que aparecen son **de ejemplo**. Las tuyas las
sabes con `tailscale ip -4`, `ip -4 addr` y `adb devices -l`.

## 1. Arranque tras un reinicio

Ollama y el gateway de Hermes **no** son servicios de sistema (Tailscale sí usa
`systemd` y arranca solo). Aun así, no hay que levantarlos a mano: hay un script
que los levanta, espera su salud real y los apaga comprobando que mueren.

```bash
bash infra/stack.sh arrancar     # Ollama :11434, gateway :8642, bridge :8000
bash infra/stack.sh estado       # salud de los tres + qué puede escribir Aegis
bash infra/stack.sh parar        # los tres, verificado
```

`estado` es la pregunta que importa antes de delegarle algo a Aegis:

```
== Aegis ==
  ollama   :11434  ok   pid 64941   6 modelos
  gateway  :8642   ok   pid 65227   hermes 0.21.4
  bridge   :8000   ok   pid 65403   worker
  autonomy: solo · escribiendo: aegis
```

La cuarta línea dice si hay un modo y un proyecto marcados; sin ella, un
`project` nuevo en alta y sin verificador falla en la primera escritura sin
explicación.

Lo que hace el script por dentro, si algún día hay que hacerlo a mano:

```bash
# 1) Ollama con contexto 64k (imprescindible para Hermes)
env OLLAMA_HOST=127.0.0.1 OLLAMA_CONTEXT_LENGTH=64000 ~/.local/bin/ollama serve \
  > ~/.local/ollama.log 2>&1 &
# alternativa: ./infra/ollama/start-ollama.sh

# 2) Gateway/API server de Hermes
setsid nohup ~/.local/bin/hermes gateway run > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &

# 3) Bridge Aegis
cd bridge                                # o donde clonaste el repo
( env BRIDGE_BIND=0.0.0.0 BRIDGE_PORT=8000 PYTHONPATH=app \
    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > ~/.local/bridge.log 2>&1 & )

# 4) Devolución de bueno
curl -s http://127.0.0.1:8000/health   # espera status ok + agents [worker]
```

Dos avisos que el script se encarga de evitar y que al hacerlo a mano muerden:

- **El gateway drena ~30 s.** Arrancar el nuevo antes de que muera el anterior
  hace que el nuevo muere con `A gateway already owns this host`.
- **Apagar no es `pkill`.** `pkill -f 'ollama serve'` se comprobó que **no mata
  nada**, y además quedan hijos vivos (el `llama-server` de un modelo cargado
  sobrevive al `ollama serve`). El script mata por PID, al grupo de proceso, y
  comprueba que el puerto quedó libre antes de decir que paró.

Logs (los del script; los manuales, en el bloque de arriba, van a otros sitios):

| Servicio | Log                                   |
|----------|---------------------------------------|
| Ollama   | `~/.local/log/aegis/ollama.log`       |
| Hermes   | `~/.local/log/aegis/gateway.log`      |
| Bridge   | `~/.local/log/aegis/bridge.log`       |
| Bridge (JSON) | `bridge/data/logs/bridge.jsonl`  |
| Bridge (por run) | `bridge/data/logs/runs/<run_id>.jsonl` |

### 1.1 Trazabilidad desde la terminal

Todo lo que Aegis hace queda escrito, y se lee sin la app. Sirve igual para un
run lanzado desde el móvil que para uno lanzado por curl: el run no sabe de
dónde vino.

```bash
# En vivo: todo lo que va haciendo el bridge, a una línea por evento
tail -f bridge/data/logs/bridge.jsonl

# Solo los runs, legibles
jq -r 'select(.event=="tool.completed") | "\(.payload.tool) ok=\(.payload.ok) paso=\(.payload.step)"' \
    bridge/data/logs/runs/<run_id>.jsonl

# La lista de runs, con qué herramienta usaron y cómo acabaron
cd bridge
bin/api GET runs | jq '.runs[] | {run_id, proyecto, estado, pasos, herramientas, error}'

# Un run entero, con su respuesta y por qué terminó
bin/api GET runs/<run_id> | jq '.run'
bin/api GET runs/<run_id> \
    | jq '.eventos[] | select(.event=="task.done") | .payload'

# Qué está haciendo ahora mismo (lo que ve la cabecera del móvil)
curl -s localhost:8000/actividad | jq
```

El JSONL por run es la traza real: un evento por tool llamada, con su resultado y
su `ok`. `ok: false` con el motivo es lo que hay que leer antes de creer que un
run salió bien; y el `fin` dice por qué terminó, no solo si terminó.

**El vocabulario de `fin`**, que es cerrado y comprobable:

| `fin` | Lo que pasó | ¿Te toca hacer algo? |
|---|---|---|
| `sin_tools` | el modelo respondió y no pidió ninguna tool | no, salvo que esperabas que trabajara |
| `respuesta_vacia` | el modelo devolvió vacío y se agotaron los reintentos | mirar el prompt |
| `max_steps` | se acabaron los pasos | normalmente no |
| `esperando_ok` | Aegis necesita tu permiso | **sí**: aprobar o denegar |
| `parado` | paraste el run tú | no |
| `verificador_rojo` | el verificador reprueba el avance, o ya estaba rojo | sí, antes de seguir |
| `llamada_repetida` | la misma llamada falló dos veces con esos argumentos | sí: cambia el enfoque |
| `modelo_caido` | Ollama no respondió | mirar `infra/stack.sh estado` |
| `reventado` | error del propio bridge | mirar el log; el run dejó rastro igualmente |

En el JSONL, `task.done` es un run que terminó su trabajo; `task.stopped`, uno
que espera a alguien; `task.failed`, uno que **no** pudo seguir (incluidos
`modelo_caido`, `reventado`, `verificador_rojo` y `llamada_repetida`). Un
`task.done` con `fin: reventado` sería un bug del bridge: no debería ocurrir.

Para ver un run mientras crece —en vez de a posteriori— se lanza con
`POST /autopilot/start` y se lee `GET /autopilot/<run_id>` (ver §4.2).

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
# CAPA 3 — Memoria episódica (vectorial)
bridge/.venv/bin/pip install -r requirements.txt   # instala chromadb; mcp<2 por la API FastMCP
ollama pull nomic-embed-text                        # modelo de embeddings local

# FASE 2 (opcional) — consulta de memoria por el agente vía MCP
bridge/.venv/bin/pip install 'mcp>=1.0,<2'
```

> **Sin Docker.** El aislamiento por contenedor se retiró el 2026-09-30. Arrancaba
> un contenedor `aegis-sandbox` en cada run al que el agente no tenía acceso
> (`terminal` nunca estuvo habilitada en `api_server`) y cuyo `/workspace` era un
> directorio vacío. `terminal.backend` es `local`: las tools de `aegis-ops` corren
> en el host, protegidas por la whitelist y los guardarraíiles de escritura de
> `bridge/app/mcp_ops.py`. El gateway **no necesita** el grupo `docker`.

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

## 4. App: emulador primero, teléfono con puerta

### 4.0 El emulador (donde se prueba de verdad)

```bash
bash infra/mobile/emulador.sh arrancar     # AVD aegis-a17
bash infra/mobile/emulador.sh estado      # android / resolución / dpi
bash infra/mobile/emulador.sh parar
```

Android 16 (API 36), 1080x2340, 450 dpi: misma versión y geometría que el
galaxy a17 real. **La ABI no se replica** — el teléfono es arm64-v8a y esta
máquina es x86_64 — así que el emulador sirve para UI, red y lógica, no para
medir rendimiento.

```bash
build_apk(target='emulador')     # -> app-debug-emulador.apk   (API_HOST=localhost)
install_apk(target='emulador')   # instala y abre aquí sin preguntar nada
deploy_smoke()                   # arranca y comprueba que la app HABLA con el bridge
```

> Un APK por destino, y el destino va en el nombre. Con un único
> `app-debug.apk` compilar para el teléfono deja el emulador con una app que no
> ve nada, y es un fallo silencioso (A-022).

### 4.1 Tu teléfono (con permiso)

```bash
install_apk(target='telefono')   # analyze + tests + humo en emulador
#   -> sin tu aprobación: NO instala, te avisa y devuelve el id de petición
#   -> apruebas en el móvil (o por POST /aprobaciones/{id}), y se ejecuta con
#      POST /aprobaciones/{id}/ejecutar, que corre la llamada aprobada tal cual
```

### 4.1.1 Por USB, o sin Tailscale en el teléfono

Aegis reconoce un teléfono de tres formas: el nombre que publica por mDNS, un
`adb connect ip:puerto`, o el serial que declaras tú. **No lo adivina**, porque
«el único aparato que no es el emulador» no es una identificación: es una
suposición, y su consecuencia es instalar una app de prueba en un aparato real.

Por USB el serial es de hardware (`SERIAL1234567`) y no parece nada de lo anterior:

```bash
adb devices -l | grep -o '^[A-Z0-9]*' | head -1        # el serial
echo 'AEGIS_PHONE_SERIAL=SERIAL1234567' >> bridge/.env
bash infra/stack.sh reiniciar bridge                     # sin esto no se lee
adb_devices()                                            # debe decir TELEFONO
```

Y sin Tailscale en el teléfono, el APK del teléfono se compila contra la IP de
la LAN (`adb_devices` lo dice si el teléfono no llega por la tailnet):

```bash
ip -4 addr | grep wlan0                                  # la IP del portátil
echo 'AEGIS_BRIDGE_TAILNET_IP=192.168.0.50' >> bridge/.env
```

La puerta comprueba que el teléfono llegue **antes** de instalar. Con `ufw` activo
el puerto no está abierto por defecto, y sin esto la puerta dice «el teléfono NO
llega» con el teléfono enchufado al lado:

```bash
sudo ufw allow from SUBNET_LOCAL/24 to any port 8000 proto tcp
```

- Instalación y **lanzar** son pasos separados. Por defecto solo se instala.
- La aprobación es de **un solo uso** y la gasta la propia tool: el agente nunca
  ve el token.
- **Un aviso en el móvil, y solo uno**: lo publica la propia app con su icono y
  su canal, y lleva la cuenta de pendientes —tocas y se abre el cuadro de
  decisión, sin sacar la app de la que estés usando. El puente lo verifica contra
  `dumpsys` y, si no llega, **lo dice** con el motivo en vez de suponer.
  `AEGIS_AVISO_INTERMEDIO=emulador` lo manda al emulador, `=ninguno` lo apaga.
  No es FCM: requiere adb conectado (A-020, A-021, A-029, A-042).
- **Aprobar instala solo**: el token de un solo uso lo gasta el bridge dentro de
  `POST /deploys/{id}/instalar`. Si no hay teléfono por adb, la puerta se cierra y
  sale un aviso de fallo —no se finge que se instaló (A-045).
- **Si no llegan los avisos**, mira el permiso del sistema: las notificaciones de
  Aegis pueden estar apagadas, y sin `POST_NOTIFICATIONS` no hay nada que hacer.
  La app enseña un aviso en pantalla solo cuando hay algo pendiente, y lo
  desaparecer en cuanto lo concedes es la señal de que ya está.
- **La primera instalación no pide aprobación**, porque el botón para aprobar está
  dentro de la app que aún no está. Aun así exige la puerta completa y nunca abre
  la app (A-023).
- La app del teléfono necesita la IP de la tailnet **del bridge**, que se pide a
  `tailscale ip -4`. Si no hay tailnet, `AEGIS_BRIDGE_TAILNET_IP=<ip>`; y si no se
  puede averiguar, no se compila antes que compilar con una dirección inventada.

Depuración inalámbrica (los puertos giran en cada reinicio):

```bash
adb mdns services                       # puerto actual mDNS
adb connect 192.168.0.5:<puerto>
adb -s <serial> shell am start -n com.aegis.aegis_console/.MainActivity
```

- Las tools de `aegis-ops` resuelven el dispositivo solas: `adb_connect()` usa
  mDNS + la IP de la tailnet. Funcionan con o sin Tailscale (misma Wi-Fi).

## 4.1.2. Actualizar la app desde la propia app

Hay dos caminos y se confunden mucho:

| Camino | Quién decide | Cuándo |
|---|---|---|
| `install_apk(target=…)` | Aegis, con tu OK | una **release** que hay que poner en el móvil |
| Ajustes → «Actualizar Aegis» en la app | tú, en Android | una **build** que ya está en el bridge |

El segundo es el del día a día:

1. `HEAD /apk/telefono` — tres cabeceras, no 50 MB.
2. Si el número es mayor que el instalado, ofrece **Bajar la nueva**.
3. Si falta el permiso de «instalar apps desconocidas», ofrece llevar a Ajustes y
   **vuelve a preguntar solo** cuando la app pasa a primer plano.
4. Descarga a `Android/data/<paquete>/files/apk/`, lo único que el `FileProvider`
   puede leer sin permisos extra.
5. Pasa el fichero al instalador del sistema con un `content://`. **Tú confirmas.**

Lo que Aegis **no** puede hacer, y no hay diseño que lo arregle: responder al
diálogo de Android. Por eso el diálogo dice «te toca confirmar», nunca
«instalado».

```bash
# El bridge tiene que servir un APK AL DÍA. Si el código cambió después de
# compilarlo devuelve 409 y no sirve nada — a propósito: un APK viejo
# instalado como si fuera nuevo deja la app peor que estaba.
cd bridge && bin/api GET apk/telefono   # 200 + x-aegis-version, o 409 + x-aegis-motivo
```

> El motivo del `409` viaja en la **cabecera** porque la app pregunta con un
> `HEAD`, y un `HEAD` no tiene cuerpo. Va **sin acentos**: las cabeceras viajan en
> latin-1 y un `código` dentro revienta la respuesta con `UnicodeDecodeError`. El
> original con acentos sigue en el `detail`, que sí los admite.

Para probar el ciclo entero hacen falta **dos** builds: una que se instala a mano
con `adb` y otra más nueva que se sirve. Con una sola, la app ve que ya tiene la
última y no hay nada que probar.

## 4.2. Agente autónomo (`/autopilot`)

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
cd bridge
bin/api POST autopilot '{
  "prompt": "pon el tono en verde, compila e instala en el teléfono",
  "max_steps": 12
}'
# -> {"answer": "...", "steps": N, "trace": [{"tool": "...", "arguments": {...}, "ok": true}]}
```

`bin/api` pone la cabecera `X-Aegis-Token` que **toda ruta que cambia algo pide
desde 2026-10-04**. Sin ella, `/autopilot` y `/autopilot/start` devuelven 401.

Garantías de `aegis-ops` (sin importar quién la llame):

- **Whitelist**: solo 8 tools del repo; cualquier otro nombre se rechaza.
- **Rutas**: solo dentro del repo; veta `.git/`, `.env*` y binarios.
- **Secretos**: se niega a escribir contenido que parezca una clave (redactada).
- **Rollback**: si un `.dart` deja de parsear tras editar, se revierte y se le
  devuelve el contenido actual al modelo para que reintente.
- **Trazabilidad**: cada paso queda en `trace[]` con argumentos y resultado.

### 4.3 Aprobaciones: qué te está preguntando

```bash
cd bridge
bin/api GET aprobaciones | jq
# {"pendientes": [...], "aprobadas": [...]}

# aprobar (devuelve el token de un solo uso)
bin/api POST aprobaciones/<id> '{"decision":"aprobar"}' | jq -r .token

# ejecutar lo aprobado, con sus argumentos, sin modelo en medio
bin/api POST aprobaciones/<id>/ejecutar | jq '{ok, tool, error}'

# denegar con motivo: el motivo se le inyecta al siguiente run
bin/api POST aprobaciones/<id>/motivo \
  '{"contenido":"ahora no, esta base todavía no"}' | jq -r .motivo
```

**Ejecutar o relanzar**: aprobar no es aprobar un run, es aprobar **una llamada con
unos argumentos**. Ejecutar corre esa llamada tal cual (de un solo uso, solo
tools de nivel 3, con sus guardarraíles y con rastro en
`data/logs/runs/aprobacion-<id>.jsonl`); relanzar repite el run con el token y
sirve para que Aegis **continúe** después de esa llamada. En el móvil son los dos
botones de la tarjeta.

### 4.4 Las lecciones ya no van al prompt

`lessons/{alias}.md` es el registro de por qué el código es como es, y **no se
borra**. Lo que cambió el 2026-10-14 es que dejó de ser input del modelo.

| | antes | después |
|---|---|---|
| system prompt | 17 155 chars | **7 953** |
| de los cuales, lecciones | 9 200 (54 %) | 0 |
| tools en el schema | 22 | 21 |

Por qué, medido:

| motivo | evidencia |
|---|---|
| No cambiaba el comportamiento | A-014 («no repitas la llamada idéntica que ya falló dos veces») se repitió **3 de 3 con las lecciones inyectadas y 3 de 3 sin ellas** |
| La puerta no se usó nunca | La tool `lecciones` tiene **0 llamadas** en los 857 run logs de `bridge/data/logs/runs/` |
| El índice estaba truncado | Con el tope de 8 000 chars listaba A-001…A-078 de 121: se pagaba el 100 % para enseñar el 65 % |
| Y era caro | Con las 120 KB enteras: 60,2 s por llamada. Con el índice: 11,9 s. Sin nada: 10,1 s |

**Para leer una lección, ábrela con un editor.** Para volver a mirar el número:
`bin/medir-prompt.py`.


### 4.5 Fases de trabajo

Un enfoque son las instrucciones que solo valen mientras se piensa. Cada uno es un
fichero en `bridge/enfoques/` con su entrada en `_indice.json`, y solo se inyecta
en el prompt de los runs que lo piden:

```bash
cd bridge
bin/api GET enfoques          # ["arquitectura"]

bin/api POST autopilot/start '{
  "project": "acme", "enfoque": "arquitectura", "max_steps": 10,
  "prompt": "requisitos no funcionales y tres opciones de almacenamiento, con coste de cambio"
}'
```

En el móvil es el selector de fases que aparece bajo el motor: al elegir una, el
texto explica para qué sirve, porque una fase cambia lo que Aegis se permite
hacer.

Por qué van aparte de `metodo.md`: A-016 midió que el 7B deja de emitir
`tool_calls` cuando el prompt crece. Una fase inyectada a todos los runs se
paga en los de operación, que son los que más necesitan llamar tools. Si
`probe-toolcall.sh` dice que ya no hay tool_calls, lo primero que se mira es el
tamaño del prompt.

## 5. Pruebas

Unitarias (capa observabilidad + memoria + autopilot; corren SIN chromadb — degradan):

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

# El verificador DECLARADO, que es lo que ejecuta Aegis. Si esto sale rojo, el
# criterio de éxito de cualquier trabajo en este repo no significa nada: el rojo
# no es «sin verificar», es «verificado y rojo». Desde 2026-10-04 lo estaba, por un
# PYTHONPATH que faltaba (A-084).
cd bridge && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from app.verifier import ejecutar
for what in ('check', 'test'):
    v = ejecutar('aegis', what)
    print(what, 'OK' if v.ok else 'FALLO')"


# ciclo real contra Ollama (el modelo decide y ejecuta de verdad)
cd bridge && AEGIS_SLOW_TESTS=1 .venv/bin/python -m unittest tests.test_autopilot -v

# sonda de capacidad de tool-calling del modelo
cd bridge && bash bin/probe-toolcall.sh qwen2.5:7b
```

Funcionales (host):

```bash
# Un run de verdad, y su veredicto
cd bridge
RID=$(bin/api POST autopilot/start '{"project":"aegis","prompt":"lista los proyectos"}' | jq -r .run_id)
bin/api GET autopilot/$RID | jq '{status, steps, fin, estado, duracion_s}'

# Contrato de control del run en marcha
bin/api POST autopilot/$RID/steer '{"text":"ahora resume"}'
bin/api POST autopilot/$RID/stop
```

> `tests/e2e_ws.py` y las rutas `POST /tasks*` se quitaron en la Fase 1 con el
> motor de Hermes y el WebSocket. `GET /autopilot/{run_id}` hace lo que hacía el
> `subscribe` con replay: la traza crece paso a paso y sobrevive a reiniciar el
> bridge, porque se escribe en `data/logs/runs/<run_id>.jsonl`.

Y el reparto de estados del histórico, que es la línea base de cualquier cambio
en el bucle:

```bash
cd bridge && .venv/bin/python bin/medir-runs
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
| Un run devuelve `fin: incompleto`    | paró sin responder o sin ninguna tool en verde. El `resumen` dice cuál; `bin/medir-runs` compara contra la línea base |
| `estado: roto` en un run largo        | `fin: modelo_caido` o `reventado`: el modelo no respondió, o el bridge reventó. El `error` va en su propio campo |
| Un verificador rojo deja el bridge colgado | ya no: `verifier.gate` corre el comando en un hilo. Si vuelve a pasar, `tests/test_verificador_no_bloquea.py` lo detecta |
| La app no conecta                     | verifica MagicDNS `aegis.tailXXXXXX.ts.net` e IP 100.x, y que `GET /health` responde (va sin token) |
| La app se queda en «buscando proyectos…» | el `GET /health` sale en el log del bridge con `200`: si llega y vuelve, el cuelgue está en el cliente. Un interceptor sin `handler.next()` cuelga sin error (A-104) |
| El diálogo se queda en «preguntando»     | un `await` sin `catch` deja el estado a medias; con excepción se queda en «cargando» para siempre (A-105) |
| «el bridge no tiene un APK que servir»   | mira el **status** del `HEAD`: si es `401`/`403` el token no viaja o caducó, y el arreglo está en la app, no en el bridge (A-105b) |
| El 409 no muestra el motivo              | el motivo va en `x-aegis-motivo`, y **sin acentos**: las cabeceras viajan en latin-1 y un `código` dentro revienta la respuesta |
| «Ir al permiso en Ajustes» no hace nada  | el dispositivo no tiene ninguna activity que lo maneje. Debe decirlo, no fallar en silencio: los intents se prueban, no se consultan (A-106) |
| «Listo para instalar» sin nada que instalar | la frase se elegía por el permiso y no por si hay versión nueva (A-107) |
| `build_apk(telefono)` apunta a una dirección muerta | `AEGIS_BRIDGE_TAILNET_IP` en `bridge/.env`: si está, **tiene que ser una de las que da `ip -4 addr`** — una caducada se descarta sola y cae a `tailscale ip -4` (A-108). Ahora está sin declarar a propósito |
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
    command: "/RUTA/ABSOLUTA/AL/REPO/bridge/bin/mcp-memory.sh"   # absoluta: mcpd no
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
**al arrancar**: reinícialo después de registrar el servidor.

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
