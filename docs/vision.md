# Visión

> **Qué es Aegis cuando esté terminado**, y en qué orden se llega. Este
> documento es la dirección; `docs/motores.md` es un plan de latencia que cuelga
> de él, y `docs/decisiones/` es el registro de por qué cada decisión se tomó.
>
> Ninguna puerta de este documento se cruza con números heredados de la
> conversación. Se cruza con lo que `bin/medir-runs` y `bin/lab/` midan.

## 1. El objetivo

Un asistente **ambiental**: te oye sin que pulses nada, entiende lo que dices,
actúa sobre tus herramientas, recuerda lo que importa de ti, ve lo que le pides
ver, y te avisa de los problemas que él encuentra antes de que se los digas.

No es un chat. La prueba de que existe es que **funciona cuando no lo miras**.

## 2. Qué es hoy, con números

Medido el 2026-10-05. Ninguno de estos números es una opinión:

| | Hoy | Lo que el objetivo necesita |
|---|---|---|
| **Lo que no necesita modelo** | **0,03 ms** — T0 existe desde 2026-10-05 | < 300 ms ✅ **cumplido, margen 10×** |
| Latencia de un run del agente | **18,5-49,1 s** (en caliente; ~58 s en frío) | por debajo de 3 s |
| Prompt por paso | **35.835 chars** (~9.000 tokens) × hasta 16 pasos | **es la palanca**: ver abajo |
| Schema de tools | **19.083 chars**, fijo, en cada paso | — |
| VRAM | **6 GB** (RTX 3050) | o más, pero **no es la variable que decide** |
| Runs completados | **45,1 %** de 133 | sube solo al medir el coste por paso |
| Herramientas del agente | **22, todas de código** | + voz, cámara, agenda, casa, noticias |
| Línea base de latencia histórica | **133 runs con `0.0` hardcodeado** | desde 2026-10-05 se mide de verdad |
| Voz, sentidos, reconocimiento facial | **no existe** | es la mayor parte del trabajo |

**Los dos datos que deciden el orden:**

**El primero, medido el 2026-10-05**: el prompt **es** la variable. Con 35.835 chars
un run tardaba **49,1 s**; con 22.847, **18,5 s**. Un 36 % menos de prompt, un
**62 % menos de tiempo**. Y el schema de tools (19.083 chars) es la parte del prompt
que se paga en cada paso **sin condición** — es la primera a recortar.

**El segundo**: un asistente de voz que tarda medio minuto en responder no es un
asistente de voz, es un teléfono roto. Por eso la primera fase no es una capacidad
nueva: es la latencia. Y ya está hecha a medias — T0 responde en 0,03 ms, lo que
significa que **el problema ya no es qué hacer sino que todo siga entrando por el
modelo**.

Y la sorpresa útil: **cambiar de modelo no sirve**. `llama3.2:3b` tarda 16,8 s
contra los 20,6 s del 7B — un 18 %. La suposición de que un modelo pequeño sería
rápido era **falsa**: `qwen3:4b` tarda 212 s. Ver `docs/decisiones/002`.

## 3. El hardware es una variable, no una bifurcación

Existe la opción de migrar a una máquina con 24 GB de VRAM. **Esa decisión no
debe cambiar la arquitectura**: el modo de residencia es una variable, no un fork.

- La **tabla de residencia** (`docs/motores.md` §5) dice qué modelo vive con cuál.
  Se deriva de perfiles medidos, no de una opinión.
- Con **6 GB → turnos**: el grande se carga, se usa, se suelta. Con **24 GB →
  convivencia**: puede quedarse cargado.
- **Mismo código, valor distinto.** Cambiar de máquina es cambiar una variable.
  Si una propuesta solo funciona con 24 GB, está incompleta: lo dice así de claro
  y declara qué se pierde hoy.

Sobre 6 GB, los residentes que caben y los que no:

| | Cabe | Nota |
|---|---|---|
| Wakeword (openWakeWord) | sí | **CPU**, ~10 MB. Nunca toca la GPU. |
| STT (whisper.cpp `small` Q5) | sí | ~1 GB si va en GPU; en CPU va ~2× realtime |
| TTS (piper) | sí | **CPU**, ~50 MB, más rápido que tiempo real |
| LLM pequeño (4B Q4) | sí | ~2,5 GB |
| LLM grande (MoE 30B) | no | ~5 GB, solo por turno |
| Visión (LLaVA 7B) | no | compite con el LLM por los mismos 6 GB |

**La restricción que manda**: el wakeword tiene que ser un proceso **CPU puro,
separado**, que nunca espere a la GPU. Si no, el asistente se queda sordo
exactamente cuando está pensando. Eso es lo primero que muere si se intenta
cargar «todo junto».

## 4. Las invariantes

Las tres del repo original se reemplazan. Sus principios eran buenos;
cambia la forma, no el fondo.

| Antes | Ahora |
|---|---|
| *Aegis nunca es punto único de falla* | **Aegis se apaga bien.** Todo dispositivo tiene timeout y estado seguro por defecto. El hub de casa es *fail-safe*, no *fail-immune*: si muere, la casa no queda en un estado raro. Es un requisito distinto, y más barato. |
| *Aegis nunca es la autoridad* | **Tiene autoridad, y no puede usarla en silencio.** Toda acción con consecuencia irreversible pasa por aprobación de un solo uso. **Ningún pago es automático**, ni con permiso concedido de antemano. |
| *El bridge es de un solo proceso* | **Un proceso por nodo.** Móvil, reloj y casa son clientes, no bridges. El motivo real sigue vigente: el estado en memoria hace que un `stop` a otro worker dé un 404. |

Y dos nuevas que no tenían):

- **Lo íntimo no sale de la máquina.** Audio, fotogramas y rostros no van a
  terceros sin permiso explícito y medible.
- **Siempre se puede saber qué hizo y por qué.** Traza y veredicto existen; se
  extienden a los sentidos: quién vio qué, cuándo.

Y el criterio de aceptación de todo lo anterior: **un asistente que no se puede
apagar no es un asistente, y uno que no se puede auditar es un problema de
seguridad.**

## 5. Las fases

El orden es **por dependencia**, no por excepción. F0 es la razón de que F1
sea posible, y F5 va al final porque convierte cada fallo anterior en un fallo
**autónomo**.

### F0 — Latencia · **hecho el 2026-10-05**, a medias

- ✅ `app/intents.py`: router con abstención. Llama a funciones, no al schema.
- ✅ `POST /voces`, con la puerta `preparar → decide → aplicar`.
- ✅ `t1_model` medido: `llama3.2:3b`, no `qwen3:4b`.
- ✅ Una alarma se guarda en **0,3 ms**, contra 300 ms de presupuesto.

**Lo que falta, y es lo que manda**: el prompt. 35.835 chars por paso, de los que
**19.083 son el schema de tools**. Es lo único que se paga en cada paso sin
condición, y la medición dice que de ahí sale el 62 % del tiempo.

**Falta además `para_hora`**: hoy «pon una alarma a las 7» **abstiene** y cae a T1,
porque `para` es `YYYY-MM-DD`. Ver `docs/decisiones/002`.

### F1 — Voz cortocircuito

Wakeword → STT → T0 → TTS. El camino más corto a algo que se nota, y el que
fuerza a resolver de verdad las tres cosas que todo lo demás hereda: latencia,
always-on y contención de GPU.

**Sale cuando**: «Aegis, ¿qué hora es» responde en **< 1 s con el modelo grande
ocupado**.

### F2 — Manos

Agenda, notas, música, mapas como T0 + intents. El asistente *hace* cosas, no
solo responde.

**Sale cuando**: «después del café con Ana» crea la alarma sin modelo.

### F3 — Memoria de ti

Preferencias, personas, decisiones. **Separada** de la memoria de runs: la
actual guarda épica de código. Datos distintos, retención distinta, privacidad
distinta. La semilla ya existe: `bridge/quien-eres.md` (3,2 KB).

**Sale cuando**: «¿qué sé de Ana?» responde sin que se lo digas dos veces.

### F4 — Ojos

Cámaras y visión. **Antes de esto hay una decisión que no es técnica**: grabar
personas en tu casa y reconocerlas es una cuestión de privacidad y legal, no de
ingeniería, y es de las pocas que no se pueden deshacer. Es lo que el
reconocimiento facial queda fuera del objetivo hasta que se tome esa decisión,
con su propio documento.

### F5 — Juicio

Iniciativa, subagentes, centro de inteligencia. **Lo último a propósito.**
La iniciativa **propone por la cola de aprobación que ya existe**, no con manos
libres: es la diferencia entre un asistente que avisa y uno que actúa solo.

**Sale cuando**: detecta un problema y propone una acción por la cola, sin
ejecutar nada por su cuenta.

### F6 — Omnipresencia

PC, móvil, reloj, casa. Requiere el hub *fail-safe* y el fin del «un bridge».

## 6. Lo que este objetivo NO incluye

Un objetivo sin exclusiones es una promesa que no se puede cumplir.

- **Reconocimiento facial**, hasta que se tome la decisión de privacidad.
- **Enviar audio, video o rostro a un tercero.** No es un requisito del objetivo;
  es una concesión, y no está concedida.
- **Pagos automáticos.** Nunca, sin excepción ni con permiso de antemano.

## 7. Cómo se decide lo siguiente

Una decisión de sistema no va por `/aegis`. Va por:

```
/objetivo <qué hay que decidir>
```

Ese comando inyecta los dos enfoques del repo —`producto.md` (¿esto sirve para
algo?) y `arquitectura.md` (¿por qué esta y no las otras?)—, exige un agente
crítico independiente, y escribe en `docs/decisiones/`.

Una unidad de código va por `/aegis <unidad>`, que pasa por el mismo crítico
antes de delegar nada.