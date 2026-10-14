# Motores: una flota con presupuestos de latencia

> Especificación. Define **qué** se va a construir y **con qué criterio se acepta**.
> Las cifras de este documento son objetivos, y algunas son hipótesis: ninguna
> puerta se cruza con números heredados, todas con números medidos aquí.
> Lo que hoy está en el repo (60,2 s vs 11,9 s, 452 issues, 11,8 s/paso) es
> **hipótesis**, no línea base.

## 1. El problema que ataca esto

Hay tres hechos medidos en el código que no dependen del modelo:

1. **No hay camino corto.** `POST /autopilot` y `/autopilot/start`
   (`bridge/app/main.py:925`, `:960`) siempre llegan al modelo. Antes del primer
   token se paga `build_system_prompt` (`bridge/app/autopilot.py:133`): método +
   quién eres + ficha + enfoque + recall + denegaciones. **7 953 caracteres**,
   de los que las lecciones eran 9 200 antes del 2026-10-14.
2. **Las herramientas triviales no existen para el modelo.** `POST /tareas` y
   `POST /notas` (`main.py:1551-1600`) están escritas y funcionan, pero no están
   en el schema: `autopilot._tools_schema()` (`autopilot.py:249`) deriva 21 tools
   de `mcp_ops`, y ninguna es "crear una alarma".
3. **Aegis no sabe cuánto tarda.** `main.py:2013` escribe
   `"run_duration_s": 0.0` **hardcodeado**. Sin duración real no hay presupuesto,
   y sin presupuesto no hay clase de latencia.

Y el cuarto, de recursos: **la GPU tiene 6 GB** (`nvidia-smi`: RTX 3050 Laptop,
6144 MiB) y la RAM 15 GiB con **swap solo zram de 15,3 GB** (zstd, del tamaño de
la RAM), `vm.swappiness=150` y `systemd-oomd` activo. Esos tres pelean por el
**page cache**, que es justo de donde un MoE saca sus expertos.

## 2. La forma: clase de latencia, no modelo

Toda petición lleva una **clase**. La clase decide el presupuesto; el modelo
asignado a la clase se lee de una **tabla declarada**, nunca de un `if` en el
bucle.

| Clase | Qué es | Motor | Presupuesto |
|---|---|---|---|
| **T0** | alarma, nota, listar, leer | **ninguno** | < 300 ms |
| **T1** | tool-calling corto, 1-3 pasos | **pequeño, residente** | por medir |
| **T2** | razonar, entender evidencia, revisar | **grande, por turnos** | por medir |

La clase se pide **explícita** (selector del móvil, por defecto T1). Lo único
automático es la escalada T1→T2, y **aparece en la traza**: es auditable.

## 3. La flota: pequeño residente, grande por turnos

### 3.1 Por qué turnos y no convivencia

| | pesos en GPU | KV | total |
|---|---|---|---|
| pequeño (`qwen3:4b` Q4) | 2,5 GB | 0,3–0,6 GB (ctx corto) | **~3 GB** |
| grande (MoE 30B-A3B) | 2,5–3 GB (atención+dense+embeddings) | ~1,9–2 GB (q4 a 64k) | **~5 GB** |

**Suman ~8 GB en 6.** No caben, y el reparto no lo arregla un flag: son turnos.

```
         sin turno                      con turno
   [T1: pequeño]  ──adquirir──▶  [T2: grande]  ──liberar──▶  [T1: pequeño]
        ▲                            │ fail de carga            │
        │                            ▼                          │
        └────── T0 nunca entra en turno ─────────────────────────┘
```

Adquirir un turno **incluye soltar el pequeño**. El intercambio se mide: `qwen3:4b`
son 2,5 GB desde el NVMe, y el orden de las operaciones determina si el turno
cuesta 4 s o 40.

### 3.2 El turno tiene coste propio

```
coste_de_turno = carga_s + trabajo_s + descarga_s
```

Si la carga desde NVMe cuesta decenas de segundos, un turno de tres minutos de
trabajo se paga un 50 % de sobrecarga. Por eso **`gran_modelo` tiene tres modos**,
no uno:

- `por_turno` — se carga al pedirlo y se suelta al terminar.
- `por_ventana` — se queda cargado mientras dura una ventana explícita; todo lo
  pendiente se **agrupa** en una sola carga.
- `nunca` — el grande no está disponible; T2 se rechaza con un `fin` que lo dice.

Agrupar pendientes no es una optimización: es lo que hace que el modo por turnos
sea viable. Sin agrupación, T2 es más caro por run que cualquier otra clase.

### 3.3 La alternativa que también hay que medir

Dar al grande **menos capas en GPU** (`-ngl` parcial, KV a CPU) para que quepa
junto al pequeño. Si el coste medido es pequeño, la convoyencia gana al turno y
esta sección se reescribe. **No se decide a ojo: se mide** (`bin/lab/medir-offload.py`).

## 4. T0: el camino que hoy no existe

Nuevo `bridge/app/intents.py`: registro `{patrón → tool + args}` con **abstención**
(si no está seguro, T1). Herramientas nuevas que exponen al modelo lo que ya
existe por REST: `tarea_crear` (con `vence` → alarma), `nota_crear`, `*_listar`.

La puerta se **reutiliza**: pasan por `autonomy.decide()` (`autonomy.py:616`) como
nivel 1. T0 no es un camino paralelo, es el camino corto *del mismo camino*.

Y es la **red de seguridad** del sistema: con un solo modelo cargado, si el
modelo está caído o cargando, alarmas, notas y preguntas de estado siguen
funcionando.

## 5. Lo que hay que medir

Un **perfil por modelo**, con instrumentos que ya existen
(`bridge/bin/probe-toolcall.sh`, `bridge/bin/lab/measure-models.py`) más lo que
solo importa al desplegarlo:

```
tool_calls {ok, anidados}   calidad_tarea   ttft_s   tok_s
carga_s   descarga_s   vram_gb   ram_gb   acierto_de_tipo
```

La **tabla de asignación** se deriva de los perfiles, no de una opinión:

```
asignacion: {T0: ninguno, T1: <medido>, T2: <medido>, T3: ninguno}
```

Es declarativa, auditable sin abrir el bucle, reversible por variable y testeable
(un test afirma que toda clase tiene motor y que el motor existe).

## 6. Qué NO hacer

- **Dos motores con tools.** El autopilot sigue siendo el único que ejecuta, en
  cualquier clase. El grande no ejecuta nada por sí mismo: su salida es un
  payload que pasa por `autonomy.decide()` y `mcp_ops` igual que hoy. Un modelo de
  20 GB **no amplía el radio de acción** (A-062).
- **Ninguna heurística en el bucle.** Si algo decide, está en la tabla y en la traza.
- **No tocar los guardarraíles** (`mcp_ops.py`) para que algo funcione.
- **No cambiar `autopilot_model` sin N=20** del mismo encargo, nuevo vs actual, con
  las cuatro métricas de AGENTS §4.
- **No dejar el grande cargado.** Eso deshace la decisión de los turnos.
- **No medir calidad con opinión**, y no reusar ninguna medición antigua como puerta.

## 7. Fases

```
F0a  re-medir los 5 modelos locales            sin descargar nada
F0b  llama-cpp: verificar flags y CUDA         luego medir los MoE candidatos
F0c  perfiles → tabla de asignación            derivada de F0
F1   T0 determinista                           ataca las horas, sin modelo
F6   memoria: zram, oomd, MemoryMax            antes de medir nada en serio
F2   presupuesto + ETA real                    arreglar el 0.0 de main.py:2013
F3   app/motores.py                            default = comportamiento actual
F4   leases y turnos + política de recursos     escalada T1→T2 con rastro
F5   concurrencia: un turno a la vez            y qué sobrevive si el modelo cae
F7   systemd --user + stack.sh                 con el servicio del grande
F8   tests + lección                            en lessons/aegis.md
```

F1 antes que F4 a propósito: **T0 no depende de qué modelo gane**.

## 8. Criterio de éxito

1. Una alarma se guarda en **< 300 ms y con 0 tokens de modelo**.
2. Todo run declara clase, presupuesto y estimado, y agota el presupuesto con un
   `fin` explícito en vez de una espera indefinida.
3. La tabla de asignación está en configuración, tiene test, y el 22 de tests de
   `tests/test_autopilot.py` sigue verde sin cambiar el comportamiento por defecto.
4. Un turno T2 se mide de punta a punta (`carga + trabajo + descarga`), no solo el
   `trabajo`.
5. Cambiar de modelo es cambiar una variable, y el cambio se puede deshacer en un
   segundo.

## 9. Decisión pendiente

**Qué califica como T2** — es decir, qué encargos justifican pagar la carga del
grande. Está por definir y es la siguiente conversación: de esa lista salen el
número de turnos por día y, con él, si el modo por turnos o por ventana es el
que sale adelante.