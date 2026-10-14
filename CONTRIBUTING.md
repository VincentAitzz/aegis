# Cómo contribuir

Este repo tiene una forma rara de trabajar, y conviene entenderla antes de
mandar nada. No es purismo: es que **un modelo de 7 GB se equivoca con
sistemática**, y el diseño entero está para que eso no se note.

## Lo primero: lee la lección

`bridge/lessons/aegis.md` son 121 lecciones sobre lo que salió mal. Están en
español y son largas.

No hace falta leerlas todas. Abre una issue o una PR y di qué toca; ahí está la
lección más relevante, y muchas veces esa lección dice «esto ya se rompió dos
veces y la forma de arreglarlo es otra».

La lección con el bloque `> Aplica cuando: …` es la que aplica a tu caso. Las que
no lo declaran usan la primera frase de su «qué pasó», y **no se inventa uno**: un
disparador inventado suena específico y no sirve para decidir nada.

## Puesta en marcha

```bash
git clone <este repo> && cd aegis
bash infra/setup.sh              # venv, .env, comprobaciones
```

`setup.sh` es idempotente: se puede volver a ejecutar sin romper nada. Te dice
qué falta en vez de fallar con un error de Python.

## Los dos comandos que importan

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -q   # ~700 tests
cd bridge && .venv/bin/python bin/check-imports.py               # 28 módulos
```

Los dos tienen que estar en verde. Si tocas `mobile/`, además:

```bash
cd mobile && flutter analyze && flutter test                     # 0 issues, verde
```

**Sobre `flutter analyze`:** el criterio es **cero issues**, no «no más de N». Se
midió antes de empezar y es cero. Si un cambio tuyo lo sube, el problema es tuyo
o ya estaba: en ambos casos hay que bajarlo.

## Cómo contributes, de verdad

Hay dos caminos, y no son intercambiables.

### 1. Tú escribes el código

Es lo normal para una PR. Escribe, pon tests, pon la lección.

### 2. Se lo dices a Aegis

Aegis puede escribir en este repo. **No** lo lances a pelo sobre `main` desde el
móvil; es la puerta de nivel 3 y con un trabajo de tamaño real se va a quedar
sin pasos.

La forma que funciona es: un `POST /autopilot` con las reglas y el encargo, desde
la máquina. Las reglas van en `instructions` y la tarea en `prompt`.

Antes de delegar algo, lee `bridge/lessons/aegis.md`. Si vas a repetir un
trabajo, la lección explica dónde se equivocó la última vez.

## Las tres reglas que no se saltan

1. **Una corrección sin lección escrita es trabajo incompleto.** Un arreglo que
   solo vive en el commit no lo ve nunca el agente: la próxima vez lo repite.
   Añade la lección a `bridge/lessons/aegis.md` en la misma PR.
2. **El veredicto sale de la traza, no de la respuesta del modelo.** Si añades
   una tool, haz que su evidencia llegue a la traza. Si no, Aegis puede
   reportar éxito sin haber hecho nada, que es el peor fallo posible aquí.
3. **Los guardarraíles de `app/mcp_ops.py` no se debilitan.** Si uno bloquea
   algo legítimo, se **amplía**. Nunca se desactiva. Y el motivo de cada veto va
   en el mensaje, para que quien lo recibe sepa qué hacer.

## Estilo

- Comentarios que explican **por qué**, no **qué**. El código ya dice qué.
- Si un comentario dice por qué, que sea verdad y que siga siendo verdad: si el
  problema se arregla, se actualiza el comentario.
- Español en el código, los comentarios y los mensajes al usuario. Los nombres de
  símbolo, en inglés.
- Una idea por PR. «De paso» es como se cuela lo que nadie ha revisado.

## Lo que NO va al repo

Hay cosas que este proyecto usa y no versiona, a propósito:

| Qué | Por qué |
|---|---|
| `bridge/quien-eres.md` | Cómo quieres que te hable. Es tuyo. La plantilla sí está. |
| `bridge/fichas/{proyecto}.md` | Ficha técnica de tus proyectos: es información de tu negocio |
| `bridge/registro/*.json` | Los mismos proyectos por su nombre real |
| `bridge/lessons/{otro}.md` | Lecciones de proyectos que no son este repo |
| `bridge/fichas-privadas/` | La parte comercial: quién es el cliente y qué se le cobran |
| `bridge/.env`, `bridge/data/` | Secretos, logs, memoria y SQLite |

Todo eso está en `.gitignore`, y el `.gitignore` es parte del diseño: **un
`.gitignore` demasiado ancho se come código sin avisar** (lección A-017), y uno
demasiado estrecho manda tu `.env` a internet. Si añades algo nuevo y no sabes
dónde va, pregunta antes de hacer `git add -A`.

## Si algo no cuadra

Un invariante de este repo es que **la documentación que miente es un defecto**.
Si encuentras que el README, el runbook o un comentario no dicen la verdad,
eso es una PR tan válida como cualquier otra. Preferiblemente con el motivo, no
solo el síntoma: la mitad de las veces el síntoma está en el fichero equivocado.