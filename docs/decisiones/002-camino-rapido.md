# 002 — El camino rápido: qué se expone al modelo y qué no

> 2026-10-05. Convierte la fase F0 de `docs/vision.md` §5 en algo construido.

## El problema

Medido: un run del agente tarda **~21-49 s** para «lista los proyectos», y paga
**35.835 chars de prompt por paso**. Pero «qué hora es» son **0,03 ms** y «pon una
alarma» es una fila en SQLite. El 90 % de lo que se le pide a un asistente no
necesita un modelo.

## Opciones

**A. No hacer nada.** Coste: cero. La voz empieza por un minuto de silencio, y un
asistente de voz con un minuto de silencio no es un asistente de voz.

**B. Exponer las tools T0 al modelo, como propone `docs/motores.md` §4.**
Coste: el schema de `mcp_ops` son **19.083 chars que se pagan en cada paso de cada
run**. Añadir tools ahí agranda el prompt para todos los runs a cambio de acelerar
los que ni las usan.

**C. Un router determinista delante, que llama a las funciones directamente.**
Coste: un módulo más y una lista de patrones que mantener. El schema no crece.

## Recomendación

**C.** Motivo, medido: **el prompt es la variable, no el modelo**.

| condición | prompt | mediana | min |
|---|---|---|---|
| con proyecto `aegis` | 35.835 chars | **49,1 s** | 33,9 s |
| sin proyecto | 22.847 chars | **18,5 s** | 6,9 s |

Un **36 % menos de prompt** dio un **62 % menos de tiempo**. Y la palanca sobre el
prompt es exactamente el schema de tools, que es lo único que se paga en cada paso
sin condición. Meter ahí lo que solo sirve para el camino rápido sería hacer más
lento el motor para acelerar el subconjunto que no lo necesita.

## Qué se construyó

- `bridge/app/intents.py` — registro `{patrón → tool + args}` con **abstención**.
  Llama a funciones Python, **no** al schema.
- `POST /voces` — `preparar → autonomy.decide() → aplicar`, en ese orden.
- `t1_model` en `config.py`.

## Lo medido, sin suponer nada

| | |
|---|---|
| T0 «qué hora es» | **0,03 ms** de servidor |
| T0 «qué proyectos hay» | **3,3 ms** |
| T0 «mis tareas» | **0,3 ms** |
| Presupuesto de `vision.md` | 300 ms — **cumplido con margen de 10×** |

**T1: la hipótesis era falsa.** Se suponía que un modelo pequeño sería más rápido.
Medido con el mismo encargo:

| modelo | mediana | tool-calling | VRAM |
|---|---|---|---|
| **`llama3.2:3b`** | **16,8 s** | sí | 1,9 GB |
| `qwen2.5:7b` | 20,6 s | sí | 4,4 GB |
| `qwen2.5-coder:7b` | 31,4 s | sí | 4,4 GB |
| `gemma3:4b` | — | **roto** | 3,3 GB |
| `qwen3:4b` | **212 s** | sí | 2,4 GB |

`qwen3:4b` era la suposición original y era **10× más lento**: es un modelo de
*thinking* y genera el razonamiento antes de responder. Menos parámetros, peor
latencia. Se cambió por lo medido, no por lo que parecía.

**Y el margen es de un 18 %**: 16,8 contra 20,6. El modelo no es la palanca. El
prompt sí. Por eso `t1_model` ayuda poco y por eso el recorte de prompt es lo que decide si la voz es viable.

## Qué lo falsaría

Que un prompt de 22.847 chars siga tardando más de 3 s en un run de una tool. Si
pasara, el prompt **no** sería el cuello de botella y todo este análisis apuntaría
al sitio equivocado. Se mide con la tabla de arriba, que se puede repetir.

## Qué invariante toca

Ninguna directamente, pero hay dos que este trabajo deja en el aire y hay que
cerrar antes de F1:

1. **La puerta va antes de escribir, y eso está resuelto.** `preparar()` es puro;
   `ejecutar()` **no puede** escribir (lanza `RuntimeError`). La puerta es
   `preparar → decide → aplicar`, y hay un test que la invierte a propósito para
   comprobar que se detecta.
2. **La primera cuando hay un micrófono abierto.** Una alarma es inocua; un
   micrófono abierto hace que la falla sea *Aegis oyendo en tu casa*. Entra en F1,
   no después.

## Lo que queda abierto

- **`para` es `YYYY-MM-DD`: no hay campo de hora.** «pon una alarma a las 7»
  **abstiene** y cae a T1, en vez de guardar media cosa y decir que la guardó
  entera. La columna que falta es `para_hora`, con índice para `vencidas()`. Sin
  ella, las alarmas con hora son media feature.
- **La puerta no cubre intents de nivel 3.** Hoy ninguno lo es. Cuando lo haya,
  `preparar` sigue siendo puro y el orden se mantiene, así que no hay nada que
  arreglar — pero conviene que el primer intent de nivel 3 venga con su test.
- **`gemma3:4b` está roto** y no se ha investigado por qué. Queda anotado para
  que no se pregunte de nuevo.