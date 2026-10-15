# Medidas

Las cifras que justifican el diseño. **No son afirmaciones: son replicables**, y
cada una dice con qué se comparó y cuántas veces.

Este fichero existe por una razón concreta: una medición **no** se puede
deducir del código. El día que alguien cambie el prompt, el modelo o la máquina,
estos números no los puede volver a sacar nadie sin repetir los experimentos — y
un número que solo existe en la cabeza de quien lo midió deja de ser un dato el
mismo día que deja de estar en su cabeza.

Cada medición dice **qué se comparó con qué** y **con qué n**. Una cifra sin su
comparativa no es una medición, es un número sin unidades.

## La regla que salió de aquí

> **Cada bloque que entra en el prompt tiene que justificar su coste con una
> medición. Si la medición dice que no hace nada, sale.**

Está escrita en `README.md` porque no es de este fichero: es del sistema.

---

## 1. El prompt es el cuello de botella

**2026-10-05 · `docs/decisiones/002` · n=2-3 por variante, mismo encargo**

| prompt | tool-calling | latencia |
|---|---|---|
| con proyecto `aegis` — 35 835 chars | — | **49,1 s** |
| sin proyecto — 22 847 chars | — | **18,5 s** |

Un 36 % menos de prompt, un 62 % menos de tiempo. El prompt es la palanca.

## 2. Cambiar de modelo no es la palanca

**2026-10-05 · mismo encargo, n=2-3**

| modelo | mediana | ¿tool-calling? | VRAM |
|---|---|---|---|
| **`llama3.2:3b`** | **16,8 s** | sí | 1,9 GB |
| `qwen2.5:7b` | 20,6 s | sí | 4,4 GB |
| `qwen2.5-coder:7b` | 31,4 s | sí | 4,4 GB |
| `gemma3:4b` | — | **roto** | 3,3 GB |
| `qwen3:4b` | **212 s** | sí | 2,4 GB |

`qwen3:4b` era la suposición y era falsa: 12× más lento que `llama3.2:3b`. Es un
modelo de *thinking* y genera el razonamiento antes de responder. Menos
parámetros, peor latencia.

## 3. La memoria contaminada hunde el tool-calling

**2026-09-30 · ablación sobre el prompt real, n=8 cada variante**

| variante del system prompt | tool-calling |
|---|---|
| completo, con 3 episodios falsos en memoria | **0/8** |
| completo **sin** el bloque de memoria | **7/8** |
| memoria con encabezado pero 0 episodios | 6/8 |
| mínimo (69 chars) | 8/8 |

**Tres episodios falsos bastan.** Con memoria limpia el mismo código dio
**16/16 en dos rondas**, sin falsos éxitos.

Lo que **no** era la causa, y se comprobó para no seguir perdiendo días:

| Callejón | Resultado |
|---|---|
| Recortar el prompt a 2 280 chars | siguió en **0/8** |
| 15 tools o 23 tools | igual |
| Prefijo `mcp__` en el nombre | 10/10 y 9/10 |
| Instrucción fuerte en `instructions` | **0/8** |

## 4. Las lecciones costaban y no compraban nada

Esta es la medición que retiró el mecanismo (2026-10-14). **A/B alternado, dos
procesos del bridge en la misma máquina en el mismo momento**, no bloques
seguidos: entre bloques la máquina se calienta y el modelo se descarga, y la
diferencia que se ve es ese ruido.

### 4a. Lo que ya estaba medido antes (2026-10-04, n=5)

| prompt | tool-calling | latencia |
|---|---|---|
| con las 120 KB enteras (127 738 chars) | 5/5 | **60,2 s** |
| con el índice (16 720 chars) | 5/5 | 11,9 s |
| sin lecciones (4 489 chars) | 4/5 | 10,1 s |

Y el comportamiento que las lecciones describen no cambiaba: A-014 («no repitas
la llamada idéntica que ya falló dos veces») se repitió **3 de 3 con las
lecciones inyectadas y 3 de 3 sin ellas**.

### 4b. El A/B de la retirada — y el número que estaba mal

**Primera medición, 2026-10-14, n=12 (6 pares):**

| | sin lecciones | con lecciones |
|---|---|---|
| **tool-calling** | **6/6** | **6/6** |
| latencia, mediana | **40,0 s** | **71,8 s** |
| latencia, rango | 34,0 – 55,2 | 64,3 – 103,6 |

De aquí sale «**+31,8 s, +79 %**», y ese número se publicó. **Es falso.**

**Remedido en un solo proceso**, alternando, con `bin/lab/medir-prompt-costo.py`:

| | sin lecciones | con lecciones |
|---|---|---|
| primer token | 3,07 s | 4,24 s |
| total | **12,5 s** | **16,3 s** |
| | | **+3,8 s (+31 %)** |

Ocho veces menos. El A/B original levantaba **dos procesos del bridge contra la
misma GPU** y alternaba los requests entre ellos: lo que estaba midiendo era
**contención**, no prompt. Dos procesos pidiendo al mismo Ollama con 6 GB de VRAM
se estorban, y esa diferencia es la que salió.

### Lo que sí se sostiene

| conclusión | evidencia | ¿se sostiene? |
|---|---|---|
| El tool-calling no cambia | 6/6 y 6/6 en el A/B; 3 de 3 con y sin en 2026-10-04 | **Sí** |
| El prompt cuesta algo | +3,8 s (+31 %) en un proceso | **Sí**, pero 8 veces menos de lo que se dijo |
| La tool `lecciones` no se usó | 0 llamadas en 857 run logs | **Sí** |
| El índice estaba truncado | 8 000 chars de tope listaban A-001…A-078 de 121 | **Sí** |

**La decisión no cambia**: 54 % del prompt para algo con 0 llamadas, 0 efecto en
el comportamiento y contenido truncado sin avisar. Lo que estaba mal era la
cifra, y una cifra falsa en un fichero que se llama `medidas.md` es exactamente
el fallo que este repo dice no cometer.

### Y una observación que salió de arreglarlo

Con el prefijo **estable** el prompt de 7 953 chars cuesta **+30 ms** al primer
token: la caché de prefijo de Ollama lo absorbe casi entero. El coste real no es
el tamaño, es que el prefijo **cambie**.

| | primer token |
|---|---|
| prompt de 60 chars | 0,13 s |
| prompt de 7 953 chars | 0,16 s |

Eso decide una cosa para siempre: **todo lo estable va en el prompt**, porque es
barato. Lo caro no es meter contexto, es **meterlo en el sitio equivocado**.

## 5. Hablar con Aegis: lo que cuesta y por qué el chat no lleva schema

**2026-10-14 · `POST /chat` · máquina de referencia**

### 5a. El modelo no es lento. El sistema no hablaba.

`"stream": False` estuvo en la llamada al modelo desde el primer commit. Con eso
no se emitía nada hasta que el modelo **terminaba**:

| | primer token | turno corto | turno de trabajo |
|---|---|---|---|
| `llama3.2:3b` | **0,14 s** | 2,0 s | 14,0 s |
| `qwen2.5:7b` | **0,37 s** | 5,3 s | 99,1 s |

El tiempo hasta el primer token no cambia casi nada al poner streaming. Lo que
cambia es que **a los 0,14 s ya hay una palabra en la pantalla**.

### 5b. Con el schema delante, el modelo llama tools aunque no haga falta

Mismo modelo, misma máquina, con y sin el schema de 21 tools:

| | primer token | total | ¿llamó a una tool? |
|---|---|---|---|
| 3B **sin** schema | **0,02 s** | **0,17 s** | no |
| 3B **con** schema (19 649 chars) | — | 0,39 s | **siempre** |

Un «hola, ¿qué tal?» con el schema produce una llamada a `quien_eres_actualiza`.
**El modelo no sabe cuándo no usar una herramienta.** Por eso `/chat` no se lo
pone delante, y por eso la escalada a T2 no se le deja decidir: escala solo
cuando **T1 se queda callado**, que es observable.

### 5c. Los dos modelos no caben en la tarjeta

VRAM: 6 144 MiB. `llama3.2:3b` = 2,0 GB, `qwen2.5:7b` = 4,7 GB. **Suma 6,7 GB.**

| | carga en frío | resident |
|---|---|---|
| `llama3.2:3b` | 6,5 – 14,7 s | **0,27 s** |
| `qwen2.5:7b` | 10,8 s | 1,12 s |

**Cada escalada entre T1 y T2 cuesta 6 – 15 s.** Y T1 ahorra 0,2 s de primer token.
Ese es el cálculo entero, y por eso el conversational va con el resident: una
conversación no puede provocar un swap.

### 5d. Lo que contestaba el 3B sin saber qué era

Sin identidad en el prompt, contesta de memoria. Medido por HTTP contra `/chat`:

| se le preguntó | respondió |
|---|---|
| «cuéntame qué puedes hacer» | «tareas relacionadas con la **seguridad de la información**» |
| «revisa el repositorio aegis y dime si el verificador está en verde» | «Verificando… **Está en verde.**» |

La segunda es A-016 con otro traje. En el autopilot la delata la traza, porque el
veredicto se calcula de los pasos ejecutados. En una conversación **no hay traza**:
la única defensa es que no tenga con qué mentir.

Con `identidad_para_el_prompt()` (234 chars) y `como_texto()` en el prompt:

| se le preguntó | respondió | total |
|---|---|---|
| «cuéntame qué puedes hacer» | la lista real de herramientas | **0,01 s** (T0, sin modelo) |
| «hola, ¿qué tal?» | «Estoy listo. ¿En qué puedo ayudarte?» | 0,80 s |
| «¿ya está todo bien en mis proyectos?» | «**no lo comprobé.**» | 0,63 s |
| «estoy aburrido» | una pregunta | 0,75 s |

## 6. La puerta que nadie usó

**2026-09-24 → 2026-10-14 · los 857 run logs de `bridge/data/logs/runs/`**

| tool | llamadas |
|---|---|
| `projects_list` | 34 |
| `aegis_read_file` | 6 |
| `verify_deploy`, `build_apk` | 1 cada una |
| **`lecciones`** | **0** |
| **`usar_enfoque`** | **0** |
| `memoria` | 0 — **la acabo de crear**, así que su 0 es provisional |

`lecciones` se retiró por esto (sección 4). `usar_enfoque` **sigue ahí**: tiene las
mismas 0 llamadas y es el siguiente candidato, pero los enfoques son un mecanismo
de decisión y no de memoria. No se retira en el mismo movimiento algo que ya está
medido, junto a otra cosa que no.

Y el índice, además, estaba truncado: con el tope de 8 000 chars listaba
A-001…A-078 de 121. Se pagaba el 100 % del coste para enseñar el 65 %.

---

## 7. Un modelo, y qué se comprueba de lo que dice

2026-10-14. Decisiones en `docs/decisiones/003`.

### 7a. Un modelo en vez de dos

| | dos modelos | uno |
|---|---|---|
| primer token en conversación | 261 ms | **269–381 ms** |
| intercambio por petición de trabajo | 6–15 s | **0** |
| RAM del modelo resident | 6,07 GB | **2,94 GB** |

La penalización por turno de conversación salió a **~40 ms**, no a los 230 ms
estimados: con un prompt de 1.602 tokens, el primer token lo marca el ancho de
banda de los pesos, y los dos modelos caben igual de bien. El intercambio es lo
que se elimina, y era de 25 a 150 veces más caro que lo que se paga.

### 7b. El contexto de 64k era un requisito sin dueño

| | |
|---|---|
| prompt real del sistema | **5.606 chars ≈ 1.602 tokens** |
| peor caso construido (16 pasos) | ≈ 15.321 tokens |
| contexto antes / ahora | 64.000 / **32.768** |
| KV en f16 antes / ahora | ≈3,6 GB / **≈1,8 GB** |

Los 64k venían de `MINIMUM_CONTEXT_LENGTH`, de Hermes. Desde la Fase 1 Hermes
es una sonda de salud, no un motor. El número siguió porque nadie lo quitó
consigo sujustifylo.

### 7c. Qué se comprueba de una respuesta, y cuánto se caza

`app/evidencia.py` extiende la regla de A-016 —el veredicto sale de la traza,
nunca de `final_text`— un nivel arriba: **las afirmaciones también**.

Sobre los 103 runs `completado` del histórico:

| | |
|---|---|
| su respuesta nombra un fichero | 21 |
| su respuesta afirma «en verde» | 2 |
| **afirman algo comprobable** | **19 (18 %)** |
| **caen sin respaldo** | **0** |

**Cero, y es el resultado correcto.** Cuando el modelo va a trabajar llama al
verificador y no tiene que decirlo. El fallo que la regla previene no estaba en
los runs de agente.

El coste de la regla, medido en cada versión en que se rompió:

| versión | falsos positivos | detecciones |
|---|---|---|
| sin filtro | 3 | 0 |
| solo prosa (sin citas, listas ni código) | 1 | 0 |
| afirmación de menos de 100 caracteres | 0 | 0 |
| afirmación en las dos primeras frases | **1** | **0** |

La última es la que está. **Un falso positivo de 220 runs (0,5 %):** la
respuesta reproducía el índice de las lecciones del repo y la regla leyó «en
verde» como una afirmación suya. No lo era —la frase citada dice justo lo
contrario— pero venía dentro de una enumeración y de las dos primeras frases.

Los criterios probados antes elegían **un número** —longitud de línea, posición
de la frase— y los dos fallaron en los dos sentidos: 100 caracteres se saltaban
un «No necesito tools para confirmar eso. **El verificador está en verde.**» de
102, y la posición 120 agarraba el índice con el match en el 92. Se paró ahí a
propósito: **cuarto criterio para un artefacto mal formado es sobreajustar**, y
un test con el residuo escrito está en `tests/test_evidencia.py` para que el
coste no desaparezca de la vista.

| lo que sí funciona | |
|---|---|
| camino de la conversación, en vivo | **cero falsos positivos** |
| detecciones en vivo | 2 de 2 (la afirmación salía sin comprobar nada) |

### 7d. Donde sí muerde: la conversación

En `/chat` no hay verificador, y el hueco se llena de «está en verde» sin
comprobar. Comprobado en vivo:

```
«el verificador esta en verde»
  → «Entendido, el verificador esta en verde. ¿En qué te puedo ayudar hoy?»
  → turno guardado con sin_respaldo: 1
```

Y el caso que la que originó la regla, de la lección A-016:

```
«revisa el repositorio aegis y dime si el verificador está en verde»
  → «Verificando… Está en verde.»      (sin haber ejecutado nada)
```

### 7e. Dos bugs que solo aparecieron al medir

| bug | síntoma |
|---|---|
| la respuesta entraba en «lo que el modelo ha visto» | cualquier ruta inventada se respaldaba a sí misma |
| el punto final no cerraba el regex de rutas | **ninguna ruta al final de una frase se encontraba** |

El segundo es el peor de los dos, porque una comprobación que no suena nunca
**parece que pasa**. Lo cazó un test que escribí para otra cosa.

## 8. Cómo pides las cosas, medido sobre tus propias sesiones

2026-10-14. Fuente: `~/.local/share/opencode/opencode.db`, 545 prompts, de los
que **500 son tuyos** (45 eran el prompt del arnés, «Continue if you have next
steps», que no cuenta). Instrumento: `bridge/bin/medir-cobertura`.

### 8a. El reparto de tus prompts

| patrón | n | % |
|---|---|---|
| **continuar** — `procede`, `continua`, `dale` | 95 | **19 %** |
| corregir | 61 | 12 % |
| explorar | 44 | 8 % |
| aprobar | 33 | 6 % |
| construir | 22 | 4 % |
| mediana de longitud | **138 chars** | — |
| menos de 80 caracteres | 169 | 33 % |
| **sin tildes** | — | **94 %** |

### 8b. La mitad de los «procede» vienen con requisitos

De 88 reales, **44 llevan algo detrás**:

> «Procede, los sin numero tambien incluyelos para manejarlos manualmente pero
> haz la separacion de los otros»

Eso no es continuar: es cambiar los requisitos de lo que ya se estaba haciendo.
Y desde el 2026-10-14 el intent `procede` separa los dos casos.

### 8c. La cobertura, antes y después

Sobre **216 prompts de sesiones de `aegis`** (los otros cinco proyectos no se
abren: no están en `PROJECTS`):

| | los entiende sin modelo | se los pasa al modelo |
|---|---|---|
| antes | **0** (27 %) → `procede` no existía | 100 % |
| ahora | **60 (27 %)** | 156 (72 %) |

### 8d. Los tres falsos positivos

De los 40 «procede» con requisitos, tres no lo eran:

| frase | lo que veía |
|---|---|
| `Procede tal cual como dices` | resto: «tal cual como dices» |
| `Dale procede asi entonces` | resto: «procede asi entonces» |
| `Procede nomas rey` | resto: «nomas rey» |

Son **énfasis**, no requisitos. Sin corregirlos, Aegis reformula el plan con un
requisito inventado y eso sale en el informe como cambio drástico. Se cazaron
**midiendo sobre los datos reales** con `--detalle`, no con un test: un test con
frases inventadas habría dado verde para siempre.

### 8e. Un detalle que salió al medir

Uno de los prompts de `aegis` trae una **IP de Tailscale con el token de sesión
dentro**, y otro habla de «la clave de api». Por eso `medir-cobertura` redacta IPs,
UUID, números largos, claves y tu ruta de casa antes de imprimir: un instrumento
que imprime secretos es un instrumento que algún día los imprime donde no debe.

## 9. El run que sobrevive al reinicio

2026-10-14. El paso que hacía falta para «revisar lo que Aegis hizo en mi ausencia».

### 9a. Qué se perdía

`_AUTOPILOT_RUNS` es un `dict` en memoria, y `aegis-bridge.service` está en
`Restart=always`. Además el JSONL se escribía **entero al terminar**, con
`open("w")`. Las dos cosas juntas:

| | antes |
|---|---|
| el fichero de un run cortado | **no existía** |
| el estado en memoria | se perdía con el proceso |
| lo que se podía decir después | nada. Ni error, ni motivo, ni punto de corte |

### 9b. El cambio: el log pasa a ser append-only

| | cuándo |
|---|---|
| `task.created` | al arrancar el run |
| `tool.completed` | **en cuanto termina cada paso**, no al final |
| `text.delta`, duración y terminal | al cerrar |

Un corte deja `task.created` más los pasos que se alcanzaron a hacer, y eso **es**
el estado: estaba en marcha, y se paró en el paso N.

### 9c. Recuperado, con `interrumpido`

Al arrancar, `app/recuperacion.py` relee `data/logs/runs/autopilot-*.jsonl` y
devuelve los runs al buffer. **Nunca dice `running`**: la tarea no existe tras el
reinicio, y un cliente esperando a un `running` que no va a llegar espera para
siempre.

Los que no tienen evento terminal se **sellan** con `task.failed` y
`fin: interrumpido`, y el estado nuevo cuenta aparte:

```
ESTADO              n     %
  completado        104   45.2%
  esperando_ok       67   29.1%
  incompleto         42   18.3%
  interrumpido        7    3.0%    ← nuevo
  roto                7    3.0%
```

**`interrumpido` no es `roto`.** Un `SIGKILL` a media tarea y una tarea que
fallan no son lo mismo, y meterlos en el mismo número esconde justo lo que hay
que mirar. El corte además dejó trabajo a salvo, y eso se cuenta:

> «el proceso se reinició con el run en marcha; 1 paso(s) quedaron a salvo en su
> traza»

### 9d. Lo que salió por el camino: un bug que llevaba semanas

Al probar esto se descubrió que **`POST /autopilot/start` nunca había ejecutado
un run**. `_runner()` estaba definida —con su `try`, sus dos `except` y la
escritura de la traza del fallo— y **debajo no había nada**.

Lo que se veía era lo que hace un fallo silencioso bien hecho: `200 OK`, un
`run_id` válido y un `status: running` para siempre. `/autopilot` **síncrono** sí
funcionaba, porque llama a `_run_autopilot_once` directamente: los dos caminos
compartían todo el trabajo y se diferenciaban en **una línea**.

Se encontró por un camino lateral —había que lanzar un run real para matarlo— y
se localizó con un log de cuatro líneas. Es A-127.

## Cómo se mide otra vez

| Lo que quieres saber | El instrumento |
|---|---|
| De qué está hecho el prompt | `bin/medir-prompt.py` |
| Si el prompt grande rompió el tool-calling | `bin/lab/medir-autopilot.py` |
| Un A/B de dos prompts, alternando | `bin/lab/medir-prompt-ab.py` |
| Qué modelo va más rápido | `bin/lab/measure-models.py` |
| Cómo se reparten los estados del histórico | `bin/medir-runs` |
| Si el modelo emite tool-calling de verdad | `bin/probe-toolcall.sh` |
| Cuánto cuesta un bloque del prompt, **en un proceso** | `bin/lab/medir-prompt-costo.py` |
| Si el conversational escala, y lo que cuesta el swap | `bin/lab/medir-prompt-ab.py` y §5c |
| Cuánto de lo que pido casca con un intent, y qué se escapa | `bin/medir-cobertura --detalle` y §8 |
| Cuántos runs se cortaron y qué dejaron a salvo | `bin/medir-runs` y §9 |

`probe-toolcall.sh` mida **una** tool con un prompt mínimo. Sirve para detectar
que el modelo **dejó** de emitir tool-calls; **no** sirve para declarar que el
flujo real funciona. Eso se mide end-to-end, y por eso existe el primero de los
tres.