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

### 4b. El A/B de la retirada (2026-10-14, n=12, 6 pares)

`bin/lab/medir-prompt-ab.py`. El bloque viejo se reconstruye desde
`git show 0669557~1:bridge/app/autopilot.py` en un proceso aparte: **el código de
producción no cambia**, que es lo que hace la comparación honesta.

| | sin lecciones | con lecciones |
|---|---|---|
| **tool-calling** | **6/6** | **6/6** |
| latencia, mediana | **40,0 s** | **71,8 s** |
| latencia, rango | 34,0 – 55,2 | 64,3 – 103,6 |

Dos conclusiones, y la segunda es la que importa:

1. **El tool-calling no cambia.** 6/6 en los dos grupos, y 6/6 en la ronda
   anterior: 12/12 en total. Coincide con el 3/3 de 2026-10-04. Las lecciones
   nunca pusieron a este modelo a dejar de llamar a una tool.
2. **La latencia sí, y mucho: +31,8 s, un 79 %.** En la ronda templada el
   **mínimo del grupo con (64,3) es mayor que el máximo del grupo sin (55,2)**.
   Cero solape. Con n=6 y esa dispersión, una diferencia menor que el ruido no se
   afirma; esta no lo es.

Y el tamaño, con `bin/medir-prompt.py`:

| | antes | después |
|---|---|---|
| system prompt | 17 155 chars | **7 953** |
| de los cuales, lecciones | 9 200 (**54 %**) | 0 |
| tools en el schema | 22 | 21 |

## 5. La puerta que nadie usó

**2026-09-24 → 2026-10-14 · los 857 run logs de `bridge/data/logs/runs/`**

| tool | llamadas |
|---|---|
| `projects_list` | 34 |
| `aegis_read_file` | 6 |
| `verify_deploy`, `build_apk` | 1 cada una |
| **`lecciones`** | **0** |
| **`usar_enfoque`** | **0** |

Y el índice, además, estaba truncado: con el tope de 8 000 chars listaba
A-001…A-078 de 121. Se pagaba el 100 % del coste para enseñar el 65 %.

---

## Cómo se mide otra vez

| Lo que quieres saber | El instrumento |
|---|---|
| De qué está hecho el prompt | `bin/medir-prompt.py` |
| Si el prompt grande rompió el tool-calling | `bin/lab/medir-autopilot.py` |
| Un A/B de dos prompts, alternando | `bin/lab/medir-prompt-ab.py` |
| Qué modelo va más rápido | `bin/lab/measure-models.py` |
| Cómo se reparten los estados del histórico | `bin/medir-runs` |
| Si el modelo emite tool-calling de verdad | `bin/probe-toolcall.sh` |

`probe-toolcall.sh` mida **una** tool con un prompt mínimo. Sirve para detectar
que el modelo **dejó** de emitir tool-calls; **no** sirve para declarar que el
flujo real funciona. Eso se mide end-to-end, y por eso existe el primero de los
tres.