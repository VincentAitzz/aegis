# Lecciones del proyecto `aegis`

Lo lee `bridge/app/autopilot.py` y se inyecta en el prompt de **todo** run con
`project: "aegis"`.

## Reglas transversales (aprendidas en otro proyecto, aplican aquí)

Son las que se pagaron en el portafolio y valen para cualquier repo. Están aquí
porque esta memoria es por proyecto, y un error no debería repetirse en otro.

### A-001 · Una verificación en verde NO es una entrega completa

- **Qué pasó**: se pidieron cinco entregables; el agente escribió uno, descartó
  cuatro en silencio y respondió "el check pasa". `tsc` estuvo verde siempre.
- **Regla**: un verificador comprueba que **lo que existe** sea consistente, no
  que no falte nada. **Cuenta los entregables uno por uno contra la spec**, antes
  de mirar cualquier resultado.
- **Detección**: un `grep -c` por entregable. Un 0 donde esperabas 1 es un fallo
  aunque todo esté verde.

### A-002 · El recuento que da el agente no es evidencia

- **Qué pasó**: respondió "4 enums creados" cuando había escrito 23. Los 23
  estaban bien; el recuento era falso.
- **Regla**: un modelo de 6 GB **no cuenta**. Cuenta tú contra la fuente.
  Y compara los **valores**, no solo los nombres: un nombre sin su valor es la
  mitad del trabajo.

### A-003 · Un tool call que devuelve el mismo error dos veces no se repite

- **Qué pasó**: `repo_verify` devolvió "no test files found" y el agente lo
  invocó cuatro veces seguidas, quemando un cuarto de los pasos. Nunca creó el
  archivo que faltaba.
- **Regla**: ante un resultado idéntico, **cambia de estrategia** (lee la ruta
  para ver si existe, escribe lo que falta). Dos repeticiones es el máximo.

### A-004 · Un archivo se escribe con saltos de línea

- **Qué pasó**: 46 declaraciones en una sola línea física. El typecheck dio
  verde: el formato no es un error de tipos.
- **Regla**: una declaración por línea. Este proyecto no tiene formateador que
  lojee, así que **nadie lo va a arreglar después**.
- **Detección**: `wc -l` menor que el número de declaraciones.

### A-005 · Un id no se deduce de un host

- **Qué pasó**: registré el proyecto de Neon `compra-unida` con el nombre de su
  **endpoint** (`young-waterfall-ace5iynr`) en vez del **id del proyecto**
  (`el-proyecto-de-neon-del-cliente`). Falló con 404/401, y el mensaje de Neon confunde
  alcance con credenciales inválidas.
- **Regla**: un valor copiado del host de una URL es una hipótesis, no un id.
  Se confirma contra la API antes de escribirlo en un registro.
- **Por qué importa**: un registro con un id inventado no falla visible: falla
  cuando alguien depende de él.

### A-006 · En Python, una declaración por línea y el `def` va con la función

- **Qué pasó**: al crear `app/projects.py` el agente escribió
  `workspace_candidates(workspace: str) -> list[Path]:` sin el `def`. El archivo
  no importaba, y la tool lo reportó como "creado".
- **Por qué pasó**: **el guardarraíl no validaba Python**. Solo miraba `.ts` y
  `.js` con esbuild; para `.py` devolvía "OK" sin comprobar nada. Un agujero del
  guardarraíl, no del modelo.
- **Regla**: en un archivo Python, toda función empieza con `def` en su propia
  línea, y los imports (empezando por `from pathlib import Path`) van arriba. Si
  escribes `algo(...) -> Tipo:` sin `def`, estás escribiendo un expression
  statement, no una función.
- **Ya está arreglado**: `_syntax_ok` valida `.py` con `ast.parse` desde el
  2026-09-27, y hay dos tests. Si vuelves a perder un `def`, la escritura se
  rechaza y te lo dice con el número de línea.

### A-007 · Un archivo no importa a sí mismo ni a quien lo usa

- **Qué pasó**: en `app/projects.py` el agente puso
  `from .mcp_ops import project, neon_entry`: un import circular (mcp_ops
  importa el registro, el registro importa mcp_ops) de nombres que además no
  existen allí.
- **Regla**: las dependencias van en un solo sentido. El registro (`projects.py`)
  no importa a nadie de la cadena; quien lo consume (`mcp_ops.py`, `neon.py`) lo
  importa. Y un módulo **nunca** importa lo que define.
- **Detección**: `python -c "import app.<modulo>"` — el import circular falla al
  instante, mucho antes de que algo lo use.

### A-008 · El agente escribe archivos completos; no edita quirúrgicamente

- **Qué pasó**: cinco unidades delegadas en este repo. Resultado medido:
  | Unidad | Qué pidió | Qué entregó |
  |---|---|---|
  | registro único (8 entregables) | crear `projects.py` + tool | **3 de 8**, y el archivo no importaba |
  | completar `projects.py` | un archivo, contenido exacto | **bien** (3 pasos), le faltó un import que pedí mal |
  | rewiring de `mcp_ops.py` | 3 cambios quirúrgicos en 668 líneas | **0 de 3**, 17 pasos, todos fallidos |
  | añadir función al final | reescribir el archivo con la función anexada | escritura **rechazada** por el guardarraíl |
  | crear `workspaces.py` (nuevo) | dos funciones descritas | dos intentos sin tool call válida |
- **La línea**: acierta cuando el trabajo es **un archivo nuevo o uno pequeño, con
  contenido especificado**. Falla cuando tiene que **adivinar un fragmento dentro
  de un archivo grande** (`patch_file` con `old` inventado: "aparece 8 veces",
  "no se encontró", una y otra vez) o cuando la unidad tiene **muchos entregables**.
- **Regla**: una unidad por entregable, y dale el contenido. Si tiene que editar
  algo grande, dale el `old` y el `new` exactos, o hazlo tú: el coste de un
  acierto a medias en el núcleo es mayor que el de hacerlo a mano.
- **Además**: confunde argumentos entre tools. Pasó `what=` (que es de
  `repo_verify`) a `aegis_write_file` en dos unidades distintas. Si se le pide una
  sola tool por paso, se le evitan las confusiones.

### A-009 · Una spec incompleta produce un fallo que parece del modelo

- **Qué pasó**: le pedí usar `field(default_factory=dict)` y enumeré los imports
  como "from dataclasses import dataclass". Ol mentioning `field` en la lista de
  imports. Escribió `field(...)` sin importarlo: `NameError` al importar.
- **Regla**: cuando pidas usar un símbolo, inclúyelo en los imports que pides. Y
  en general: **el fallo que parece del modelo puede ser de la spec**. Antes de
  corregir al agente, corrige la instrucción.

### A-010 · Sintaxis válida no es módulo importable

- **Qué pasó**: el guardarraíl valida con `ast.parse`, que ve `field(x)` sin
  definir como perfectamente válido. El fallo solo aparece al importar.
- **Ya está arreglado**: `bin/check-imports.py` importa todo el paquete y es el
  `check` del repo `aegis`. Antes de que lo tuviéramos, el agente escribía
  Python sin ninguna red detrás.

### A-011 · Escritura rechazada → reescribe. Verificar NO es el siguiente paso

- **Qué pasó**: unidad "crear `verifier.py`". Paso 1: `aegis_write_file` → el
  guardarraíl rechazó por sintaxis (`línea 25: expected ':'`) y borró el archivo.
  Paso 2: el modelo llamó `repo_verify(check, aegis)` → **OK, 15/15 módulos
  importan**. Pasos 3-5: dos reparaciones y nada. Entregó 0 de 1.
- **Las dos trampas**:
  1. `repo_verify` en verde **no prueba que el entregable exista**: el archivo se
     había borrado, y con él desapareció del conteo de módulos. Un verificador
     verde sobre un entregable ausente es un falso positivo.
  2. El rollback **borraba el contenido escrito**, así que nadie podía leer qué
     había escrito mal. Sin evidencia, el error se repite a ciegas.
- **Regla**: si una escritura sale `RECHAZADA`, el siguiente paso es **volver a
  escribir el archivo**, nunca verificar. Y antes de reescribir, lee la
  cuarentena: el guardarraíl deja el contenido en `bridge/data/quarantine/`.
- **Ya está arreglado**: la cuarentena existe y el mensaje dice dónde está.

### A-012 · Para Python, dale el esqueleto, no la especificación

- **Qué pasó**: con la interfaz descrita en prosa, el modelo generó la estructura
  y metió un error de sintaxis. Con `projects.py` (interfaz corta) acertó.
- **Por qué**: la estructura es lo único que el modelo puede hacer mal de forma
  silenciosa, y yo puedo escribirla gratis. El cuerpo de las funciones son
  sentencias, y las sentencias casi nunca tienen error de sintaxis.
- **Regla**: cuando el archivo sea Python y la interfaz importe, incluye en las
  instrucciones el esqueleto completo con `pass` en los cuerpos, y pide que solo
  rellene los cuerpos. "Escribe esto filling the bodies" en vez de "esto es lo
  que tiene que hacer".

### A-013 · El agente declaró haber creado un archivo que nunca escribió

- **Qué pasó**: tercer intento de la misma unidad. La escritura falló con
  `aegis_write_file() got an unexpected keyword argument 'what'` (el tercer vez
  que confunde el argumento `what` de `repo_verify`, con A-008 ya inyectada). El
  modelo no reintentó, y su respuesta final fue:

  > "El verificador ha confirmado que todos los módulos se importan correctamente.
  > Podemos concluir que el archivo `verifier.py` ha sido creado y verificado
  > exitosamente."

  No se había escrito nada. Nunca se escribió.
- **Por qué importa más que los otros errores**: los otros hacen que el agente
  falle. Este hace que el agente **mienta sobre su propio trabajo**, que es peor
  para un sistema autónomo: un asistente que reporta éxito sin evidencia no es
  inútil, es peligroso, porque parece que funciona.
- **Regla dura**: `answer` es una **opinión del modelo**, nunca evidencia. El
  mismo `repo_verify` en verde que él citaba como prueba era la prueba de lo
  contrario: el archivo no existía, por eso el check daba verde. Para saber si un
  entregable está, se mira el archivo, no la respuesta.
- **Consecuencia de diseño**: por eso existe `verifier.py` y por eso la puerta
  verifica con el comando, no preguntándole al modelo. Y por eso la Fase 1
  escribe artefactos en disco: si el plan no está en un archivo, no se puede
  auditar.

### A-014 · Siete reintentos idénticos, y la lección que no alcanzó

- **Qué pasó**: el segundo intento escribió 7 veces `aegis_write_file` con la
  misma ruta equivocada (`/RUTA/AL/REPO/...`: armó la ruta a mano y perdió el
  segmento `Workspace`), en 19 pasos, sin cambiar nunca de estrategia.
- **La lección A-011 estaba inyectada** y no evitó nada: la lección hablaba de
  reescribir tras un rechazo, y este modelo ni siquiera estava en el caso que
  describía. **Una lección solo previene el error que nombra.**
- **Corolario**: el antidoto no es una lección más, es la mecánica. Ya está:
  `verifier.es_repetido` cuenta la llamada idéntica que falló dos veces, y la
  puerta pone `stop: True` cuando no hay mejora. La lección sirve para entender;
  el mecanismo es lo que para.
- **Mejora del guardarraíl**: el mensaje de ruta ahora dice cuál era la correcta
  (`¿Querías decir: ...?`). Un error sin salida convierte una torpeza en un
  callejón; un error con la respuesta a un paso delata el hueco exacto.

---

## Reglas de este repo

- **Una fuente de verdad**: los proyectos viven en `app/projects.py` (raíz,
  verificador, base Neon, permisos). `mcp_ops.py` y `neon.py` leen de ahí; si
  aparece un segundo `PROJECTS` en otro archivo, es un bug.
- **Verificar antes de afirmar**: `repo_verify(check, aegis)` para Python,
  `repo_verify(check, portafolio)` para tipos. Un verificador en verde no prueba
  que la entrega esté completa: cuenta los entregables (A-001).

---

## Registro de correcciones

| fecha | archivo | error | lección |
|---|---|---|---|
| 2026-09-27 | `app/projects.py` (agente) | `def` perdido → el archivo no importaba; el guardarraíl no validaba Python | A-006 |
| 2026-09-27 | `app/projects.py` (agente) | `from .mcp_ops import ...`: import circular de nombres inexistentes | A-007 |
| 2026-09-27 | `app/projects.py` (agente) | repitió el id de endpoint como id de proyecto, con A-005 ya inyectada | A-005 |
| 2026-09-27 | unidad "registro único" (agente) | entregó 3 de 8 entregables y reportó éxito | A-001 |
| 2026-09-27 | unidad "registro único" (agente) | llamó `repo_verify` 4 veces con A-003 inyectada | A-003 |
| 2026-09-27 | unidad "completar projects.py" (**spec**) | le pedí `field` sin importarlo: spec incompleta | A-009 |
| 2026-09-27 | `app/projects.py` (agente) | `neon_entry` indexaba el dataclass como dict | A-006 |
| 2026-09-27 | unidad "rewiring mcp_ops" (agente) | 17 pasos, 0 cambios: adivina fragmentos en un archivo de 668 líneas | A-008 |
| 2026-09-27 | 2 unidades (agente) | pasó `what=` de `repo_verify` a `aegis_write_file` | A-008 |
| 2026-09-27 | `app/workspaces.py` (**yo**) | `workspace_candidates` no buscaba proyectos a nivel 1; lo encontró un test | — |
| 2026-09-27 | `app/projects.py` (**yo**) | puse el id de endpoint de compra-unida como id de proyecto; detectado al listar la organización | A-005 |
| 2026-09-27 | unidad "crear verifier.py" (agente) | escritura rechazada por sintaxis y después verificó en vez de reescribir: `repo_verify` dio verde con el archivo borrado | A-011 |
| 2026-09-27 | rollback de sintaxis (**yo**) | borraba el contenido rechazado, dejando al agente sin evidencia del error | A-011 |
| 2026-09-27 | unidad "crear verifier.py" (**spec**) | describí la interfaz en prosa y el modelo generó la estructura con un error de sintaxis | A-012 |
| 2026-09-27 | unidad "crear verifier.py" (agente) | 7 escrituras idénticas con una ruta a mano mal armada, en 19 pasos | A-014 |
| 2026-09-27 | unidad "crear verifier.py" (agente) | declaró el archivo "creado y verificado" sin haberlo escrito nunca | A-013 |
| 2026-09-27 | `app/verifier.py` (**yo**) | `ERROR_RE` sin `IGNORECASE` no contaba los `ERROR:` de los compiladores | — |
| 2026-09-27 | `tests/test_verifier.py` (**yo**) | mock con `root` como string en vez de `Path` | — |


