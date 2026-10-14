# Aegis

Español · [English](README.en.md)

Un asistente que vive en tu propia máquina. Oye lo que le dices, ejecuta sobre tus
herramientas, recuerda lo que importa de ti y te avisa de los problemas que
encuentra — sin nube, sin cuenta, y sin una sola petición a un tercero.

```
┌──────────────┐   REST    ┌─────────────────┐   HTTP    ┌──────────┐
│  App Flutter │ ────────► │  Bridge FastAPI │ ────────► │  Ollama  │
│  (Android)   │ ◄──────── │     :8000       │ ◄──────── │  :11434  │
└──────────────┘  stream  │  /chat   T0→T1   │  stream  │ llama3.2 │
                          │  /autopilot   T2 │          └──────────┘
                          │  memoria · tools │
                          └─────────────────┘
                                ▲
                    systemd --user: se levanta solo
```

## Qué es y qué no es

**Es** un agente local que ejecuta de verdad: llama a sus propias herramientas,
opera tus repositorios, compila tu app y te deja ver cada paso. Lo que hace queda
en `bridge/data/logs/runs/<run_id>.jsonl`, paso a paso.

**No es** un chat con un modelo. Un chat te devuelve texto; Aegis te devuelve lo
que pasó, con la traza al lado, y el veredicto se calcula **desde la traza**, no
desde lo que dice el modelo.

Tampoco es un servicio: son tres procesos que levantas tú, en tu máquina, y que
se apagan contigo.

## Qué lo hace distinto

### El veredicto sale de la traza

Es el invariante central, y se puso por un fallo concreto. El bucle marcaba
`success` a cualquier `task.done` sin mirar qué se había ejecutado; esos episodios
falsos entraban en memoria; el `recall` los reinyectaba como *«Episodios similares
resueltos antes»*; y el modelo aprendía que la respuesta era «OK» y contestaba
**sin llamar a nada**.

Medido, con ablación intercalada (n=8):

| Memoria | Tool-calling |
|---|---|
| Con 3 episodios falsos | **0/8** |
| Sin el bloque de memoria | **7/8** |

Tres episodios falsos bastan. Por eso al prompt solo suben episodios `success`
**con tools nombradas**, y por eso `app/veredicto.py` es el único que dice cómo
terminó un run.

### Dos motores serían dos sitios donde vive un guardarraíl

El repo tuvo un motor de conversación además del autopilot. Se borró entero: no
le quedaban llamadores, y `docs/architecture.md` seguía documentándolo como API
viva en quince sitios. Un invariante que depende de un componente que ya no se
usa no es un invariante; es una intención.

### El prompt es el presupuesto

Medido en la máquina de referencia: con 35 835 caracteres un run tardaba 49,1 s; con
22 847, 18,5 s. Un 36 % menos de prompt, un 62 % menos de tiempo.

El caso más claro está en las lecciones. Ocupaban **9 200 de los 17 155 caracteres**
del prompt —el 54 %—, su índice estaba truncado sin decir nada, y la tool para
pedirlas tenía **0 llamadas en 857 runs registrados**. No cambiaban el
comportamiento que describían. El prompt hoy pesa **7 953**.

Regla: **cada bloque que entra en el prompt tiene que justificar su coste con una
medición, y si la medición dice que no hace nada, sale.**

Todas las cifras de este README, con su comparativa y su n, están en
**[`docs/medidas.md`](docs/medidas.md)**. Para medir de nuevo:
`bin/medir-prompt.py` (de qué está hecho el prompt) y
`bin/lab/medir-prompt-ab.py` (un A/B de dos prompts, alternando).

### Nada irreversible por su cuenta

Tres niveles de autonomía. Aegis lee y comprueba lo que quiera sin avisarte. Para
**escribir** necesita que le marques el proyecto —y solo se activa si ese proyecto
tiene verificador declarado, porque sin él no hay contra qué comprobar que el
trabajo quedó bien—. Y lo que sale de tu disco te lo pregunta siempre, con el
motivo escrito.

Los niveles 3 (migrar una base, instalar un APK, crear un proyecto) preguntan en
**los tres modos**. No existe un modo que dispense de la cola.

## Empezar

Necesitas Linux, Python ≥ 3.12 y un modelo local. Para la app móvil, Flutter, un
JDK y el SDK de Android — el bridge funciona sin ninguno de los tres.

```bash
git clone https://github.com/VincentAitzz/aegis.git && cd aegis
bash infra/setup.sh                 # venv + .env + comprobaciones
```

**Y para que no haya que acordarse después de un reinicio**, la instalación como
servicio de usuario (arranca al iniciar sesión, muere al cerrarla, no pide sudo):

```bash
bash infra/systemd/instalar.sh      # tres units + un timer de vigilancia
journalctl --user -u aegis-bridge -f
```

`infra/stack.sh` sigue ahí y funciona en todas partes: las unidades no existen en
macOS, y no son la única forma de encender Aegis, sino la de que no tengas que
acordarte.

Ollama con 64 000 de contexto y el modelo:

```bash
bash infra/ollama/start-ollama.sh
ollama pull qwen2.5-coder:7b       # ~4,7 GB
ollama pull nomic-embed-text       # embeddings de la memoria, ~274 MB
ollama pull llama3.2:3b            # T1, el del camino rápido
```

Levantar el bridge:

```bash
bash infra/stack.sh arrancar
bash infra/stack.sh estado         # salud de los tres + qué puede escribir Aegis
```

Y hablar con él:

```bash
cd bridge
bin/api GET health
bin/api POST autopilot '{"project":"aegis","prompt":"lista los proyectos y su verificador"}'
```

### Las dos formas de hablar

Hay dos, y la diferencia no es de estilo: una **conversa** y la otra **trabaja**.

| | `POST /chat` | `POST /autopilot` |
|---|---|---|
| Modelo | el 3B | el 7B |
| Schema de 21 tools | **no** | sí |
| Qué contesta | conversación | trabajo con traza |
| Turno corto | **0,17 – 0,8 s** | 23 – 40 s |
| Herramientas | ninguna | todas, con su puerta |

`/chat` **no lleva el schema a propósito**, y está medido: con el schema delante,
el modelo llama a una herramienta aunque no haga falta. Un «hola, ¿qué tal?»
produce una llamada a `quien_eres_actualiza`. **El modelo no sabe cuándo no usar
una herramienta**, y una tool llamada sin querer no es inocua: se ejecuta, o
peor, se pide permiso por algo que nadie pidió.

Los tres destinos de un turno:

```
texto → T0  intents  → 0,01 s, sin modelo
     → T1  el 3B, sin schema  → 0,17 s, conversación
     → T2  solo si T1 se calla → trabajo de verdad
```

La escalada no se la deja al modelo: escala **por silencio**, que es observable.
Un sistema que decide por su cuenta que lo que oyó fue una orden es el fallo que
ya se midió cuando Aegis pidió crear un proyecto que nadie le había pedido.

### La app móvil (opcional)

```bash
bash infra/mobile/emulador.sh arrancar     # AVD que replica un Android de 1080x2340
cd mobile && flutter build apk --debug --dart-define=API_HOST=10.0.2.2
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

El emulador es el destino por defecto a propósito: el teléfono real solo se toca
cuando alguien lo pide **explícitamente** y con la puerta de despliegue en verde.
Escribir en el teléfono de alguien, sin avisar, también está roto.

Para hablar con el bridge desde fuera de tu máquina hay `docs/runbook.md` §3
(Tailscale).

## Hardware

Todo esto está pensado alrededor de **una GPU de 6 GB**. Los números medidos, lo
que cabe y lo que no, están en **[`docs/hardware.md`](docs/hardware.md)**.

En corto: con 6 GB de VRAM y 16 GB de RAM, `qwen2.5-coder:7b` a 64 000 de
contexto. Un 14b a 64k **no entra**: 9 GB de pesos más 12 GB de KV contra 6 GB de
tarjeta.

## Cómo está montado

| Capa | Qué hace |
|---|---|
| **Autopilot** | El único motor. Bucle modelo → tool → observación → modelo. Ejecuta. |
| **Guardarraíles** | `bridge/app/mcp_ops.py`. Whitelist, denylist, escaneo de secretos, rollback de sintaxis. |
| **Veredicto** | `bridge/app/veredicto.py`. Decide cómo terminó el run, desde la traza. |
| **Memoria** | Episódica (Chroma) + grafo conceptual (SQLite). Degrada sola si falta Chroma. |
| **Autonomía** | `bridge/app/autonomy.py`. Los tres niveles y la cola de aprobación. |
| **App** | Flutter. Lista proyectos, aprobaciones, trazas y la bóveda TOTP. |

## Lo que hay que saber de un modelo pequeño

Los modelos de 6-7 GB disponibles **no emiten `tool_calls` fiables**: escriben el
JSON de la llamada dentro del texto. Eso es lo que hace que exista el autopilot,
y no un detalle de implementación.

El resto son consecuencias medidas de lo mismo:

- Cambiar de modelo **no es la palanca**; recortar el prompt sí.
- `qwen3:4b` era la suposición y era falsa: 212 s contra 16,8 s de `llama3.2:3b`.
  Menos parámetros, peor latencia, porque es un modelo de *thinking* y genera el
  razonamiento antes de responder.
- Un escalar envuelto en objeto (`repo: {"type": "aegis"}`) lo repara
  `coerce_args`. Es la malformación típica y antes tumbaba el run.

## Verificar que funciona

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -q   # ~700 tests
cd bridge && .venv/bin/python bin/check-imports.py               # 28 módulos
cd mobile && flutter analyze && flutter test                     # 0 issues, verde
```

Los tres se ejecutan en CI. La suite del bridge pasa **sin Flutter, sin JDK y sin
SDK de Android**: es comprobación de que el repo no depende de la máquina de
nadie, y por eso está en el CI y no solo aquí.

## Contribuir

Lee [`CONTRIBUTING.md`](CONTRIBUTING.md). Lo corto: los dos comandos de arriba en
verde, y **una lección escrita por cada corrección**.

Las 121 lecciones de `bridge/lessons/aegis.md` son la parte más útil del repo.
Antes de tocar algo, mira si ya se rompió una vez.

## Documentación

| | |
|---|---|
| [`docs/hardware.md`](docs/hardware.md) | Números medidos: qué cabe en qué GPU |
| [`docs/vision.md`](docs/vision.md) | Qué quiere ser y hacia dónde va |
| [`docs/architecture.md`](docs/architecture.md) | Diseño, contrato y por qué de cada decisión |
| [`docs/runbook.md`](docs/runbook.md) | Operación, diagnóstico y resolución de problemas |
| [`docs/decisiones/`](docs/decisiones/) | ADRs. La autoridad de cada decisión |
| [`AGENTS.md`](AGENTS.md) | Cómo trabaja el supervisor de este repo |

## Licencia

AGPL-3.0. Ver [`LICENSE`](LICENSE) y el [porqué en `NOTICE.md`](NOTICE.md).

Si te sirve y alguien se sirve de él, cuéntamelo en una issue. Si no te sirve, también: saber
eso también ayuda.