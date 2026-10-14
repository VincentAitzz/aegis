# 003 — Un modelo, y por qué «confiable» no se arregla entrenando

> 2026-10-14. Convierte la conversación sobre el modelo propio en cuatro
> decisiones cerradas, y deja escrita la que **no** se puede tomar todavía.

## El problema

Aegis tenía dos modelos: `llama3.2:3b` residente para T1 (conversación, sin
schema) y `qwen2.5:7b` para T2 (trabajo, con schema). La razón estaba escrita
en `config.py` y era buena:

> con un solo modelo, «abstenerse» significaba pagar sus 4,4 GB y su latencia,
> que es exactamente lo que el camino rápido viene a evitar.

El problema es que **el coste estaba mal medido**. Lo que se comparó fue el
tiempo de un *run de agente* —16,8 s contra 20,6 s, un 18 %—, no el coste de
tener **los dos resident a la vez**.

## Opciones

**A. Dos modelos, como estaba.** Coste: un intercambio de 6–15 s por petición de
trabajo, y dos `llama-server` en RAM a la vez.

**B. Un solo modelo.** T1 pasa a ser «el mismo modelo, sin schema». Se paga algo
de latencia en conversación y se ahorra el intercambio entero.

**C. Medir antes de decidir.** Coste: tiempo. Es lo que se hizo.

## Recomendación

**B.** Y con una medición que no estaba en la discusión: el recurso que se
estaba agotando **no era la VRAM, que es la evidente, sino la RAM.**

```
llama-server (7B)      6,07 GB de RAM
llama-server (embed)   0,64 GB de RAM
```

Dos modelos resident son dos procesos de 6 GB en una máquina de 15 GB. Y «que
Aegis no se cuelgue ni pierda el trabajo» es uno de los cuatro sentidos de
«confiable» que se pactó de acuerdo. **El diseño de dos modelos era, sin saberlo,
la causa de la inestabilidad.**

## Lo medido, con el cambio puesto

| | dos modelos | uno |
|---|---|---|
| primer token en conversación | 261 ms | **269–381 ms** |
| intercambio por petición de trabajo | 6–15 s | **0** |
| RAM del modelo resident | 6,07 GB | **2,94 GB** |

La penalización medida fue de **~40 ms por turno de conversación**, no los
230 ms que se habían estimado. El equilibrio está en ~1 petición de trabajo por
cada 15 turnos de conversación, y por encima de ahí tener las dos solo empeora.

## El contexto de 64k era un requisito sin dueño

`OLLAMA_CONTEXT_LENGTH=64000` venía de `MINIMUM_CONTEXT_LENGTH`, de Hermes. **Hermes
ya no es motor** desde la Fase 1: quedó como sonda de salud
(`docs/decisiones/002`). El requisito se quedó sin dueño y se seguía pagando,
que es la forma más común de que un número sobreviva a lo que justificaba.

| contexto | prompt que aguanta |
|---|---|
| 64.000 | 40× el prompt real — del orden de 38 GB de RAM |
| **32.768** | **20×** |
| 16.384 | 10× |

El prompt real son 5.606 chars (1.602 tokens); el peor caso construido, 16
pasos con resultados largos, son 15.321. **32.768 deja 2,1× de margen** y
ahorra ~1,8 GB de KV en f16.

## Los topes, que no son ajustes sino límites

En `infra/ollama/start-ollama.sh`:

| variable | valor | por qué |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | el bucle es secuencial; en paralelo se duplica el KV para nada |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | el 7B y el de embeddings. Con tope 1, cada búsqueda en memoria expulsaría al modelo del trabajo. Con tope 2, un tercero no puede entrar |
| `OLLAMA_FLASH_ATTENTION` | `1` | menos memoria de KV, más rápido, sin contrapartida medible |
| `OLLAMA_KEEP_ALIVE` | `60m` | ya no hay intercambio entre clases |

`OLLAMA_KV_CACHE_TYPE=q8_0` está **commented**: reduciría el KV a la mitad pero
degrada la calidad en silencio. Es el siguiente peldaño si la RAM sigue justa, y
una palanca que solo se tira a propósito.

## Lo que se decidió NO hacer

### No entrenar todavía, y por qué no es una decisión de hardware

La pregunta «¿puedo crear un modelo propio?» tiene dos respuestas distintas que
se confunden:

| | |
|---|---|
| **¿Cabe en la GPU?** | **Sí.** QLoRA de un 7B en 4 bits: ~5,0–5,5 GB de 6. |
| **¿Hay con qué entrenarlo?** | **No.** ~100 ejemplos utilizables frente a 3.000. |

Un LoRA necesita años, no meses, de ejemplos etiquetados. **Falta un factor de
20, y ese factor se rellena con conversaciones, no con GPU.** Por eso el
dataset es el trabajo de estos meses y el entrenamiento es una decisión que se
tomará con los datos delante, no ahora.

La palanca que sí está puesta es `bridge/app/conversaciones.py`: cada turno de
`/chat` se guarda con su veredicto, y `corregir()` admite un **motivo**, que es
lo único que enseña. Un ejemplo positivo dice cómo es una respuesta buena; el
par «respuesta mala + motivo» dice **qué se esperaba**.

### No añadir un modelo más

`qwen2.5-coder:7b` está descargado y no se usa. Los números de `002` (n=2-3,
octubre) ya no son una base para decidir, y añadir un tercer modelo resident es
justo lo que este documento acaba de eliminar.