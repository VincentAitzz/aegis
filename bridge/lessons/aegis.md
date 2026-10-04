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

> Aplica cuando: cuando vas a decir que has hecho N cosas

- **Qué pasó**: respondió "4 enums creados" cuando había escrito 23. Los 23
  estaban bien; el recuento era falso.
- **Regla**: un modelo de 6 GB **no cuenta**. Cuenta tú contra la fuente.
  Y compara los **valores**, no solo los nombres: un nombre sin su valor es la
  mitad del trabajo.

### A-003 · Un tool call que devuelve el mismo error dos veces no se repite

> Aplica cuando: cuando una tool devuelve un error que ya habías visto

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

> Aplica cuando: cuando te toque adivinar un id, un host o una URL

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

> Aplica cuando: cuando te pidan código sin decirte la firma exacta

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

> Aplica cuando: cuando tu respuesta diga que has escrito algo

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

> Aplica cuando: cuando vas a repetir una llamada que ya ha fallado dos veces

- **Qué pasó**: el segundo intento escribió 7 veces `aegis_write_file` con la
  misma ruta equivocada (`/RUTA/AL/REPO/...`: armó la ruta a mano y perdió el
  segmento `Workspace`), en 19 pasos, sin cambiar nunca de estrategia.
- **La lección A-011 estaba inyectada** y no evitó nada: la lección hablaba de
  reescribir tras un rechazo, y este modelo ni siquiera estava en el caso que
  describía. **Una lección solo previene el error que nombra.**
- **Corolario**: el antidoto no es una lección más, es la mecánica. La lección
  sirve para entender; el mecanismo es lo que para.
- **Corrección de esta misma lección, 2026-10-04 (A-079)**: aquí se escribió
  «Ya está: `verifier.es_repetido` cuenta la llamada idéntica que falló dos
  veces». **No estaba.** La función existía, con su docstring prometiendo lo que
  hace, y `grep` la encontraba **sin una sola llamada** en `app/`. Una lección que
  declara montado un mecanismo que no lo está es peor que una lección que no
  habla de él: el que la lee deja de comprobar. Hoy `es_repetido` se usa en la
  puerta del verificador, y `autonomy.empeora` compara la línea base con el
  final del run —los dos mecanismos sin usar que había—.
  **Regla que sale de aquí**: antes de escribir «ya está», `grep` la función y
  mira si la llaman. Una afirmación de que algo está montado es un commit, y se
  comprueba como un commit.
- **Mejora del guardarraíl**: el mensaje de ruta ahora dice cuál era la correcta
  (`¿Querías decir: ...?`). Un error sin salida convierte una torpeza en un
  callejón; un error con la respuesta a un paso delata el hueco exacto.

### A-015 · El agente redacta documentos que inventan la API

- **Qué pasó**: la demostración de la puerta pidió «15 líneas que expliquen qué
  hace `verifier.py`». Lo escribió, la puerta dio **verde** (el verificador de
  este repo es importar el paquete, y el archivo era markdown), y el contenido
  era ficción: citaba `project.verifier`, `from app.neon import project_neon`,
  `from db_query import db_query`, una función `verify_project()` que no existe, y
  afirmaba que el módulo «se ejecuta periódicamente».
- **La lección de fondo**: **escribir y documentar no es lo mismo que saber.**
  El modelo es capaz de producir un texto plausible sobre código que nunca leyó.
  Un verificador que solo comprueba que el archivo exista no detecta eso.
- **Regla**: no dejes que el agente documente el código que no ha leído. Si
  documenta, cita `archivo:línea` y cada símbolo que mencione tiene que existir.
  El doc que entregó se reemplazó a mano por uno que sí cita las funciones.

### A-016 · Una tool que falla en silencio es peor que una tool ausente

> Aplica cuando: cuando una tool te devuelva texto en vez de un fallo

- **Qué pasó** (medido el 2026-09-30): `POST /tasks` respondió `status: completed`
  y `final_text: "OK"` en **5 de 5** runs en los que la tool **nunca se ejecutó**.
  Hermes rechazaba la llamada con `tool_call requires 'calls'`, el modelo
  respondía "OK", y el bridge guardaba el episodio como `outcome: success`.
  18 tool_calls emitidos, 17 rechazados, 0 tools reales.
- **Por qué no lo detectó nadie**: el modelo **sí** emitía `tool_calls`
  estructurados. Fallaba el *envoltorio*, no el modelo. Y el run se reportaba
  como completo, así que ningún test, ni el health, ni la app mostraban nada raro.
- **La lección de fondo**: un `success` sin evidencia de ejecución es una
  mentira que se acumula. Y al acumularse se vuelve **la causa** del fallo.

#### El bucle (la mitad que no se vio hasta el final)

Quitar el diferido de `tool_search` arregló la primera capa, pero `/tasks` siguió
en **0/8**. La segunda capa era la propia memoria contaminada:

1. `hooks.py` marcaba `success` a cualquier `task.done`, sin mirar la traza.
2. Esos episodios entraban a memoria con `final_text = "OK"`.
3. El `recall` los inyectaba al run siguiente bajo el rótulo
   **"Episodios similares resueltos antes"** → `[success] … SOLUCIÓN: OK`.
4. El modelo leía que la respuesta *era* "OK" y contestaba **sin llamar a nada**.
5. No había tool → `task.done` → otro falso éxito. Vuelta a empezar.

Ablación sobre el prompt real que Hermes manda (n=8 cada una):

| variante del system prompt | tool calls |
|---|---|
| completo, con 3 episodios falsos | **0/8** |
| completo **sin** el bloque de memoria | **7/8** |
| memoria con encabezado pero 0 episodios | **6/8** |
| mínimo (69 chars) | **8/8** |

**Tres episodios falsos bajan el tool calling de 7/8 a 0/8.** Y con la memoria
limpia el mismo código dio **16/16 en dos rondas**, sin falsos éxitos.

#### Los callejones que se recorrieron antes de llegar

- **El tamaño del prompt no era el problema.** Recortar los 5 bloques de guidance
  dejó 2.280 chars y siguió en **0/8**, porque el bloque de memoria seguía ahí.
- **El nº de tools tampoco**: 15 tools y 23 tools daban lo mismo.
- **El prefijo `mcp__` tampoco**: 10/10 con nombre corto, 9/10 con el largo (n=10).
- **Meter una instrucción fuerte en `instructions` tampoco**: 0/8.
- Los tres primeros Loeb se habrían "arreglado" con un recorte de prompt, y el
  fallo habría vuelto a las 24 h sin entenderse.

- **Regla**: el veredicto de un run sale de la **traza** (¿hubo una tool con
  `ok`?), nunca del texto del modelo. `final_text` es la opinión del agente sobre
  su propio trabajo. Un run sin tool ejecutada no es `success`: es
  `sin_evidencia`.
- **Regla**: la memoria solo se inyecta si el episodio **se resolvió de verdad**.
  `recall` devuelve lo más cercano sin mirar el `outcome` y lo rotula "resueltos
  antes": un fallo presentado como solución es instrucción contraria, y el
  modelo la copia. Al prompt solo suben los `success` con tools nombradas.
- **Corolario para el médico**: si el síntoma es "parece que funciona pero no
  hace nada", **lee la traza, no el veredicto**. Y cuando el arreglo no se sostiene,
  **mide por capas en vez de parchear la primera que se vea**: aquí había dos
  capas y cada una tapaba a la siguiente.
- **Corolario de método**: dos instrumentos mentirosos en el mismo día.
  - `probe-toolcall.sh` dio "fiable" midiendo **una** tool con un prompt mínimo:
    no puede ver este fallo, porque este fallo necesita el prompt real.
  - El medidor de `/tasks` dio **0/8** porque `/tasks` es **async** (devuelve
    `status: started`); esperaba 1,5 s y leía una traza que aún no existía.
    **Un 0/8 sin verificar el instrumento no es un dato.**
- **Corolario de diseño**: el criterio de éxito de un plan tiene que ser
  **comprobable por máquina** (A-016). «Escribir documentación» no lo es;
  «importar el paquete y que la puerta dé verde» sí.

### A-017 · Un `.gitignore` demasiado ancho se come código sin avisar

- **Qué pasó** (2026-09-30): `.gitignore` tenía `data/` sin anclar, para excluir
  el runtime del bridge. Ese patrón también matchea **`mobile/lib/data/`**, que es
  la capa de datos de la app Flutter. Resultado: `agent_models.dart` y
  `agent_repository_impl.dart` **nunca estuvieron versionados**, y el móvil **no
  compilaba desde un clone limpio**. Nadie lo notó porque el árbol de trabajo
  local sí tenía los ficheros, así que `flutter analyze` pasaba en verde.
- **La lección de fondo**: un patrón de exclusión sin ancla no es una
  configuración, es un **oráculo sobre qué existe**. Todo lo que cae bajo ese
  nombre desaparece del repo sin dejar rastro, y el síntoma (no compila) aparece
  lejos de la causa (una línea de `.gitignore`).
- **Regla**: los patrones de exclusión se anclan al path real (`/bridge/data/`),
  y **se comprueba con `git check-ignore -v`** que lo que quieres excluir sí y lo
  que no, no.
- **Corolario de método**: `flutter analyze` en verde **no** demuestra que el
  repo esté sano: sólo demuestra que *este* directorio está sano. La prueba de
  que un fichero está versionado es `git ls-files`, no el analizador.
- **Corolario para el médico**: si algo "funciona en mi máquina" y además toca
  `data/`, `build/`, `logs/` o `tmp/` en el nombre, **mira `git status` antes de
  tocar el código**: puede que el fichero no exista para el resto del mundo.

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
| 2026-09-27 | `app/autopilot.py` (**yo**) | respuesta vacía del modelo terminaba el run y se reportaba como "agotó los pasos" | — |
| 2026-09-27 | `bridge/docs/verificador.md` (agente) | inventó la API: `project_neon`, `verify_project()`, "se ejecuta periódicamente" | A-015 |
| 2026-09-30 | `~/.hermes/config.yaml` (**yo**) | `tools.tool_search` sin definir difería las 13 tools MCP tras el meta-tool `tool_call`; un 7B no construye el array anidado → 0/5 tools ejecutadas | A-016 |
| 2026-09-30 | `~/.hermes/config.yaml` (**yo**) | `platform_toolsets.api_server` con nombres de servidor donde se esperan toolsets: dejó **todas** las configurables en `enabled=False` | A-016 |
| 2026-09-30 | `app/hooks.py` (**yo**) | grababa `outcome: success` con solo mirar `task.done`, sin evidencia de tool: 5 falsos éxitos a memoria | A-016 |
| 2026-09-30 | `app/memory/__init__.py` (**yo**) | `recall` devolvía lo más cercano sin mirar `outcome` y lo rotulaba "Episodios similares resueltos antes": enseñarle un fallo como solución | A-016 |
| 2026-09-30 | el bucle completo (**yo**) | el falso éxito alimentaba el recall, el recall enseñaba "responde OK sin tool", y el run sin tool volvía a grabarse como éxito | A-016 |
| 2026-09-30 | `probe-toolcall.sh` (**spec**) | la sonda (1 tool, 60 tokens) dio "fiable" mientras el flujo real fallaba 0/8: medía otra condición | A-016 |
| 2026-09-30 | el medidor de `/tasks` (**yo**) | dio 0/8 porque `/tasks` es async y yo esperaba 1,5 s: un 0 sin verificar el instrumento no es un dato | A-016 |
| 2026-09-30 | `infra/docker/` (**arquitectura**) | sandbox por contenedor inalcanzable (`terminal` nunca habilitada) y con `/workspace` vacío: 683 MB y un contenedor por run a cambio de nada | A-016 |
| 2026-09-30 | `app/autopilot.py` (**yo**) | `repo_verify(repo={"type":"portafolio"})` — escalar envuelto en objeto — reventaba con `TypeError` y tumbaba el run | A-016 |
| 2026-09-30 | `POST /fichas` (**yo**) | el modelo se comió los `---` del frontmatter al 'copiar' la ficha: escritura exacta va de la persona al bridge | A-019 |
| 2026-09-30 | `install_apk` (**yo**) | instalaba y ABRÍA la app en el teléfono sin puerta ni aviso, y el destino lo elegía solo | A-020 |
| 2026-09-30 | `app/fichas.py` (**yo**) | el filtro de comentarios era de una línea y las subsecciones `###` rellenaban su `##`: la puerta se abría sola | A-018 |
| 2026-09-30 | `tests/test_deploy.py` (**yo**) | `ESTADO.limpiar()` escribía en el fichero real: correr los tests borraba la aprobación del usuario (un 404 del móvil lo delató) | A-021 |
| 2026-09-30 | `app/mcp_ops.py` (**yo**) | un único `app-debug.apk` para emulador y teléfono, y `api_host` del teléfono con la IP del propio teléfono de reserva: dos fallos silenciosos | A-022 |
| 2026-09-30 | `app/deploy.py` (**yo**) | la aprobación se daba desde la app que exigía aprobación: instalar por primera vez era imposible | A-023 |
| 2026-09-30 | `pubspec.yaml` + `flutter_launcher_icons` (**yo**) | `android:` es el nombre del fichero y `image_path` no se toma como foreground: generó los cinco PNG y el ícono no cambió | A-024 |
| 2026-09-30 | `adaptive_icon_foreground_inset: 12` (**yo**) | la máscara del lanzador le cortaba el cráneo; 12 parecía correcto y no lo era | A-024 |
| 2026-09-30 | `app/mcp_ops.py` (**yo**) | la excepción de "primera vez" estaba en `instalar_en_telefono`, que `install_apk` nunca llega a llamar: en un teléfono nuevo Aegis pedía una aprobación imposible | A-025 |
| 2026-09-30 | `api_host_para` (**yo**) | devolvía una IP sin comprobar que el teléfono la alcanzara: Tailscale sin sesión y ufw bloqueando la LAN | A-026 |
| 2026-09-30 | varios ficheros (**yo**) | caracteres de alfabetos ajenos dentro de palabras, en comentarios y en `lessons/`: se colaron tres veces en un trabajo | A-027 |
| 2026-09-30 | `.gitignore` (**yo**) | `data/` sin ancla también excluía `mobile/lib/data/`: la capa de datos de la app nunca estuvo versionada y el móvil no compilaba desde un clone | A-017 |
| 2026-10-01 | `app/mcp_ops.py` (**yo**) | `current_brand()` leía el path viejo de la paleta: al renombrarla devolvía `<no existe el tema>`, que no es el centinela, y la comprobación de `build_apk` pasaba sin comprobar nada | A-028 |
| 2026-10-01 | `app/mcp_ops.py` (**yo**) | el centinela era el magenta original y el tema llevaba días en verde: la puerta llevaba tiempo sin bloquear nada | A-028 |
| 2026-10-01 | `app/deploy.py` (**yo**) | `pedir_deploy()` avisaba al teléfono real en cada `install_apk` sin aprobación, y el agente reintenta: el móvil se llenaba de avisos sobre una decisión viva | A-029 |
| 2026-10-01 | `tests/test_deploy.py` (**yo**) | un test que miraba el texto del aviso en vez del serial de adb habría pasado con el aviso yendo al teléfono | A-029 |
| 2026-10-01 | `tests/test_autopilot.py` (**yo**) | usó `Color()` para romper un archivo: es Dart válido, el guardarraíl lo aceptó y dejó `Color()` en la paleta de verdad | A-030 |
| 2026-10-01 | `mobile/lib/core/widgets/boot_screen.dart` (**yo**) | el arranque imprimía `handshake ok` y `auth ok` sin haber comprobado nada: A-016 en la cara del usuario | A-031 |
| 2026-10-01 | `mobile/lib/presentation/shell/aegis_section.dart` (**yo**) | se colaron ideogramas en un comentario; el test de texto los cazó antes del commit, que es lo que se quería de A-027 | A-027 |
| 2026-10-01 | `app/autonomy.py` (**yo**) | el token atado al `run_id` no se podía canjear: aprobar y relanzar crea otro run. La fila decía "aprobada" y el paso no avanzaba nunca | A-033 |
| 2026-10-01 | `app/main.py` (**yo**) | añadí la caída a disco sin que **nadie escribiera** el JSONL del autopilot: la lectura existía y la escritura no | A-034 |
| 2026-10-01 | `app/main.py` (**yo**) | `task.max_steps` como evento terminal (no está en la taxonomía) y contando solo `tool.started` (solo lo emite Hermes): la mitad de los runs salían con cero pasos | A-034 |
| 2026-10-01 | `app/autonomy.py` (**yo**) | "probado con la función `decide`" confundido con "el círculo cierra": el `AutopilotIn` del servidor no tenía campo `token` | A-033 |
| 2026-10-01 | `app/autonomy.py` (**yo**) | el criterio de autonomía fue "¿tiene ficha?"; tres proyectos no tienen verificador, así que no hay contra qué comprobar | A-035 |
| 2026-10-01 | `app/autonomy.py` (**yo**) | la denegación guardaba estado pero no motivo, y el motivo no se inyectaba: era un registro del bridge, no una memoria del agente | A-037 |
| 2026-10-01 | `app/mcp_ops.py` (**yo**) | `build_apk` leía el token del `settings` del bridge desde el proceso del MCP, donde vale `""`: APK sin token que abre bien y falla con 401 en cuatro secciones | A-038 |



### A-018 · Una puerta que se abre sola no es una puerta

- **Qué pasó** (2026-09-30): se construyó la puerta de fichas (no se escribe en
  un proyecto que no se sabe qué es) y **pasó los tests**. Dos agujeros la
  abrían, y los dos aparecieron el mismo día:
  1. El filtro de comentarios HTML era de **una sola línea**. Los comentarios
     largos se escriben en varias, así que a partir de la segunda línea el
     texto se leía como contenido y la sección contaba como escrita.
  2. Una sección `##` cuyo único texto estaba en subsecciones `###` contaba como
     escrita. Bastaba crear un `###` para saltarse el control.
- **Por qué importa más de lo que parece**: el primer agujero se detectó
  **usando la puerta**, no leyendo el código. Escribí una ficha con "pendiente"
  en comentarios, la puerta la dejó pasar, y un 7B iba a trabajar sobre una
  ficha que no decía nada. Es A-016 en otro sitio: un control que reporta verde
  sin comprobar lo que dice comprobar.
- **La lección de fondo**: **una validación nueva es código no probado hasta que
  tiene un caso que la hace fallar.** Los tests que escribí probaban lo que yo
  ya sabía. El agujero estaba en el input que yo no se me había ocurrido.
- **Regla**: por cada guardarraíl, un test con el caso **peor**, no solo el
  feliz. Para la puerta: comentario multilínea, subsección, marcador, plantilla
  recién creada, sección vacía. Y probarlos **contra la puerta real**, no contra
  la función auxiliar.
- **Corolario**: la puerta no excluye la lectura. Entender un proyecto es leerlo,
  y una puerta que cierra la lectura solo produce resistencia sin.


### A-019 · Si el texto lo aprueba una persona, que no lo escriba un modelo

- **Qué pasó** (2026-09-30): al probar el flujo de fichas desde el móvil, el
  diseño era "el agente propone la ficha, la persona la revisa, y autopilot la
  escribe tal cual". Se le pasó el texto a autopilot con la instrucción de
  copiarlo **exactamente**, y no lo hizo: se **comió los `---` del frontmatter**
  y le añadió un `## Tools` al final.
- **Por qué fue grave**: los `---` son lo que declara el `kind`. Sin ellos la
  ficha queda sin tipo, la puerta responde "tipo inválido", y el trabajo
  aparentemente hecho no abre nada. Un `write` que devuelve éxito y deja el archivo
  inservible es peor que un `write` que falla: **no se nota hasta el siguiente
  intento**.
- **La lección de fondo**: **toda copia de texto por un modelo es una pérdida de
  fidelity**. Da igual cuántas veces se lo pidas. Si un texto tiene que quedar
  *igual*, tiene que escribirlo algo que no lo reescriba.
- **Regla**: los tres sitios donde el dato tiene que ser exacto —el texto de una
  ficha, un monto, un identificador— van **de la persona al bridge, sin pasar por
  el modelo**. El modelo redacta y propone; lo que la persona aprobó se guarda.
- **Corolario**: al integrar con el móvil, probar **el camino completo** y no el
  trayecto parcial. Aquí el fallo no estaba en el modelo ni en la puerta: estaba
  en haber encadenado "texto humano → modelo → archivo", y no se vio hasta que
  el archivo se leyó.


### A-020 · Un sistema que interrumpe sin avisar también está roto

> Aplica cuando: cuando una acción tuya tarde más de lo que el usuario espera

- **Qué pasó** (2026-09-30): `install_apk` resolvía el galaxy por mDNS, lo
  instalaba **y abría la app encima** (`launch=True` por defecto). Ninguna
  puerta, ningún aviso. Una prueba de Aegis te podía interrumpir a media cosa, y
  Aegis no lo registraba como nada.
- **Por qué es la misma lección que A-016**: el síntoma es distinto —aquí no se
  reportaba un falso éxito, se reportaba un éxito sobre algo que el
  usuario no pidió—. La causa es la misma: **una acción que el usuario tiene que
  soportar se estaba haciendo porque técnicamente se podía**. Que algo se pueda ejecutar no es
  permiso para ejecutarlo.
- **La regla**: **el teléfono no se elige por descarte**. `resolver()` ya no
  tiene un valor por defecto que lo alcance; el destino se nombra. Y nombrar el
  teléfono no basta: hace falta una **autorización de un solo uso**, granted en el
  móvil, más una verificación que la puerta **corre ella misma** —analyze, tests y
  un humo en el emulador— porque aceptar el dicho del agente sería repetir A-016.
- **El detalle que casi se cuela**: el MCP de `aegis-ops` corre como **proceso
  aparte** del bridge FastAPI. Un registro de "de dónde vino esta llamada" en
  memoria habría estado siempre vacío desde el lado del MCP, y el humo habría
  fallado siempre — un fallo que solo se ve con todo desplegado. Va por HTTP.
- **Corolario sobre identidad en la frontera**: el emulador y el teléfono llegan
  los dos por `adb reverse` y los dos se ven como `127.0.0.1` en el log. Sin una
  cabecera que diga de dónde viene cada llamada, "probar en el emulador" y "tocar
  el teléfono" son la misma línea en el log, y no hay forma de probar que la
  prueba pasó por el sitio correcto.
- **Corolario de método**: `adb` anuncia el mismo teléfono por mDNS **dos veces**
  (marca el duplicado con ` (2)`, y el contador va en medio del serial). Contarlos
  dos hace que la tool diga que hay dos teléfonos. Parsear `adb devices` a mano
  es una fuente de bugs garantizada.

### A-021 · Correr los tests borraba la autorización del usuario

- **Qué pasó** (2026-09-30): la suite de `bridge/tests/test_deploy.py` llamaba
  `ESTADO.limpiar()` en `setUp`, y `ESTADO` es un singleton cuya `RUTA` es la
  real: `bridge/data/deploy.json`. O sea, **`unittest` borraba las peticiones de
  despliegue de verdad**. Se Lakovidió porque entre crear la petición y denegarla
  desde el móvil yo corrí la suite: el móvil respondió 404 y parecía un fallo de
  la puerta.
- **El motivo de fondo**: el estado existe para vivir unos minutos entre el MCP y
  el bridge. Un artefacto de test no puede escribir en el estado de producción, ni
  para limpiarlo.
- **Cómo se arregla**: cada test mueve `ESTADO.RUTA` a un `tempfile`. Comprobado:
  petición real creada, suite entera pasada, petición viva.
- **Corolario**: cuando dos procesos comparten estado en un fichero, "escribir en
  el fichero real" es una decisión de diseño, no un detalle, y hay que mirarla en
  los `setUp`.


### A-022 · Un solo APK para dos destinos: dos fallos silenciosos de un plumazo

- **Qué pasó** (2026-09-30): había un único `build/.../app-debug.apk` para el
  emulador y para el teléfono, y `api_host_para("telefono")` devolvía de reserva
  `100.101.102.103`... que es la IP **del teléfono**, no la del bridge
  (`100.101.102.100`).
- **Por qué es grave**: los dos fallos son silenciosos. Compilar para el teléfono
  dejaba en el emulador una app que apunta a la IP de la tailnet y no ve nada;
  instalar en el teléfono el APK del emulador lo dejaba en `localhost`. La app
  abre, muestra su pantalla, y no se entera de nada. Ninguno rompe, y los dos son
  indistinguibles de "funciona".
- **Cómo se arregla**: un APK por destino, con el destino en el nombre
  (`app-debug-emulador.apk`, `app-debug-telefono.apk`), y `build_apk` mueve ahí la
  salida. La puerta instala el del teléfono y el humo prueba el del emulador. Y
  para la IP: se pregunta a `tailscale ip -4`, o se exporta
  `AEGIS_BRIDGE_TAILNET_IP`; si no se puede saber, se dice, no se devuelve algo
  plausible.
- **Corolario**: un valor de reserva "razonable" en una dirección es más peligroso
  que ninguna: convierte un error visible en un silencio.


### A-023 · El botón de aprobación vivía dentro de lo que había que aprobar

> Aplica cuando: cuando pongas una puerta detrás de algo que aún no está instalado

- **Qué pasó** (2026-09-30): `install_apk(target="telefono")` exigía una
  autorización que se daba **pulsando un botón de la app del teléfono**. Sin la
  app instalada no hay botón: para instalar había que aprobar, y para aprobar
  había que tenerla instalada. Un deadlock, que solo no se notaba porque ya había
  un APK viejo en el teléfono.
- **Qué protege de verdad la puerta**: no interrumpirte **mientras usas la app**. Un
  paquete que no está instalado no interrumpe nada.
- **Cómo se arregla**: la **primera** instalación no pide autorización —se exige lo
  de siempre (destino explícito, analyze, tests, humo) y **nunca** se abre la app.
  En cuanto el paquete está presente, la puerta vuelve a ser completa.
- **Corolario**: al poner una puerta, preguntar "¿se puede pasar por ella la
  primera vez?". Si la respuesta es no, no es una puerta, es un muro.

### A-024 · Dos formas de cambiar el ícono y no cambiarlo

- **Qué pasó** (2026-09-30): al meter el logo de Aegis en la app, `flutter_launcher_icons` dio `✓ Successfully generated launcher icons` y el ícono **seguía siendo el de la plantilla de Flutter**. Dos motivos, los dos silenciosos:
  1. `android: "launcher_icon"` es el **nombre del fichero** que se genera, no un booleano. El manifest apunta a `@mipmap/ic_launcher`, así que seednesdaygeneraron cinco PNG que nadie miraba.
  2. Sin `adaptive_icon_foreground`, **no se genera nada adaptativo** y el README lo dice en una nota: `image_path` no se toma como foreground. Faltaba el `mipmap-anydpi-v26/`, que es justo lo que evita que Android 12+ recorte el ícono.
- **Cómo se detecta**: `aapt2 dump badging app.apk | grep application-icon`. Si sale `res/mipmap-xxxhdpi/ic_launcher.png` en vez de `res/mipmap-anydpi-v26/ic_launcher.xml`, el ícono no es adaptativo y da igual cuántas veces lo regeneres.
- **El inset hay que mirarlo, no razonarlo**: se puso 12 porque "el 66% central suena bien" y la máscara del lanzador **le cortaba los temporales y la mandíbula**. Se comprobó renderizando la máscara circular con 12, 18 y 24: 18 es el primero en que la silueta cabe entera. Un número que parece de correctitud no se verifica solo.
- **El emulador no puede verificar el ícono**: el AVD `aegis-a17` no tiene lanzador, usa `com.android.fakesystemapp/launcher.EmptyHomeActivity`. La pantalla de inicio sale negra. "La app se prueba en el emulador" es cierto para la UI y **falso para el ícono del lanzador**: eso solo se ve en el teléfono.
- **Corolario**: un generador que dice "generado" dice que escribió ficheros, no que cambió lo que se ve. Y un icono solo se juzga **después** de que el sistema lo enmascare.

### A-025 · Dos decisiones en dos sitios: una es código muerto

- **Qué pasó** (2026-09-30): la excepción de "primera instalación no pide autorización" (A-023) estaba en `instalar_en_telefono`. Pero `install_apk` —**la tool que se usa de verdad**— comprobaba la aprobación *antes* de llamar a `instalar_en_telefono`, y si no la había, pedía autorización y volvía. La excepción nunca se activaba por el camino real. En un teléfono recién borrado, Aegis pedía una aprobación que solo se podía dar con la app instalada.
- **Por qué no lo cazaron los tests**: los tests llamaban a `instalar_en_telefono` directamente, es decir, al camino que nadie usa. Pasaban 224 en verde mientras la puerta estaba cerrada de hecho.
- **Cómo se arregla**: `es_primera_instalacion(dev)` es la **única** que decide, y la usan los dos sitios. Y el test que importa es el que pasa por `mcp_ops.install_apk`.
- **Corolario**: cuando una decisión está en dos sitios, uno de los dos está muerto; y los tests se escriben contra el que eliges, no contra el que se usa. Cuando un test pasa sin llegar a la tool, sospecha del test, no del código.

### A-026 · Una dirección razonable no es una dirección comprobada

- **Qué pasó** (2026-09-30): al instalar en el teléfono limpio, `api_host_para("telefono")` devolvía `100.101.102.100` —correcta en el portátil— y el APK se compiló apuntando ahí. El **teléfono no llegaba**: Tailscale instalado pero sin sesión (`tailscaled` ni siquiera corría), y la red local bloqueada por `ufw`. El APK iba a instalar una app que abre, dibuja su HUD y no ve nada: sin error ni aviso. Justo el fallo de A-022, dos iteraciones después.
- **Cómo se mide**: preguntando al teléfono, con su `nc`: `nc -w 4 100.101.102.100 8000`. Con Tailscale sin sesión daba timeout; conectado, `HTTP/1.1 200 OK` con el health entero. Las tres rutas reales quedaron medidas: tailnet (depende de la sesión), Wi-Fi directo (ufw lo bloquea) y `adb reverse` (funciona siempre que haya adb).
- **Cómo se arregla**: `dispositivos.telefono_alcanza()` pregunta antes de instalar, y `pasar_puerta_deploy` se niega si el teléfono no llega. Fallar cerrado: si no se puede comprobar, no se instala.
- **Corolario**: un valor por defecto que "suena" bien (una IP, un host, un puerto) es una hipótesis, no un hecho. Y un sistema que instala cosas en tu casa necesita poder decir **"no he podido comprobar que esto funcione"**.

### A-027 · Lo que escribo se cuela en lo que escribo

- **Qué pasó**: al entregar el texto se colaron caracteres de alfabetos ajenos al
  español, dentro de palabras: un verbo con letras árabes en un docstring de test,
  dos palabras MIXTAS con ideogramas chinos en un comentario de YAML y en una
  lección. Todos en el mismo trabajo y todos en el sitio donde más daño hacen,
  porque `lessons/aegis.md` es lo que el agente se lee para corregir su forma de
  trabajar.

  Esta lección tampoco los escribe, y a propósito: nombrar el síntoma es la forma
  más fácil de reproducirlo, y este fichero lo lee el agente.
- **Por qué no lo vi**: las frases se ven bien en el mensaje del chat, donde el
  contexto immediateo los hace legibles, y en el fichero ya no: nadie relee un
  comentario buscando un kanji.
- **Cómo se arregla**: `tests/test_texto.py` recorre los ficheros de texto del
  repo y falla si aparece han, hiragana, katakana, hangul, cirílico, griego, árabe,
  hebreo, devanagari, ancho, mateúsculas o invisibles/bidi. Salvo dos ficheros,
  `app/autopilot.py` y su test, que llevan marcadores de tool en chino y japonés
  **a propósito**: es lo que escribe el modelo de 7 GB cuando se le corta una
  llamada, y hay que poder buscarlos.
- **El test se detecta a sí mismo**: la primera versión llevaba los caracteres
  literales en el docstring y en los motivos de la lista blanca, así que fallaba
  sobre su propio código. Ahora los describe con palabras. Un guardarraíl que no
  puede mirar su propia fuente es un guardarraíl que no funciona.
- **Corolario**: si un defecto se repite, no basta con corregirlo, hay que poner algo
  que lo detecte **antes** del commit. Y un test de texto tiene que poder pasar
  sobre sí mismo.


### A-028 · Un guardarraíl que se queda sin mirar parece que sigue ahí

- **Qué pasó** (2026-10-01): al renombrar `dedsec_colors.dart` a
  `aegis_palette.dart`, `current_brand()` seguía leyendo el path viejo. Pasaron
  dos cosas y ninguna se vio:
  1. Devolvía `<no existe el tema>`, que **no es igual** que el centinela, así que
     la comparación de `build_apk` pasaba y compilaba sin comprobar la marca.
  2. Peor: el centinela era `0xFFC83BFE` (el magenta original) y el tema llevaba
     días en `0xFF2EFFA0` (verde). La comprobación **ya estaba muerta** antes del
     renombrado: no bloqueaba nada y nadie lo sabía.
- **La lección de fondo**: un guardarraíl que compara contra un valor puede quedar
  comparando contra un valor **imposible**, y el resultado es que da verde
  siempre. Un control que dejó de mirar es peor que uno que no existe, porque
  parece que sigue ahí: `build_apk` informaba del color y el color no lo
  comprobaba nadie.
- **Regla**: un guardarraíl tiene que fallar **cerrado**. Si no puede leer lo que
  dice leer, devuelve un centinela que **no** sea el centinela de "todo bien", y
  el que llama tiene que poder distinguir "no hay marca" de "hay marca". Aquí
  `current_brand()` recorre una lista de rutas y, si ninguna existe, devuelve
  `<no existe el tema>`; y `build_apk` **niega** con ese motivo, en vez de
  compilar.
- **Corolario**: cuando un guardarraíl se apoya en un valor literal (un hex, un
  id, una ruta), hay un test que comprueba que **el centinela sigue siendo
  alcanzable**. `TestElGuardarrailDeLaMarca` mira que la paleta exista, que no sea
  el centinela, y que sin paleta se devuelva el fallo en vez de un hex inventado.
- **Corolario de método**: un guardarraíl que compara por *nombres de fichero*
  muere con el primer rebranding. El centinela debe ser un **hecho** —el hex con
  el que el tema nació— y no una decisión de nombres.

### A-029 · Una copia de texto que se repite no informa de nada

- **Qué pasó** (2026-10-01): `pedir_deploy()` mandaba una notificación **al
  teléfono real** cada vez que se llamaba, y se llama en cada
  `install_apk(target='telefono')` sin aprobación. Como el agente reintenta, una
  sesión de trabajo normal llenaba el móvil de avisos sobre una decisión que
  todavía no estaba tomada. Ninguno era accionable.
- **Por qué importa más allá del ruido**: el aviso intermedio dice "falta tu
  autorización". Es un aviso **antes de que exista nada que hacer**. Y el aviso
  que sí importa —"ya está instalado"— se perdía entre los otros. Cuando todo
  avisa, nada avisa.
- **Regla**: separar los avisos por **cuándo importan**. Lo intermedio va al
  destino de trabajo (el emulador, que es donde pasa la prueba); lo final, al
  teléfono, y **una vez**, después de instalar. Y dos avisos iguales seguidos no
  son dos avisos: hay una ventana (`VENTANA_AVISO`) y se dice "ya estaba avisado"
  en vez de repetir.
- **Corolario sobre la degradación**: si el emulador no está, el aviso
  intermedio **no** cae al teléfono. La degradación intuitiva sería "avisa donde
  puedas"; aquí es no avisar, porque el teléfono ya recibe el aviso final y este
  otro volvería a ser ruido sobre una decisión viva.
- **Regla para los tests**: se comprueba el **destino**, no el texto del mensaje.
  El destino es el `-s <serial>` de adb, que va en el kwarg; un test que mirara la
  cadena del mensaje pasaría con el aviso yendo al teléfono. Y hay que mirar
  `serial`, no solo los argumentos.
- **Corolario para el médico**: cuando algo te avisa demasiado, no empieces por
  silenciarlo: cuenta **quién llama** y **cuántas veces**. Aquí el que llamaba era
  un reintento del agente, y silenciar el aviso habría escondido que Aegis
  insiste; cortar la fuente lo deja visible solo cuando hay algo nuevo.

### A-030 · `Color()` es Dart válido

- **Qué pasó** (2026-10-01): el test del rollback de sintaxis abrió una edición
  que rompía el archivo, y usó `= Color()` como "esto no compila". **Sí
  compila**: es una invocación sin argumentos, perfectamente legal. El guardarraíl
  lo aceptó, lo escribió, y el test dejó `Color()` en `aegis_palette.dart` de
  verdad. Hubo que restaurarlo a mano.
- **Por qué es una lección y no un despiste**: el guardarraíl de sintaxis vale
  exactamente lo que `dart format` dice, y `dart format` no sabe qué quería
  escribir el autor. Un test que **asume** que su rompe sintaxis va a romperlo
  está probando su propia suposición, no el guardarraíl. Y si además escribe en
  el repo, se lleva por delante lo que estaba comprobando.
- **Regla**: antes de usar una mutación para probar que algo se rechaza, **comprobar
  que la mutación es lo que crees**. Aquí hay un helper (`_dart_parseable`) que
  pregunta a `dart format` lo mismo que pregunta el guardarraíl, y el test afirma
  que su mutación **no** parsea antes de meterla. Si somedaya mutación_resultara
  válida, el test falla en su propia preparación y no finge que probó el rollback.
- **Corolario**: un test que escribe en el fichero de verdad necesita restaurar el
  estado pase lo que pase. El `finally` no es opcional cuando el fichero bajo
  prueba es el que vive en el repo.

### A-031 · Un arranque que promete lo que no ha comprobado

- **Qué pasó** (2026-10-01): el arranque de la app imprimía `handshake … ok`,
  `auth … ok` y `entrada: concedida` antes de preguntar nada a nadie. Era texto
  fijo, y se pintaba antes de que la app hubiera hablado con el bridge una sola
  vez.
- **La lección de fondo**: A-016 ("el veredicto sale de la traza, no del texto del
  modelo") puesto delante de la persona que usa la app. Un sistema que reporta
  verde sin mirar enseña que **todo lo demás puede ser inventado**, y una sola
  mentira en el primer segundo se paga en la confianza de todo lo demás.
- **Regla**: el arranque dice **solo lo comprobado**, y se queda esperando si no lo
  sabe. La salud del bridge se pasa al arranque como argumento; las líneas se
  imprimen a medida que se saben y desaparecen cuando ya no hay nada que decir.
- **Corolario de método**: un arranque es transitorio, así que **mirar el último
  frame no lo prueba**: hay que pump con pasos finos y recoger **todos los textos
  que han aparecido** en cada paso. Es lo que permite afirmar que una frase se
  dijo —y también que **no** se dijo. Sin eso, el test solo comprueba la app que
  sale después.

### A-032 · Un `.gitignore` por carpeta se multiplica

- **Qué pasó** (2026-10-01): `mobile/assets/brand/` quedó fuera del índice para
  que lo que se meta ahí no entre en el repo. Se añadió a `mobile/.gitignore`,
  que es un segundo sitio de reglas.
- **Por qué se anota**: A-017 pasó justamente porque un patrón sin ancla en el
  `.gitignore` de la raíz se comió `mobile/lib/data/`. Añadir reglas al
  `.gitignore` de `mobile/` es correcto y **no** es el problema; el problema sería
  escribir una regla del móvil en el fichero de la raíz, o dejar los dos con
  contradicciones sin saber cuál manda. La regla: los patrones se anclan al path
  relativo a **su** fichero, y una exclusión nueva se comprueba con
  `git check-ignore -v` antes de darla por buena.

### A-033 · Un permiso atado al run no se puede canjear

> Aplica cuando: cuando ligues un permiso a un run o a un paso

- **Qué pasó** (2026-10-01): la cola de aprobación ataba el token al `run_id` y
  al `paso`. Aprobar y relanzar **crea un run nuevo** con otro id, así que el
  token ya no encajaba: el paso volvía a pedir permiso, para siempre.
- **Por qué es el fallo más silencioso que he hecho**: todo lo demás funcionaba.
  La fila decía `aprobada`, `/aprobaciones` devolvía un token que parecía
  válido, el móvil pintaba el botón bien. Y el paso no avanzaba nunca. Un
  componente que informa "listo" mientras no hace nada es A-016 con otro
  disfraz: aquí el untrue estaba en la fila, no en el texto del modelo.
- **Regla**: un permiso atado a lo que la persona **aprobó**, no al contenedor en
  el que se pidió. Aquí lo aprobado es *una tool con unos argumentos*, así que
  el token valida la tool y los argumentos — y **no** el run. Un permiso para
  `aegis_write_file(path=X)` no autoriza `aegis_write_file(path=Y)`: si valiera
  para más, aprobar una escritura aprobaría la siguiente sin haberla visto.
- **Corolario**: cuando el mismo store sirve para pedir y para canjear, el test
  tiene que recorrer **el círculo entero** con el store real. Los tests por
  partes pasaban los dos: emitía bien el token, y canjear bien el token. El
  eslabón roto era que no había por dónde pasarlo, y ningún test de los dos lo
  cruzaba.
- **Corolario de método**: `POST /autopilot/start` no tenía campo `token`. Al
  añadirlo no se comprobó que llegara: se probó la función `decide()` con el
  store de verdad y funcionó, y eso se confundió con "el círculo cierra". El
  camino entero —HTTP → body → `_run_autopilot_once` → `run_autopilot` → `decide`
  — se verificó después, y encontró el `token` ausente del `AutopilotIn` del
  servidor. **Probar la función no es probar el camino.**

### A-034 · Un endpoint que reconstruye desde un fichero que nadie escribe

- **Qué pasó** (2026-10-01): se añadió la caída a disco a `GET /autopilot/{id}`
  para que reiniciar el bridge no perdiera los runs, y parecía funcionar. Con un
  run real no: los JSONL de `data/logs/runs/` los escribía `relay`, que solo ve
  los runs de **Hermes**. Los de autopilot no escribían ninguno. La única copia
  seguía siendo el dict en memoria.
- **Por qué importa**: la **afirmación** estaba en el propio comentario del
  código, y era falsa. "Los JSONL tenían todo escrito desde el principio" soné
  convincente porque los ficheros existían — los había visto — y no miré **quién
  los escribía**. Es A-016 aplicado a un comentario: un texto que afirma un
  hecho que nadie comprobó.
- **Regla**: añadir una lectura desde disco tiene **dos** mitades: escribir y
  leer. Si solo se hace una, el endpoint responde 404 con la misma seguridad que
  si el run no existiera, y eso es indistinguible de un bug.
- **Corolario**: el vocabulario de eventos es un contrato. El primer arreglo
  escribió `task.max_steps` como evento terminal, que no existe en la taxonomía
  (`task.done`/`task.failed`/`task.stopped`): el run se reconstruía en
  `status: desconocido`. Y `_resumir_run` contaba solo `tool.started`, que es lo
  que emite Hermes, así que los runs de autopilot salían con **cero pasos** —
  que se lee como "no hizo nada".
- **Corolario**: un comentario que explica por qué algo es como es **envejece**,
  y el que lo escribe es el único que lo va a notar. Si un comentario dice "esto
  ya está escrito", hay que comprobar que sigue estándolo después de tocar el
  código de alrededor.

### A-035 · La autonomía necesita el proyecto marcado, y el motivo es el verificador

- **Qué pasó** (2026-10-01): al construir la autonomía, el criterio de "puede
  trabajar solo aquí" quedó en "¿tiene ficha completa?". Tres de los ocho
  proyectos del registro **no tienen verificador declarado**: sus tests ni
  siquiera se pueden ejecutar. Dar permiso de escritura sobre eso es autonomía
  sin forma de saber si el trabajo quedó bien.
- **Regla**: un proyecto necesita **dos** cosas para Aegis pueda trabajar en él
  solo: ficha completa (sabe qué toca) **y** verificador declarado (alguien
  puede comprobar si lo hizo bien). Faltando cualquiera de las dos, el
  interruptor está deshabilitado y **la pantalla dice cuál falta y por qué**.
- **Corolario**: un control que deshabilita algo sin explicar por qué parece un
  fallo. El mensaje tiene que contener el motivo y el sitio donde se arregla
  ("Decláralo en app/projects.py primero"), no solo el estado.

### A-036 · El modo `pleno` no significa "sin preguntar"

- **Qué pasó** (2026-10-01): había tres modos pensados como escalón de libertad —
  `solo`, `permiso`, `pleno`— y la tentación fue que `pleno` significara "ya no
  pregunto nada".
- **Por qué no**: un modo que dispense de la cola no sería autonomía con dientes,
  sería confianza a ciegas. Y la confianza a ciegas se gasta el primer día que
  Aegis se equivoca en algo que importa; entonces el permiso no vale nada y hay
  que volver a quitarlo entero.
- **Regla**: el nivel 3 (lo que sale de tu disco, lo que migra una base, lo que
  toca el teléfono) pregunta **en los tres modos**. `pleno` significa "también lo
  de fuera, si lo apruebas", no "sin preguntar". No existe un modo que dispense
  de la cola, y si algún día se añade, esa es la decisión que hay que pensar dos
  veces.

### A-037 · Denegar con motivo es lo que hace crecer la confianza

> Aplica cuando: cuando te digan que no, sin motivo

- **Qué pasó** (2026-10-01): la primera versión de la cola guardaba un `estado` de
  `aprobada`/`denegada` y nada más. Denegar funcionaba, pero "no" sin razón no es
  aplicable a la siguiente situación parecida, así que Aegis volvía a proponer lo
  mismo con las mismas palabras.
- **Regla**: la denegación guarda **el motivo**, y el motivo se inyecta en el
  prompt del siguiente run bajo "Lo que ya me dijiste que no". No es que Aegis
  aprenda a tener cuidado: es que la persona se lo dijo una vez y lo tiene en
  cuenta. Sin ese bloque, la columna `razon_denegacion` es un registro del
  bridge, no una memoria del agente — dato escrito que nadie lee.
- **Corolario medido**: en la primera prueba de la cola, denegar
  `db_migrate` sobre `compra-unida` con el motivo real ("su journal de drizzle
  está vacío y migrarlo me recrearía las 24 tablas") y comprobar que esa frase
  aparece en el prompt del run siguiente es lo que demuestra que el ciclo cierra.
  Un test que comprueba que la fila tiene el motivo no demuestra nada: la fila la
  escribió quien la denegó, no quien la va a leer.

### A-038 · Un secreto leído del proceso equivocado vale `""` y no lo dice

- **Qué pasó** (2026-10-01): `build_apk` (MCP de `aegis-ops`) compila el APK con
  el token de la API dentro. La clave se leía de `app.config`, que es la
  configuración **del bridge**. El MCP corre como proceso aparte, así que allí
  valía `""` si no se cargaba a mano.
- **Por qué el fallo es invisible**: con la clave vacía el APK **se compila
  bien**, instala bien, abre bien y dibuja bien. Solo falla con un `401` en las
  secciones nuevas — autonomy, agenda, memoria. La mitad de la app funciona, que
  es exactamente el patrón de "la app va fallando" y el que más cuesta
  encontrar, porque nada dice que falte una cabecera.
- **La forma del fallo**: dos procesos, un estado. Es la misma trampa que el
  registro de orígenes (A-020) y el estado de despliegue (A-021), y aquí la
  variante es que **leer bien devuelve vacío sin error**.
- **Regla**: en un proceso aparte, una configuración que viene de otro proceso se
  carga **explícitamente** en el punto donde se usa, y hay un test que comprueba
  que ese proceso la ve. Importar el nombre no basta: el `NameError` es
  evidente, el `""` no.
- **Corolario**: un valor por defecto `""` en un secreto es un permiso silencioso
  a medio hacer. Cuando el valor por defecto desactiva una protección, tiene que
  **decirlo**: `build_apk` deja una línea de log diciendo que el APK sale sin
  token y que los endpoints nuevos van a dar 401.

### A-039 · Un APK que abre no es un APK que funciona

> Aplica cuando: cuando digas que algo abre o funciona

- **Qué pasó** (2026-10-01): con la puerta de `X-Aegis-Token` activada, hay dos
  binarios: el del emulador con el token y el del teléfono sin él (hasta que se
  arregló `build_apk`). Los dos abren, los dos pintan, los dos hablan con el
  bridge. La diferencia solo aparece en cuatro secciones.
- **Por qué el humo no lo habría pillado**: `humo_emulador` comprueba que la app
  **arranca y que el bridge recibe una llamada marcada 'emulador'**. Eso lo
  cumple un APK sin token, porque `/health` y `/proyectos` no lo exigen. El humo
  es un test de vida, no de permisos.
- **Regla**: cuando se activa una protección que devuelve 401 en unas rutas y
  200 en otras, el humo tiene que probar **una de cada**. Aquí, el humo
  comprobará además `/autonomy`, que sí exige token: así "abre" y "funciona" son
  la misma comprobación.
- **Corolario de método**: "compila, instala, abre y dibuja" es un resultado que
  suena a entrega completa y no lo es. Es la forma más común de que un cambio de
  seguridad llegue a production sin que nadie lo note.

### A-040 · "Ya conectado" mirando el dispositivo equivocado

- **Qué pasó** (2026-10-01): `adb_connect()` sin argumentos contaba los
  dispositivos conectados y, si encontraba alguno, respondía `ya conectado:
  emulator-5554`. Como el emulador está **siempre** levantado —es donde van todas
  las pruebas—, la tool **nunca intentaba conectar el teléfono**. Informaba de
  algo que no había comprobado, y el teléfono seguía sin verse.
- **Por qué el fallo cuela**: el mensaje era cierto sobre *algún dispositivo*.
  Solo que no sobre el que importaba. Es A-028 con forma de mensaje de tool: un
  control que dice comprobar algo que no comprueba, y que por eso parece que
  funciona.
- **Regla**: una comprobación tiene que mirar **el objeto que dice mirar**. "Hay
  algo conectado" no es "está conectado el que pedí". Y si no se puede
  comprobar, se dice, en vez de devolver el caso cercano como si fuera el
  pedido.
- **Corolario**: `adb devices` con el emulador arriba **siempre** devuelve algo.
  Cualquier tool que interprete esa lista como "¿está el teléfono?" tiene el
  mismo bug, porque el emulador es el caso común, no el raro.
- **Corolario de método**: un puerto **abierto en TCP** no significa que `adbd`
  sirva. Con la pantalla del teléfono bloqueada, Android retira la sesión de
  depuración y el anuncio mDNS se queda cacheado: el puerto acepta la conexión
  del kernel y no contesta al protocolo. Por eso la tool **intenta de verdad** y
  reporta el fallo, en vez de asumir que por tener el puerto basta.

### A-041 · mDNS no cruza la red privada virtual

- **Qué pasó** (2026-10-01): intentando conectar el teléfono por Tailscale,
  `adb mdns services` no lista nada porque mDNS es **link-local** y no se propaga
  por la tailnet— mientras que en la red local sí listaba, aunque con puertos
  viejos cacheados.
- **Regla**: al resolver un servicio por mDNS hay que probar **las dos redes por
  las que puede estar el dispositivo**, y hay que saber que el silencio de mDNS
  no significa que el dispositivo no esté. Aquí la herramienta announcement el
  mismo teléfono dos veces, con el contador ` (2)` en medio del serial, y el
  duplicado se limpia antes de intentar.

### A-042 · «aviso enviado» no es un aviso: el que avisa tiene que ser el dueño

> Aplica cuando: cuando mandes un aviso y no compruebes que llegó

- **Qué pasó** (2026-10-01): el puente avisaba con
  `adb shell cmd notification post` y devolvía `"aviso enviado"` si salía con
  `exit=0`. En un Samsung real **no había notificación ninguna**:

  ```
  appops: com.aegis.aegis_console  ->  POST_NOTIFICATION: ignore
  canal:  shell_cmd (del sistema, no de Aegis)
  dumpsys: ni un registro de com.aegis.aegis_console
  ```

  El puente dijo que avisó, el agente se lo creyó y nadie miró el móvil. El aviso
  lo firmaba `com.android.shell`, no Aegis, así que no podía llevar su icono, su
  canal, su sonido ni abrir algo suyo; y el `appop` de la app estaba en `ignore`
  porque **nadie declaraba `POST_NOTIFICATIONS`**.
- **Por qué el fallo cuela**: `exit=0` es cierto. Lo que es mentira es la
  conclusión. Es A-016 por sexta vez, y por eso la regla de la casa es
  «el veredicto sale de la traza, nunca del texto»: aquí la traza era un código
  de salida que no dice nada del destino.
- **Regla**: **una notificación que postea otro no es una notificación tuya.** Si
  la firma otro proceso, no puede llevar tu permiso, tu canal ni tu toque. Que
  la publique la app (el puente solo la despierta con `am broadcast`) no es un
  detalle de estilo: es lo que la convierte en accionable.
- **Corolario**: **la entrega se lee del sistema, no del código de salida.** Ahora
  `_verificar_aviso` busca el registro en `dumpsys notification`, y si no está
  devuelve `"AVISO NO LLEGÓ"` con el `appop` incluido, que es el dato que faltaba.
  Un "no verificado" honesto vale más que un "entregado" falso.
- **Corolario**: `android:usesCleartextTraffic` se declaró porque **es lo que la
  app ya hacía**. Dart habla con el puente en `http://` y siempre ha hablado,
  porque los sockets de `dart:io` no pasan por la comprobación de cleartext de
  Java. `HttpURLConnection` **sí** pasa, y ahí se comía un
  `Cleartext HTTP traffic not permitted`. Dos caminos al mismo puente con
  políticas distintas, y solo uno lo sabía.

### A-043 · Avisa *después* de guardar, no antes

- **Qué pasó** (2026-10-01): `pedir_deploy` llamaba a `avisar_intermedio` **antes**
  de `ESTADO.nueva(peticion)`. La app despertaba del broadcast, iba a
  `/deploys`, no encontraba esa petición —solo las viejas— y publicaba «nada
  pendiente».
- **Por qué el fallo cuela**: en las pruebas siempre había alguna petición
  anterior, así que el aviso salía, con la cuenta equivocada. Funcionaba **por
  restos**. Con el estado limpio —que es justo cuando más importa que avise— no
  avisaba, y el puente decía «entregado y verificado» porque la notificación sí
  estaba: era la de «nada pendiente».
- **Regla**: si el aviso **pregunta** el estado, hay que escribirlo antes de
  preguntar. Y un sistema que parece funcionar porque hay restos de antes no
  está funcionando: está dependiendo de que el mundo esté sucio.
- **Corolario**: **vaciar el estado es parte de la prueba.** La primera vez que
  importé los despliegues a un emulador recién arrancado fue cuando se vio, y
  no por el cambio sino por el estado limpio.

### A-044 · Red en el hilo principal: el `catch` la convierte en una respuesta

- **Qué pasó** (2026-10-01): el cuadro de decisión hacía `Puente.pendientes()` y
  `Puente.decidir()` —llamadas de red síncronas— en el hilo principal. Android
  tira `NetworkOnMainThreadException`, y el `catch` de `pedir()` la devolvía como
  `null`.
- **Por qué el fallo cuela**: en `pendientes()` `null` significa «no pude
  comprobar», y el cuadro pintaba **«SIN RESPUESTA»** con la app perfectamente
  conectada. En `decidir()` significaba «no pude hablar con el puente», y tras
  pulsar **«SÍ»** salía un Toast de error con la petición **sigue `pendiente`**.
  No es un error: es una respuesta, y es mentira. La UI se ve bien, los textos
  están, y lo que dice no pasó.
- **Regla**: un `catch` que devuelve `null` y un valor legítimo que sea `null` son
  la misma cosa para quien lee. Si se distinguen, hay que distinguirlos **por
  separado**: o se lanza, o se registra el motivo, o el `catch` distingue.
- **Corolario de método**: una excepción en el hilo de un `BroadcastReceiver` es
  **invisible**: no hay stacktrace en logcat. Desde el puente, «la app falló» y
  «la app no avisó» se ven igual. Por eso el receptor lleva `catch` + `Log.e`, y
  el `pedir()` registra la excepción en vez de tragársela.

### A-045 · La puerta cubría menos de lo que su comentario decía

> Aplica cuando: cuando el comentario de una puerta prometa más de lo que hace

- **Qué pasó** (2026-10-01): `X-Aegis-Token` protegía notas, tareas, autonomía y
  aprobaciones de tools, pero **`/deploys` y `POST /deploys/{id}` estaban
  abiertos**. Con el endpoint nuevo de instalar en segundo plano, cualquiera que
  alcanzara el bridge en la tailnet podía leer los ids pendientes, aprobarlos y
  disparar una instalación.
- **Por qué el fallo cuela**: el comentario de la puerta decía que cubría «dar
  permiso de escritura sobre tus proyectos, denegar una aprobación». Eso es
  exactamente lo que hace aprobar un despliegue. La puerta y su documentación
  contaban historias distintas, y la que se cumple es la del código.
- **Regla**: una lista de lo que hay detrás de la puerta es una **afirmación que
  hay que mantener**. Cuando añades un endpoint a una superficie sensible, se
  actualiza la lista, y si la superficie es sensible y no está en la lista, se
  pregunta por qué antes de añadirla.
- **Corolario**: lo protegido tiene que incluir **lo irreversible**. Instalar un
  APK no tiene vuelta atrás y se puede repetir con un token viejo. Una nota se
  puede borrar; un `adb install`, no.

### A-046 · «Conéctalo» cuando ya está conectado

- **Qué pasó** (2026-10-01): `telefono()` solo aceptaba seriales con
  `_adb-tls-connect`. Pero la ruta manual que documenta el runbook
  (`adb mdns services` → `adb connect <ip>:<puerto>`) deja el serial como
  `100.101.102.103:46119`. El teléfono estaba conectado y respondiendo, y la
  puerta dijo «tu teléfono no aparece en adb. Conéctalo».
- **Por qué el fallo cuela**: la comprobación era *cierta* —ese serial no
  aparece, en efecto— y el mensaje pedía algo que no hacía falta. Es A-028 otra
  vez: un control que mira una forma y no el objeto. Y el runbook, que es donde
  se documenta la ruta manual, era la prueba de que esa forma era la normal.
- **Regla**: **la forma que documentas es una forma que tienes que soportar.** Si
  el runbook dice «conecta a mano por esta vía», el detector tiene que reconocer
  esa vía, o el runbook está mintiendo sobre lo que el sistema acepta.
- **Corolario**: reconocer más formas no es adivinar más. Lo que se descarta
  sigue siendo el emulador y el loopback, y con dos teléfonos la puerta sigue
  pidiendo que digas cuál. La diferencia entre «leer» y «suponer» está en qué se
  descarta, no en cuántas formas se aceptan.

### A-047 · Reconocer más formas no es contar más aparatos

- **Qué pasó** (2026-10-01): al arreglar A-046 —reconocer el teléfono conectado
  por IP— un mismo móvil conectado a la vez por mDNS y por `adb connect` pasó a
  contar como **dos** teléfonos. `telefono()` respondió «hay 2 teléfonos» y todo
  lo del teléfono se detuvo, con el móvil delante. El aviso de fin de instalación
  no pudo salir por eso.
- **Por qué el fallo cuela**: la regla anterior —«si hay varios, se dice cuál»—
  era la defensa contra adivinar, y por eso nadie la revisó al **ampliar** el
  reconocimiento. El guardarraíl llevaba razón; lo que cambió fue lo que había
  detrás.
- **Regla**: `adb` registra el **aparato**; el serial es de la **conexión**. Un
  mismo teléfono tiene tantas entradas como vías abiertas, así que la
  deduplicación tiene que ser por identidad de hardware (`ro.serialno`), no por
  forma del serial. Y si la identidad no se puede leer, **no se unifica**: peor
  no unificar que unificar de más, porque lo que se instala es irreversible.
- **Corolario**: ampliar lo que un sistema reconoce obliga a repasar lo que
  cuenta. «Cuántos hay» es una pregunta que se responde con el criterio de antes,
  no con el que se acaba de escribir.

### A-048 · Un mock que devuelve lo que la función no devuelve

- **Qué pasó** (2026-10-01): `pasar_puerta_deploy` devolvía `dev.serial` (un
  `str`) y un llamador nuevo se lo pasaba a `instalar_en_telefono`, que espera un
  `Device`. Reventó con `AttributeError: 'str' object has no attribute 'serial'`
  **en un hilo en segundo plano**, un minuto y medio después de que el usuario
  pulsara «sí».
- **Por qué el fallo cuela**: el test unitario fijaba el mock a un `Device`, y
  con eso pasaba. El test no comprobaba el contrato: lo **contradecía** mientras
  parecía confirmarlo. Un mock que devuelve algo que la función nunca devuelve es
  la forma más común de que un test de contrato no sea un test de contrato.
- **Regla**: para comprobar un contrato hay que mirar **la clase** que sale, con
  la función real y sin mocks en el medio. `assertIsInstance(pasar_puerta(),
  Device)` con la puerta de verdad, y además un test de punta a punta de la
  cadena, que es donde un mock siempre está mintiendo.
- **Corolario**: los fallos en hilos son invisibles por definición —no hay
  stacktrace en el sitio donde se mira—. Un `log.exception` en el hilo es parte
  del contrato, no decoración.

### A-049 · Un arranque que puede volver atrás se queda colgado

- **Qué pasó** (2026-10-01): la app se quedaba en la pantalla de arranque para
  siempre en el teléfono —«AEGIS · puente: contesta · hermes: arrancado» y un
  cursor—, y en el emulador iba bien.
- **Por qué el fallo cuela**: las dos condiciones del arranque —«¿enseño todas
  las líneas?» y «¿he terminado?»— eran **la misma comparación sobre una lista
  que cambia** cuando contesta el puente. Con la red local contestaba antes del
  primer salto y todo cuadraba; por la malla, no:

  ```
  t=0     cargando            -> 1 línea   ·  la cadena arranca
  t=640   2 > 1              ->  entregado ·  la cadena para
  t=900   llega la respuesta  -> 3 líneas  ->  2 > 3 = falso
  ```

  El arranque **retrocedía** a la pantalla de carga con la cadena ya muerta. El
  fallo solo existe donde la red es lenta, que es justo donde nadie prueba.
- **Regla**: una transición, una vez hecha, **no se deshace**. El arranque no es
  un sitio donde enseñar datos: su trabajo es decir lo que se sabe hasta ese
  momento y pasar. Lo que llegue después lo enseña la pantalla real, que es la
  que tiene los datos frescos.
- **Corolario**: no mires la lógica de una pantalla de carga sin mirar **quién
  cambia sus entradas**. Aquí la cambiaba el puente, a 900 ms, y el test con un
  repositorio falso que responde al instante no podía verlo. El fallo se
  reproduce con un retardo de 900 ms en `health()`: cuatro líneas de test.
- **Corolario de método**: «no puede pasar» hay que demostrarlo, no argumentarlo.
  Yo comprobé que la aritmética no podía colgarse, y aun así se colgaba, porque
  la lista crecía **después**. Cuando un sistema depende de datos que llegan
  tarde, el test tiene que llegar tarde también.

### A-050 · El script que dice «hecho» sin haberlo hecho

- **Qué pasó** (2026-10-01): `deriva-marca.sh` usaba `$(( 48 * 1.5 / 2 ))`, y la
  aritmética de bash no admite decimales. El error salía por stderr, `set -e` no
  paró el script, la línea se saltó, y el script **terminó con su resumen
  «Marca derivada»** sin haber generado la mitad de los ficheros.
- **Por qué el fallo cuela**: un `set -e` da una sensación de seguridad que no
  cubre la aritmética dentro de `$(...)` ni los errores de una herramienta
  externa en una tubería. El resumen se imprimía igual.
- **Regla**: **el resumen de un script se comprueba contra el disco.** Si el
  script dice que ha hecho cinco cosas, tiene que haber cinco ficheros, y su
  ausencia es un fallo con salida no cero. Un informe que no se contrasta con la
  realidad es un texto, y este repo ya sabe lo que pasa con los textos que
  describen lo que no ha pasado.

### A-051 · Un test que borra el build rompe la puerta sin que nadie lo note

- **Qué pasó** (2026-10-01): la puerta del despliegue rechazaba la instalación
  con «este APK se compiló sin anotar token. Recompílalo», y recompilando se
  arreglaba, y al volver a correr los tests se rompía otra vez. Tres veces, con
  el mismo mensaje, hasta que se buscó de dónde salía.
- **La causa**: un test guardaba `original = _sello_de_token(deploy.APK)` y
  llamaba `original.unlink()`. `deploy.APK` es **el APK real**. El test pasaba, la
  suite entera pasaba, y al terminar había borrado el sello del binario de verdad.
- **Por qué el fallo cuela**: el síntoma no parecía del test. Parecía de la
  puerta, o del `build_apk`, o del token. Y era del test, que no falla nunca: un
  test que rompe el entorno de otro test, o del proceso que viene después, no
  puede fallar él mismo.
- **Regla**: **un test no toca el directorio de compilación.** Lo que el humo
  encuentra tiene que ser lo que hay, y si un test lo modifica, deja de estar
  probando el humo y empieza a decidir lo que el humo va a ver después. Todo lo
  que un test escriba —y borre— va a `tempfile`.
- **Corolario**: cuando un sistema da un error que **desaparece al repetir la
  acción que lo arregla**, el culpable no está en la acción. Está en lo que se
  ejecuta entre medias. Y esa pregunta se hace antes de la cuarta vez, no
  después.
- **Corolario**: por eso `build_apk` **falla** si no consigue anotar el token, en
  lugar de devolver un APK que luego la puerta rechaza con un mensaje que
  despista. Una tool que entrega algo inservible y dice que salió bien es
  exactamente el mismo error de A-016, con un fichero binario de protagonist.

## A-052 — La silueta no sale del texto, y la PBM tiene la polaridad al revés

**Cuándo**: 2026-10-01. Al corregir los iconos del lanzador, que salían con fondo
blanco, deformados y con resolución mala.

- **El síntoma**: el icono del lanzador era un **cuadrado entero del color**.
  Fondo blanco, deformado y borroso. Cuatro defectos que parecían uno.
- **Eran cinco fallos, y ninguno era el que parecía**:
  1. `sed '1,12d'` quitaba 12 líneas de cabecera; la cabecera tiene **16**. Se
     colaban cuatro renglones de prosa en español, de ancho completo, encima de
     la calavera. La marca era una nota al pie con un dibujo debajo.
  2. La tabla de densidades dividía el factor: `f = f2 / 2`. En `hdpi`, `3 / 2`
     da **1** en aritmética entera, así que el icono salía de 48 px donde
     tocaban 72. La mitad se perdía en la única densidad con factor impar.
  3. `-channel A -separate` **no devuelve el alfa**: devuelve los canales RGB.
     UMBralado al 6 %, el hueso se pasa de brillo y la máscara sale blanca
     entera. Es `-alpha extract`.
  4. `-colorize 100` con relleno opaco quiere decir «todos los píxeles son del
     relleno». Para cambiar solo el blanco por hueso es `-opaque white`.
  5. En la **PBM**, un `1` es **negro** y un `0` es blanco. Al revés de como se
     le ocurre a cualquiera. Sin invertir, el cranium sale de fondo.
- **Y una trampa de ImageMagick que no es de este repo**: dentro de una misma
  invocación, `magick -size NxN xc:negro mascara -compose Lighten -composite
  -extent NxN` satura la imagen a un solo color, y con `-flatten` pasa igual.
  Medido: 2 colores sin `-extent`, 2 sin `-flatten`, **1** con cualquiera de los
  dos. Separado en dos comandos, cada uno hace lo suyo.
- **El hallazgo de fondo**: la silueta **no se puede derivar del arte de
  texto**. `rellenar` llena la calavera de verdad para que se lea, y `-trim` le
  quita el aire, así que la caja del arte **es** la calavera: dentro de ella
  casi cualquier bloque tiene trazo y la máscara se satura. Se probaron las dos
  vías y las dos fallan. La forma está en la **máscara del JPG**, que es de
  donde sale todo y de donde mide `verifica-calavera.py`. Y con la proporción de
  píxeles de la imagen: la VGA es 8x16, el bloque de texto sale el doble de alto
  que de ancho, y una calavera hecha de texto sale estirada al doble.
- **Regla**: un fichero para personas y un fichero para máquinas son dos
  ficheros. `calavera_jazz.txt` lleva quince líneas de comentario contando su
  propia historia, y está bien; el pipeline no puede leerlo, porque un comentario
  de ancho completo es indistinguible de una fila de arte. Se emite
  `calavera_jazz.arte.txt`, sin cabecera, y el shell no tiene que acordarse de
  un `sed` ni de cuántos renglones de comentario hay hoy.
- **Regla**: cuando una tool de imagen produce un color plano, el fallo **no
  está en el teñido**, está en el paso anterior. Aquí fueron tres pasos
  distintos, y en dos el síntoma —«sale un cuadrado»— era idéntico. Medir
  `colores=%k` después de cada paso es lo que separó los tres; probar
  cambios a ciegas los habría mezclado en un solo «sigue igual».
- **Regla**: `bash -x` filtrado con `grep` sobre el nombre del fichero de
  salida esconde justo lo que hay que ver. Los `printf` de una cabecera PBM
  contienen el nombre de la **entrada**, no el del fichero que se escribe.
- **Corolario**: la silueta es de la imagen y el texto es la textura. Cada uno
  con su proporción. La app, el lanzador y la notificación pintan **la misma**
  rejilla (`calavera_silueta.dart`), así que no pueden divergir.
- **Lo que sigue sin estar bien**: a 28 px —el glifo de la cabecera— una
  silueta de 40×43 no se lee como calavera. Sale un bulto, y no hay umbral que
  lo arregle: escota inferior de la fuente, no del algoritmo. Se le dice al usuario y
  lo juzga él.

## A-053 — El humo que falla por impaciencia bloquea una instalación legítima

> Aplica cuando: cuando una espera venga de prisa y no de calidad

**Cuándo**: 2026-10-01. Instalando una actualización en el teléfono real.

- **El síntoma**: `install_apk(target='telefono')` se paró con «el humo en el
  emulador no pasa: la app arrancó pero el bridge no recibió ninguna llamada
  marcada 'emulador'». La puerta tiene razón en abstracto —si el humo no pasa, no
  se instala en un teléfono—, y aquí no había nada que installar en el teléfono.
- **Lo medido, y no era la app**: corriendo el humo a mano **pasaba** (`True`), y
  mirando `/origen` en vivo, la app del emulador llama al puente **cada 2
  segundos** y se registra como `emulador`. El mecanismo estaba sano y era más
  rápido que la ventana de 40 s del propio humo.
- **Por qué entonces fallaba dentro del run**: la puerta corre `analyze` + tests
  + build del APK del teléfono + humo, encadenados, con el emulador installing un
  binario de 170 MB. Bajo esa carga la primera llamada de la app no llega dentro
  de la ventana.
- **La lección de verdad está en el propio código, escrita desde hace tiempo y en
  la dirección contraria**: el comentario del humo dice que un humo que falla
  por impaciencia *enseña a ignorar la puerta*. Lo que se vio es la otra mitad:
  **una puerta que falla por impaciencia enseña que a saltársela**, y el coste es
  que la siguiente puerta legítima parece burocracia. Las dos son el mismo
  defecto.
- **Qué NO se hizo, y por qué**: no se tocó el humo ni se lo relajó. Un guardarraíl
  que se debilita para que algo pase es un retroceso (AGENTS.md §4). Se dejó
  intacto.
- **Qué se hizo**: `pedir_deploy` **no instala nada** —registra la petición y
  manda el aviso— y la instalación sigue pasando por `instalar_pendiente`, con su
  comprobación de huella. Lanzar el aviso por ahí no debilita la puerta: mueve el
  aviso al sitio desde el que el humano lo aprueba, que es justo lo que se
  buscaba, y quien aprueba sigue siendo el usuario con el dedo en la pantalla.
- **Regla**: cuando una puerta bloquee algo y se demuestre que lo bloquea **por
  falso**, la respuesta no es abrirla. Es encontrar qué parte del gesto pedido no
  necesitaba la puerta. Aquí, todo menos instalar.

## A-054 — Apagar Aegis con `pkill` no lo apaga

- **Qué pasó** (2026-10-03): al terminar la sesión de trabajo, `pkill -f 'ollama
  serve'` y `pkill -f 'hermes gateway run'` **no mataron nada**, y no se notó
  hasta que un `curl` posterior a un puerto distinto confirmó que seguían vivos.
  Lo que pasó: los dos comandos dejaron traces de que sí se pararon, y
  además quedó un `llama-server` de un modelo cargado **más vivo que su propio
  `ollama serve`**. Hubo que caer a `kill` por PID.
- **Por qué falla `pkill` aquí**: los tres servicios se lanzan con `setsid`, así
  que el patrón `-f` tiene que seguir casando con la línea de comandos *exacta*
  del proceso, y `pkill` devuelve 0 aunque no mate a nadie que importe. Sin
  verificación posterior, un apagado es una intención, no un hecho.
- **Regla**: **un apagado que no comprueba que el proceso murió no está hecho.**
  Matar por PID (y al grupo de proceso, que es lo que se lleva los hijos),
  esperar, y después **comprobar el puerto**. Si el puerto sigue ocupado, es un
  fallo con salida no cero, no un mensaje de «parado».
- **Y la lección de fondo, que es la que más veces se repite**: el operarlo de
  este repo estaba repartido en tres sitios, con tres rutas de log distintas y
  ningún `stop`. Ahora hay `infra/stack.sh` con `arrancar | parar | estado`, y
  **`estado` incluye si Aegis puede escribir** — que es lo que hay que mirar
  antes de delegarle algo. Ante una tarea de operación, primero: `bash
  infra/stack.sh estado`, y el script. No tres `pkill` improvisados.

## A-055 — Un token que se gasta antes de comprobar es un permiso quemado

> Aplica cuando: cuando gastes un permiso antes de comprobar la llamada

- **Qué pasó** (2026-10-03): al cerrar el círculo de las aprobaciones desde el
  móvil (guardar el token, relanzar el run), `decide()` **gastaba** el token antes
  de comprobar que la llamada era la aprobada. Medido con `project_create`: el
  modelo emitía el verificador como objeto en una llamada y como dos cadenas en
  la siguiente; el token se consumía en el intento que no encajaba y el permiso
  quedaba inservible. **Tres intentos, tres aprobaciones, ninguna escritura.**
- **La segunda mitad del mismo fallo**: un token es de un solo uso, así que el
  bucle lo reenviaba en cada paso. Tras un alta correcta, el paso 2 —un
  `ficha_read`, que es de las tools **libres**— moría con «ese permiso ya se
  usó». El permiso se aplicaba a tools que no tenían nada que ver con él.
- **Por qué cuesta verlo**: el mensaje de error era *correcto* en cada pieza, y
  el síntoma («no me deja continuar») se parece al de mil cosas. Solo se ve
  leyendo los argumentos de cada intento uno a uno.
- **Regla**: **un permiso se mira antes de cobrarse, y se cobra una sola vez.**
  `por_token()` mira sin gastar; `gastar()` cobra. Y quien lo gasta lo dice
  (`Decision.uso_token`), para que el bucle deje de mandarlo.
- **Y el patrón de fondo, que es el que se repite en este repo**: cuando el
  veredicto depende de comparar algo con lo aprobado, **el orden de las
  operaciones es el requisito**. Comparar y luego cobrar es un permiso;
  cobrar y luego comparar es una moneda de cobre que se pierde al primer desajuste.

## A-056 — Un argumento compuesto es un argumento que el 7B no repite igual

> Aplica cuando: cuando le pidas al modelo un argumento compuesto (JSON, listas anidadas)

- **Qué pasó** (2026-10-03): el alta de proyecto necesitaba declarar el
  verificador, y se pidió como un **JSON dentro de una cadena**
  (`verificar='{"check": [...], "test": [...]}'`). El modelo lo emitía como
  objeto en una llamada y como texto en la siguiente, y como el token valida la
  llamada exacta, **ningún relanzado casaba nunca**.
- **Por qué**: el 7B es literal con la forma que se le da. Un argumento que
  tiene que tener una sintaxis exacta es un argumento que algún día llega con
  otra. Es A-016 dos capas más abajo: el mismo defecto, del mismo modelo, y la
  misma respuesta —**darle una forma simple y dejar que la complication la
  ponga otro**.
- **Regla**: a las tools que usa el modelo, **argumentos planos y pequeños**:
  `verificar_check="tsc --noEmit, dart format ."`, `verificar_test="vitest run"`,
  `db="neon"`. Las formas ricas (JSON) se dejan para quien escribe la llamada a
  mano. Y el motivo va en el `docstring` de la tool, que es lo que el modelo lee.
- **De paso, un contrato que el alta estaba rompiendo**: `registro/*.json` exige
  declarar `db` aunque esté vacío (tests/test_neon.py). El alta no lo escribía,
  así que una entrada nueva pasaba los tests de su módulo y rompía el de la
  frontera. **Las fronteras no se comprueban en el módulo que las cruza.**

## A-057 — Un test que depende de lo que hay vivo en el disco

- **Qué pasó** (2026-10-03): los tests de `test_registro.py` dandolan de alta
  `acme` fallaron con «'acme' ya está registrado» **porque el ensayo en vivo
  había creado ese proyecto de verdad**. Los tests no estaban mal: el workspace
  tenía basura que nadie pidió conservar.
- **Por qué importa más de lo que parece**: un test que depende del disco real
  no es un test, es una ruleta — y su fallo se lee como «el alta está rota»,
  que es la conclusión **equivocada** y la más cara.
- **Regla**: el fixture de un test que toca el registro **vacía lo que vino del
  disco** (`_DATOS`) y deja lo declarado en código, que es frontera de seguridad.
  Si un test falla solo porque existe un proyecto real con ese nombre, el test
  está mal: se arregla el test, no el proyecto.

## A-058 — «Ejecutar lo aprobado» no es «relanzar el run»

> Aplica cuando: cuando ejecutes algo que el usuario aprobó y no lo reemitas por el modelo

- **Qué pasó** (2026-10-03): cerrar el círculo de una aprobación desde el móvil
  exigía relanzar el run con el token, y el token valida la llamada, no el run.
  Medido con `project_create`: de cuatro intentos, **uno solo** casó. La causa no
  fue la puerta, fue que el 7B emite la misma tool con argumentos distintos según
  el intento (A-056). Cada desajuste devolvía una petición nueva: el flujo era
  «aprobar, relanzar, fallar, aprobar otra vez».
- **La distinción que faltaba**: aprobar no es aprobar *un run*, es aprobar **una
  llamada con unos argumentos**. Así que existe `POST /aprobaciones/{id}/ejecutar`,
  que corre esa llamada tal cual, sin modelo en medio, y gasta el token. Es más
  fiel a la aprobación, no menos: lo que se ejecuta es lo que se leyó.
- **Lo que NO es un atajo**: solo tools de nivel 3 (las únicas que generan
  aprobación), de un solo uso, pasando por sus propios guardarraíles, exigiendo
  `X-Aegis-Token`, y dejando rastro en
  `data/logs/runs/aprobacion-{id}.jsonl` con el **mismo formato** que un run.
- **Relanzar no se quita**: sigue siendo lo correcto cuando lo que quieres es que
  el run **siga** (dar de alta el proyecto *y* seguir trabajando). Solo deja de
  ser la única manera de cobrar un permiso.
- **Y una trampa de la interfaz, medida al implementarlo**: ejecutar borra la
  tarjeta de la cola, y con ella **la prueba de lo que pasó**. El resultado tiene
  que vivir fuera de la tarjeta, o el botón se queda mudo justo cuando más
  hace falta saber si salió.

## A-059 — Una tool que deniega no lanza: «hecho» sobre «RECHAZADO»

> Aplica cuando: cuando pintes un resultado de una tool sin leer lo que devuelve

- **Qué pasó** (2026-10-03): `POST /aprobaciones/{id}/ejecutar` respondía `ok:
  true` con un `result` que decía `ALTA RECHAZADA: 'acme' ya está registrado`. Las
  tools de Aegis devuelven el motivo como **texto**, no como excepción.
- **Por qué importa tanto**: es el falso éxito de A-016 una capa más abajo. La
  guía dice que el veredicto no salga de lo que el modelo cuenta; aquí salía de lo
  que la tool cuenta, que es la misma trampa.
- **Regla**: cuando el `ok` de una capa se construye a partir de lo que devuelve
  una función que **deniega sin lanzar**, mira el motivo antes de decir que se
  hizo. La lista de motivos es corta y explícita a propósito: mejor un `ok`
  demasiado optimista en un caso raro que un `ok` que adivina.

## A-060 — Una variable documentada que no hace nada es peor que no documentarla

> Aplica cuando: cuando uses una variable de entorno o un parámetro que declaraste

- **Qué pasó** (2026-10-03): el teléfono estaba **enchufado por USB** y adb lo
  veía (`SERIAL1234567`), y Aegis respondía «tu teléfono no aparece en adb. Conéctalo».
  El runbook ya tenía la respuesta —`AEGIS_PHONE_SERIAL`— pero declarar esa
  variable en `bridge/.env` **no hacía nada**, por dos motivos encadenados:
  1. `dispositivos.py` la leía de `os.environ`, y **nadie exporta el `.env` al
     entorno**;
  2. al pasarla a `Settings`, pydantic mapea `phone_serial` a `PHONE_SERIAL`, no
     a `AEGIS_PHONE_SERIAL`. Sin `validation_alias`, seguía sin hacer nada.
- **Lo que lo delató**: un informe que se contradecía a sí mismo. `adb_devices`
  decía «tu teléfono: SERIAL1234567» (para eso cogía «el primero que no sea el
  emulador») y un segundo después la puerta decía que no había teléfono. **Dos
  mensajes sobre lo mismo, y los dos creíbles.** Eso es un informe que miente,
  que es peor que no tener informe.
- **Regla**: **toda variable que se documenta se prueba de extremo a extremo** en
  la máquina donde vive. Si se documenta y no hace nada, la culpa no es de quien
  la puso: es de quien la escribió. Y cuando un informe y una tool discrepen,
  primero se sospecha del informe: es el que no tiene por qué tener razón.
- **De paso**: la IP del bridge para el APK del teléfono tenía el mismo problema
  (`AEGIS_BRIDGE_TAILNET_IP`), y cuando se declara tiene que llegar a la puerta.

## A-061 — Una puerta que comprueba una cosa y responde por otra

> Aplica cuando: cuando digas «verificado» o «listo»

- **Qué pasó** (2026-10-03): se aprobó e instaló en el teléfono un APK de **dos
  días antes** del código que se estaba tocando. La puerta dio el visto bueno:
  la huella casaba («APK verificado, listo para instalar») y el resto de
  comprobaciones estaban en verde. Todo lo que la puerta comprobaba era cierto, y
  aun así lo instalado no era lo que se creías. **Yo mismo lo instalé creyendo
  que era el nuevo**, leyendo un mensaje de éxito.
- **Por qué la huella no lo cubre**: `_huella_binario` es `tamaño-mtime`, y sirve
  para responder «¿es el mismo fichero que aprobaste?». Eso es distinto de «¿es
  el código de ahora?». Son preguntas parecidas y no son la misma.
- **Y un falso positivo por el camino**: comparar «el código es más nuevo que el
  APK» con `mtime` dio positivo con un fichero de `lib/` **sin cambios** (`touch`
  o lo que fuera). Bloquear una instalación por eso es peor que no comprobar:
  entrena a mirar el aviso por encima. La comprobación que quedó es una **firma
  de contenido** que escribe la propia compilación (`<apk>.sello`).
- **Regla**: **quien compila es quien dice de qué código salió el binario.** Ni la
  fecha del fichero, ni el nombre del APK, ni el `_huella_binario`: el sello.
  Y cuando no hay sello, no se afirma nada —«no comprobado» no es «verificado».
- **La frase que resume el resto de esta lección**: una puerta que dice «listo»
  tiene que poder responder «¿listo para qué?». Si no puede, no está lista.

## A-062 — Dos motores no son dos opciones: son dos sitios donde vive un guardarraíl

- **Qué pasó** (2026-10-03): la pantalla de pedir misión tenía un interruptor
  HERMES / AUTOPILOT, y era lo primero que te cruzabas al encargar algo. La
  diferencia real entre los dos no era de capacidad: **los dos llamaban a las
  mismas 18 tools de `mcp_ops.py`** — Hermes por MCP, el autopilot
  llamándolas en proceso. El interruptor no elegía qué se podía hacer, elegía en
  qué proceso vivía el bucle.
- **Y por qué eso no es indifferent**: todo lo que hace que Aegis sea Aegis vive
  en el bridge — los tres niveles de `autonomy.py`, la cola de aprobaciones, la
  memoria con **el veredicto sacado de la traza** (A-016), los guardarraíles. Si
  el bucle vive en Hermes (proceso aparte, `:8642`), cada uno de esos controles
  hay que reimplementarlo al otro lado del socket. Dos motores son **dos sitios
  donde puede vivir un guardarraíl**, y uno de los dos no los tenía.
- **Y el bug que se escondía detrás**: el móvil mandaba `verificar: false`
  **fijo** en cada run. Desde el teléfono, **ninguna escritura pasaba por el
  verificador**, ni en un proyecto que ya estaba marcado como escribible. La
  ruta de `curl` sí la tenía. El mismo encargo se comprobaba o no **según desde
  dónde saliera**. Un interruptor que no hace nada pero que además cuelga de él
  una decisión de seguridad es peor que un interruptor de más: por lo menos el
  de más no promete nada.
- **Regla**: **una opción de la UI tiene que cambiar lo que ejecuta, no solo por
  dónde pasa.** Si dos caminos llegan a la misma capacidad, el selector es
  ruido que además obliga a decidir algo que no importa. Y cuando la decisión
  afecta a una verificación, sale de **datos** (`/autonomy`), nunca de un valor
  que alguien escribió a mano en el cliente.
- **De paso**: quitar Hermes del cliente no quitó lo único que tenía bueno. Se le
  copiaron `stop` y `steer`, que es lo que hace un canal una conversación y no
  una cola de espera. Y parar **no** es cancelar la tarea: `_execute` es
  síncrono, así que la parada es un `Event` que el bucle consulta **antes de
  pedirle nada más al modelo**. El paso en marcha se termina entero y se
  registra; la traza sigue siendo la evidencia.

## A-063 — `AnnotatedRegion` arregla el color del sistema, no el espacio

- **Qué pasó** (2026-10-03): la cabecera del shell —marca, glifo y «en línea»—
  se dibujaba **debajo de la barra de estado**. Tenía su
  `AnnotatedRegion<SystemUiOverlayStyle>` puesto, con el color bien, y aun así se
  solapaba: `AnnotatedRegion` decide el **color** del texto del sistema, no
  cuánto hueco le deja. El hueco lo aplica `SafeArea`, y un `Container` de 52 px
  dentro de `Scaffold.body` no lo lleva.
- **Y un segundo bug del mismo origen**: los dos avisos flotantes estaban clavados
  a `top: 52`, **suponiendo** que debajo de la cabecera empezaba el contenido. En
  cuanto hay inset se montaban encima de la marca. Salen justo cuando peor se ve
  la app —sin puente, o esperando tu OK— así que tapaban la marca en el peor
  momento posible.
- **Regla**: **el inset se cuenta en un solo sitio.** Hay una constante y una
  función (`_finCabecera`), y los avisos la llaman. Tres números que se puedan
  desincronizar son tres números que se van a desincronizar. Y cualquier `top`
  clavado dentro de un `Stack` es una suposición sobre algo que el framework no te
  ha prometido.
- **El test que lo fija, y por qué es el que importa**: `mobile/test/inset_test.dart`
  **inyecta** el inset (`tester.view.padding`), porque en un test vale 0 y sin
  barra no hay solape posible —el test pasaría siempre, verde, sin comprobar nada.
  Y afirma las dos direcciones: con inset la caja baja, sin inset se queda en 0.
  La segunda es la que avisa si alguien "arregla" el solape con un padding fijo de
  24, que en un móvil sin muesca no se nota.
- **Cuidado con las unidades**: `tester.view.padding` va en **píxeles físicos** y
  el `MediaQuery` los divide por `devicePixelRatio`. Con el ratio por defecto de
  3, pedir 24 de status bar da 8 lógicos, y el test mide otra cosa de la que
  cree. Fijar `devicePixelRatio = 1.0` hace físicos y lógicos lo mismo.

## A-064 — Tocar `lib/` del móvil invalida el APK, y eso rompe 12 tests que no son del móvil

- **Qué pasó** (2026-10-03): un cambio en `mobile/lib/` dejó **12 tests de
  `bridge/tests/test_deploy.py` en rojo**, y el mensaje era `PuertaCerrada: El
  APK no corresponde al código de ahora`.
- **Por qué**: `_firma_del_codigo` hashea `pubspec.yaml`, `lib/**` y
  `android/app/src/main/**` del móvil. Ese sello es lo que impide aprobar la
  instalación de un APK viejo (A-061). Al tocar `lib/` sin recompilar, el APK del
  teléfono pasa a estar viejo **de verdad**, y la puerta tiene razón.
- **Lo que no es el fallo**: los tests. Fallaban en `test_deploy.py` y el cambio
  era en `ahora_page.dart`, que es lo que más desorienta: no es que el test esté
  mal, es que la suite **cubre el móvil** aunque el fichero no sea del móvil.
- **Regla**: **tras tocar `mobile/lib/`, recompilar el APK antes de fiarse de la
  suite del bridge.** Es el mismo guardarraíl de A-061 funcionando, y su mensaje
  —«compílalo antes»— es literalmente la instrucción. Y si el rojo aparece en un
  fichero que no tocaste, antes de culpar al test: mira si el red es del proyecto
  entero, no del fichero.

## A-065 — Aprobar una instalación desde la app no instalaba nada

- **Qué pasó** (2026-10-03): se probó el flujo de actualización de verdad, con
  Aegis pidiendo la instalación y la persona aprobándola **desde el móvil**.
  Resultado: dos OK dados, ningún `POST /deploys/{id}/instalar` en el log, y
  `lastUpdateTime` del teléfono sin cambiar. **La app instalada seguía siendo la
  de antes.** La persona vio un error y no se le ocurrió que el botón estaba mal,
  porque desde dentro tiene toda la pinta de funcionar.
- **Por qué**: el bridge separa a propósito la aprobación de la instalación.
  `POST /deploys/{id}` emite el token; `POST /deploys/{id}/instalar` lo gasta
  **dentro del bridge** y arranca la instalación en un hilo aparte, para que el
  agente nunca llegue a verlo. El docstring de `deploy_aprobar` lo dice:
  «quien aprueba desde el móvil encadena las dos».
- **Y el cliente no las encadenaba**: `decideDeploy` era lo único que llamaba, y
  luego un `refrescar()`. El método `instalarDeploy` **no existía** en el repo
  del móvil. El contrato estaba escrito en el bridge y el cliente lo incumplía
  en silencio: no había ningún error, ningún aviso, ninguna llamada que delatara
  la falta.
- **Por qué es peor de lo que parece**: A-016 teachó que un veredicto que sale de
  `final_text` en vez de la traza es una mentira. Esto es lo mismo por el otro
  lado: **no fue el agente el que mintió, fue el cliente**. Un "hecho" en la
  interfaz con un "no instalado" detrás. Y el fallo solo se ve con el teléfono en
  la mano: los tests no lo cogían porque no había ningún test de este camino.
- **Regla**: **un endpoint que obliga a encadenar dos llamadas está partido, y la
  parte que encadena tiene que tener su propio nombre en el repositorio.** Si
  aprobar y ejecutar viven en el mismo método del cliente, no se puede aprobar sin
  instalar —y no se puede instalar sin que sea imposible saltarse la aprobación.
  La separación se puede quedar en el bridge; lo que no puede es *depender de que
  el cliente se acuerde* sin que se note si se olvida.
- **Y cuando el gesto es «ejecutar», el gesto tiene que ejecutar**: quien aprueba
  un despliegue a distancia no tiene a nadie a quien preguntar. Si tras pulsar
  "sí" no se dice nada, o se dice algo que no es lo que pasó, el fallo se come la
  confianza en todo lo demás.

## A-066 — Una acción, dos colas de aprobación: el 409 no era el fallo

- **Contexto** (2026-10-03): del mismo fallo que A-065, la parte que confundió el
  diagnóstico. Instalar en el teléfono pasa por **dos** puertas distintas:
  1. la de **autonomía**: `install_apk` es nivel 3, así que Aegis deja la petición
     `ok-…` y para con `fin: "esperando_ok"`;
  2. la de **despliegue**: `install_apk` tiene además su puerta interna
     (`deploy.py`), que exige verificación en verde y una autorización propia.
- **Lo que se vio**: aprobar la primera, pulsar «Ejecutar» → `409 Conflict`, tres
  veces. El 409 **no era el fallo**: era la consecuencia. El token de autonomía es
  de un solo uso, el primer «Ejecutar» lo gastó (correctamente), y los siguientes
  chocaban con «ese permiso ya se usó». La fila quedó `gastada` y sin token, que
  es exactamente lo que debe pasar.
- **El coste real**: el mensaje de `409` es *técnicamente* cierto y *prácticamente*
  engañoso. Dice «ya se usó», que es verdad, y no dice «la instalación se paró
  aquí porque le faltaba una segunda autorización», que es lo que pasó. Quien lo
  lee busca un token gastado por error y no llega nunca a la segunda puerta.
- **Regla**: **un 409 tiene que poder responder «por qué ahora no», no solo «por qué
  no antes».** Si una acción encadena puertas, el estado que se devuelve después de
  la primera tiene que señalar que **falta la siguiente**, con su nombre. Y el
  cliente, cuando una acción suya termina en un estado intermedio, tiene que ir a
  la siguiente puerta por su cuenta —o decir que se queda ahí, con el nombre de lo
  que falta.

## A-067 — La puerta puede pasar en verde y no dejar rastro de que pasó

- **De paso** (2026-10-03): `install_apk` con aprobaciónarlo todo transitioned a
  «no instalado» porque el APK ya estaba viejo… no: porque `pasar_puerta_deploy`
  comprobó sello, verificación y ruta, todo en verde, y aun así `pedir_deploy`
  dejó una segunda petición. La puerta **funcionó**: su trabajo era no instalar sin
  autorización, y no instaló.
- **Lo que faltaba era una afirmación**: la respuesta decía «NO INSTALADO, y es lo
  correcto» pero no decía **qué** faltaba ni en qué cola. Un mensaje de puerta
  cerrada que no dice por dónde se vuelve a entrar es una puerta que hay que
  buscar.
- **Regla**: **`NO INSTALADO` tiene que traer el siguiente paso con su id.** Ya lo
  trae el texto de `install_apk` (`id de petición: deploy-…`), y esa parte estaba
  bien: el problema era que **el cliente no la seguía**. La puerta es un contrato
  de ida y vuelta, y si el que tiene que dar el siguiente paso no lo da, el
  contrato está a medias por mucho que la puerta sea correcta.

## A-068 — La puerta que se pasa después de tu «sí» es una puerta en el sitio equivocado

- **Qué pasó** (2026-10-03): aprobar una instalación y esperar era esto: `flutter
  analyze`, `flutter test` y el humo en el emulador, **después** de que pulsaras
  «sí». El aviso decía «se instala en segundo plano», el Toast decía lo mismo, y
  luego venía un silencio de varios minutos. Y si la puerta se cerraba después,
  ese «sí» había servido para que approvingas una instalación que no iba a
  ocurrir.
- **La puerta se movió al compilar.** `build_apk` verifica y sella
  `<apk>.verificado` con la firma del **binario**; instalar solo comprueba que ese
  sello siga cuadrando y que el teléfono esté y alcance al bridge. Entre tu «sí» y
  el APK instalado queda un `adb install`.
- **Lo que no se puede mover al compilar**: que el teléfono **alcance** al bridge.
  Depende del cable, de Tailscale y de si la app está encendida, y cambia sin
  avisar. Verificarlo al compilar daría un verde que Caduca.
- **Lo que ya decía el texto**: el docstring de `instalar_pendiente` afirmaba
  «analyze, tests y humo ya se comprobaron cuando `install_apk` pidió la
  autorización». No era verdad: se comprobaban al instalar. El código ahora
  cumple lo que el docstring llevaba tiempo prometiendo.
- **Regla**: **una comprobación se pone donde el coste es gratis y el aviso
  todavía no está en la pantalla de nadie.** Compilar es gratis; instalar, con tu
  dedo puesto, no. Y si una puerta tiene partes que caducan y partes que no, se
  parte: cada mitad en su sitio, con un sello que ate la parte de arriba a la de
  abajo.
- **Corolario**: un `.sello` y un `.verificado` son dos preguntas y van en dos
  ficheros. En uno habrías tenido que elegir, y las dos respuestas se habrían
  mezclado: un APK compilado a mano nunca verificado habría pasado por verificado
  porque su código era el de ahora.

## A-069 — Un aviso por estado, y no dos avisos que se pisan

- **Qué pasó** (2026-10-03): había **dos** ids de notificación. `4101` para «necesito
  tu OK» y `4102` para el resultado. Solo se cancelaba el primero, y solo cuando
  otro aviso de pendientes veía la cola vacía. Resultado: **un aviso de un test se
  quedó en la bandeja sin forma de quitarlo**, y mientras tanto todos los avisos
  de resultado acababan en «AVISO NO VERIFICADO», porque `_hay_aviso_aegis` solo
  miraba el 4101 en `dumpsys`.
- **El argumento a favor de dos ids era bueno y el resultado, malo**: se separaron
  para que un «ya está» no borrara un «todavía necesito tu OK». Esa preocupación es
  real, pero se resolvió creando un estado que **nadie borra**, que es peor: un
  aviso que se queda para siempre enseñando algo falso entrena a ignorar los avisos.
- **Ahora hay un id y cuatro estados** —`pendiente`, `trabajando`, `hecho`,
  `fallo`, más `limpiar`— que se sustituyen **en sitio**. «No puede haber dos
  avisos de Aegis» deja de ser una intención y pasa a ser una propiedad. Y el
  riesgo que se temía se paga solo: el siguiente aviso de pendientes repinta el de
  decisión.
- **Y cada estado se retira solo**: los finales llevan `setTimeoutAfter(45 s)`.
  `setAutoCancel(true)` solo quita el aviso al tocarlo, que no es lo mismo que
  cuando deja de valer.
- **Regla**: **un aviso por operación, y su ciclo entero en el mismo sitio.** Un
  aviso tiene que poder *irse solo* cuando lo quedice dejó de ser cierto, y eso
  no puede depender de que llegue otro aviso que lo tape: si no hay nada nuevo
  que avisar, ese otro aviso no llega nunca.
- **Corolario**: el estado se ordena con un `ts` que pone **el puente**, no la hora
  del teléfono. Los broadcasts van por adb uno a uno pero sin orden entre llamadas
  distintas, y sin ese guardia un «instalado» tardío podía dejar la bandeja
  pidiendo un OK sobre algo ya hecho. Y se guarda en `SharedPreferences`, no en un
  `var`: el proceso es un `BroadcastReceiver` y Android lo mata cuando quiere.

## A-070 — Un toast que promete lo que no pasa es peor que un toast que no está

- **Qué pasó** (2026-10-03): el cuadro superpuesto (`OverlayActivity`) aprobaba,
  pintaba un Toast con «Aprobado. Se instala en segundo plano.» y cerraba. **No
  instalaba nada.** `POST /deploys/{id}` solo emite el token; el token lo gasta
  `POST /deploys/{id}/instalar`, y `Puente.instalar()` —que existía, con un
  docstring prometiendo el flujo entero— **no lo llamaba nadie**.
- **Y era el mismo fallo por los dos lados.** En Dart, `decideDeploy` sin
  `instalarDeploy` detrás (A-065). En Kotlin, `decidir` sin `Puente.instalar`
  detrás. Dos clientes, el mismo eslabón ausente, y el docstring de Kotlin
  describiendo un flujo que no ocurría.
- **La razón de fondo**: el token **no sale del bridge**, a propósito —se gasta
  dentro, que es lo único que hace que un token de un solo uso siga siendo de un
  solo uso—. Esa decisión obliga a que aprobar e instalar sean **dos** llamadas.
  Separarlas está bien; que se puedan olvidar por separado, no.
- **Regla**: **quien encadena las dos llamadas tiene que tener los dos métodos con
  nombre en su repositorio.** Si aprobar y ejecutar viven en el mismo método del
  cliente, no se puede aprobar sin instalar, y no se puede instalar sin saltarse
  la aprobación. La separación puede quedarse en el servidor; lo que no puede es
  *depender de que el cliente se acuerde* sin que se note si se olvida.
- **Y cuando el gesto es a distancia, el desenlace va al sitio que sobrevive a la
  app.** El `adb install -r` mata el proceso de la app por su cuenta: no hay que
  cerrar nada a mano, pero tampoco se puede mantener un widget con el resultado de
  algo que ya te ha matado. Por eso el estado vive en el aviso.

## A-071 — Fundir dos avisos debilita la verificación, si no se comprueba el estado

- **Qué pasó** (2026-10-03): al unificar los dos ids de notificación (A-069), la
  verificación dejó de comprobar nada. `_hay_aviso_aegis` miraba «¿hay una
  notificación de Aegis con `id=4101`?», y con un solo id eso es **siempre cierto**:
  el aviso del estado anterior sigue ahí mientras el nuevo se publica en el hilo
  del receptor.
- **Medido en el emulador**: tras pedir `hecho`, `dumpsys` seguía enseñando
  `AEGIS · EN MARCHA` y el puente respondía «aviso entregado y verificado».
- **Por qué con dos ids no pasaba**: el aviso de resultado usaba el 4102, así que
  encontrar el 4101 era justamente la prueba de que el aviso de decisión **no** se
  había tocado. Fusionar quitó esa propiedad por el camino, sin que se notara: el
  código era idéntico y la respuesta seguía siendo verde.
- **Regla**: **cuando una comprobación se debilita por un cambio estructural, hay
  que reescribirla, no dejarla como estaba.** Aquí «existe el aviso» pasó a no
  significar nada y la prueba siguió llamándose igual. Ahora se comprueba el
  **título** del estado pedido (`MARCA_ESTADO`).
- **Y el mock tenía el mismo agujero**: el `dumpsys` falso enseñaba un
  `NotificationRecord` sin título, así que cualquier estado nuevo daba «no
  verificado» —el fallo visible— mientras un mock que siempre dijera «está» habría
  pasado todo. Un doble que no puede fallar no es un doble.
- **Corolario**: **un «sí» que no se puede refutar es un «sí» que no comprueba
  nada.** Cuando una aserción pasa siempre, lo que se está midiendo es que el test
  no falla, no lo que dice medir.

## A-072 — Cuatro maneras de decidir a quién avisas, y la que nadie prueba está mal

- **Qué pasó** (2026-10-03): `avisar_intermedio` caía al emulador cuando no había
  teléfono, porque el aviso de decisión tiene que estar donde se decide. Los otros
  tres —`hecho`, `fallo` y `limpiar`— iban solo al teléfono.
- **Consecuencia medida**: en una máquina sin teléfono conectado, **el aviso
  atascado del emulador no se podía quitar nunca**. `limpiar` miraba el teléfono,
  que no existía, y se iba sin hacer nada diciendo «aviso limpiado».
- **Por qué es la clase de fallo que más cuesta ver**: la ruta del emulador no
  estaba rota en la máquina de trabajo —ahí sí había teléfono—, así que todo
  parecía bien. El fallo solo aparece donde el otro aparato no está, que es
  exactamente donde nadie mira porque ya no hay nada que mirar.
- **Regla**: **una decisión que se toma en varios sitios se toma en uno, y todos
  los sitios la llaman.** Cuatro copias no es robustez: es cuatro oportunidades de
  que una se quede sin probar. Y el helper se llama `_destino_aviso`, no
  `_destino_telefono`, porque la decisión ya no es «el teléfono».
- **Corolario**: cuando un aviso **tiene** que poder irse, comprobarlo en el caso
  fácil («hay teléfono, funciona») no dice nada del difícil («no hay teléfono»).
  Los dos casos van en el mismo test o en ninguno.

## A-073 — Un enfoque que solo va en el prompt es un consejo, y Aegis no los cumple

- **Qué se hizo** (2026-10-03): los enfoques dejaron de ser fases que elige la
  persona y pasaron a ser algo que **pide Aegis** con `usar_enfoque`, cuando su
  encargo no es todavía ejecutable. `idea` se borró a propósito.
- **Por qué `idea` fuera, y no por taste**: `metodo.md` ya lleva, en todos los
  runs, las seis preguntas para aterrizar una idea hasta poder escribir su ficha.
  Tenerlo además como enfoque era pagar dos veces lo mismo. Y una técnica de
  prompt que se aplica **siempre** no es un enfoque: es texto.
- **Lo importante es que tiene dientes**: `restringe` en el índice lo cumple
  `decide()` **antes que ningún nivel**, y el motivo nombra el enfoque y dice cómo
  salir. «No puedo escribir» es ruido —hay tres motivos y se arreglan de tres
  maneras—; «el enfoque arquitectura cierra esto, suéltalo cuando el diseño esté
  cerrado» cambia el comportamiento del 7B.
- **El `por_que` de `usar_enfoque` no es un comentario**: ES la subtarea de razonar
  el encargo, y su texto queda en la traza. Sin razonamiento previo, elegir un
  enfoque es adivinar con palabras — y un adivino bien escrito es indistinguible
  de uno pensado.
- **Regla**: **una instrucción que Aegis debe cumplir bajo presión va en el código
  que ejecuta, no en el prompt.** El prompt es lo que el modelo *intenta*; la
  autonomía es lo que decide.

## A-074 — El presupuesto se comprueba al pedir, no al cargar

- **Qué pasó** (2026-10-03): con un solo enfoque el tope no se notaba, y el test
  que lo cubría daba verde con cualquier tope. `cabe(n, ())` con la lista vacía
  **no puede fallar nunca**: la pregunta no es «¿cabe este?», sino «¿cabe este
  encima de lo que ya llevas?».
- **Por qué importa de verdad**: A-016 midió que el prompt es el presupuesto.
  Un único bloque de 2600 caracteres pasaba al cargarse y podía ser el segundo
  de 2600 más 2600. El tope se evalúa **en cada petición**, contra lo ya gastado.
- **Regla**: **un presupuesto se comprueba acumulando, no de una en una.** Y un
  test que solo mira el caso vacío está midiendo la nada.
- **Y el motivo del rechazo lleva las cifras.** «No cabe» sin decir cuánto es
  esconde el motivo; y un aviso que no dice por qué hay que buscarlo es la clase
  de error que este repo ya pagó dos veces (A-042, A-055).

## A-075 — Meter una tool se mide, no se supone

- **Contexto** (2026-10-03): hacer que Aegis pida su enfoque significa meter una
  tool más en el schema, y A-016 avisaba de que los modelos de 6 GB rinden peor
  con muchas tools. Eso era una afirmación sobre el *prompt*; el número de tools es
  otra variable.
- **Cómo se midió**: `bin/probe-toolcall.sh` acepta ahora un tercer argumento, el
  número de tools, y las saca de `_tools_schema()` —las reales, no unas inventadas,
  porque un número inventado mediría otra cosa.
- **Resultado**: con **19** tools emite `tool_calls` en no-stream y en stream; con
  **20** emite `tool_calls` reales en no-stream, dos veces seguidas. El autopilot
  usa `stream: false`, así que la puerta que importa pasa. En stream los deltas
  salieron a 0 con 20; anotado, no bloqueante, y conviene mirarlo si algún día se
  emite en stream.
- **Regla**: **antes de añadir una tool, medir antes y después.** El instrumento
  ya existía para una tool; seBuddó a N porque una tool no mide un cambio de
  cantidad.

## A-076 — Un agente que «sí o sí» trabaja en un proyecto, porque su método lo dice

- **Qué pasó** (2026-10-03): Aegis tenía que servir para el uso cotidiano —una
  pregunta, una nota, mirar algo— y no había forma: la fila de proyecto pintaba el
  primero de la lista cuando no había ninguno elegido, así que la app **parecía**
  siempre trabajando en `aegis`, y «sin proyecto» no aparecía por ninguna parte.
- **Pero la causa de fondo estaba en el prompt, no en la pantalla**: `metodo.md` se
  inyectaba **siempre** y estaba escrito entero como si hubiera siempre un proyecto
  —«el verificador del proyecto», «pruebo en el emulador», «tu teléfono»—. Eso no
  solo recarga prompt: **le dice a Aegis que todo encargo es trabajo en un repo**,
  que es la instrucción equivocada impresa en el sitio con más peso que tiene.
- **Arreglo**: `metodo.md` y `metodo_proyectos.md`, y el segundo solo entra con
  proyecto. Sin proyecto el prompt baja de 3571 a 1975 caracteres: **−45%**. Y la
  fila dice «Sin proyecto», que se puede soltar con un toque sin abrir nada.
- **Regla**: **un agente demuestra para qué sirve con lo que le metes en el prompt,
  no con lo que su interfaz permite.** Si el método dice que todo es un repo, la
  pantalla puede ofrecer «sin proyecto» y seguir siendo un agente de repos.
- **Corolario**: una variable llamada como lo contrario de lo que comprueba
  (`pendiente` significando «no hay que avisar») no cuesta nada hasta que alguien
  la lee al revés.

## A-077 — Medido: el 7B **razona** el enfoque y no lo pide

- **Qué se probó** (2026-10-03): tres runs con el encargo «qué motor de base de
  datos uso, postgres o sqlite, quiero dos opciones con el por qué», sin enfoque
  fijado.
- **Resultado**: **ninguno pidió el enfoque.** Los tres fueron distintos y los tres
  mal:
  1. `repair`, `repair`, y luego inventó la tool `verificar_check`, que no existe,
     y acabó con ella de respuesta.
  2. Escribió en prosa: «Apriori no hay un enfoque activo»,}y se inventó uno
     llamado `basado_en_tamaño_y_complejidad` en Markdown, sin llamada.
  3. Respondió **en chino**, sin pedir nada.
- **Lo importante es que el modelo sí razona bien**: en el segundo dijo
  literalmente que no hay enfoque activo y que el método estándar es lo que
  aplica. La comprensión está; lo que falta es la acción.
- **Y no es el peaje de A-016**: `probe-toolcall.sh` con **20 tools** emite
  `tool_calls` reales en no-stream, dos veces seguidas. Saber llamar tools y
  **elegir** llamar una son dos cosas distintas, y aquí falla la segunda.
- **Por qué el runway de reparación no lo rescata**: `_mentions_tool` solo dispara
  si el texto nombra una tool. Un modelo que razona en prosa sin nombrarla llega a
  `fin: sin_tools`, y su propio razonamiento —que era correcto— se queda en la
  respuesta en vez de convertirse en llamada.
- **Regla**: **«el agente puede hacer X» no es lo mismo que «el agente elige X».**
  Una capacidad nueva necesita medirse por las dos partes: que sepa, y que la
  escoja. Aquí se midió la primera (20 tools, `tool_calls` reales) y se creyó que
  cubría la segunda. No la cubría.
- **Lo que sí funciona, y es determinista**: el enfoque **fijado**. Entra en el
  prompt con su título y sus tools cerradas, y `decide()` las niega antes de
  ejecutarlas. Ese camino no depende de que un 7B se acuerde.
- **Lo que queda sin decidir**: si además el bridge **deriva** el enfoque del
  encargo y se lo da a Aegis diciendo por qué —`enfoques.derivar()`, ya escrito y
  sin usar—, la capacidad deja de depender del modelo. Es la opción que se
  descartó al elegir «que lo pida Aegis», y la medición es el dato nuevo: no es
  que sea peor, es que con este modelo no dispara.

## A-078 — Resuelto: el bridge propone y Aegis corrige

- **Decisión** (2026-10-04): el puente deriva el enfoque del encargo
  (`enfoques.derivar()`, señales del `_indice.json`) y lo pone con su motivo
  **escrito en la traza**; Aegis conserva la tool para **corregirlo** —
  `usar_enfoque(nombre='')` lo suelta, `usar_enfoque(nombre, por_que)` pide otro.
- **Medido, mismo encargo de A-077**: el bloque entró, la respuesta siguió la
  estructura del enfoque («requisitos no funcionales», «coste de cambio»), y en ese
  run Aegis **además lo pidió** con la tool en el paso 1. Los dos caminos coinciden;
  ya no dependemos de que el segundo llegue.
- **Y lo que cuesta**: el enfoque se propone sin que nadie lo pidiera. Por eso la
  traza lleva `propuesto_por: "bridge"` y el prompt dice «No lo pediste tú». Una
  propuesta que no se puede leer como propuesta es un impose con log.
- **Lo que casi se cuela**: el enfoque lo fija una regla, y una regla se equivoca.
  Las tres salidas son soltar, corregir, y no proponer cuando no hay señal —que es
  lo que hace `derivar()` devolviendo `None`. Un enfoque equivocado cierra tools de
  más, así que el `None` es la respuesta por defecto y no un caso raro.
- **Lo que salió de escribir el test**: la entrada del paso 0 se escribía en `trace`
  y una línea más abajo una re-declaración la **borraba**. El enfoque se aplicaba de
  verdad y era invisible en `GET /autopilot/{run_id}`: lo que se leía no era lo que
  había pasado. Por eso `_sembrar_enfoque()` es una función pura que **devuelve** la
  entrada en vez de escribirla — si el test necesita un modelo delante, tarde medio
  minuto y acabe sin comprobarse.
- **La puerta, comprobada aparte**: con `arquitectura` activo, `aegis_write_file` y
  `aegis_patch_file` se niegan **antes** de mirar el modo, y el motivo dice cómo
  soltar el enfoque. Sin enfoque, la misma escritura se cae por `solo`, que es un
  motivo distinto y el correcto.

## A-079 — Un `fin` que no está no es un `fin`: es un `KeyError` esperando

> Aplica cuando: cuando devuelvas el resultado de un run, por el camino que sea

- **Qué pasó** (2026-10-04): la parada por verificador devolvía un dict **sin
  `fin`**, y quien lo consumía hacía `result["fin"]`. El `KeyError` se comía el
  motivo real y el run se guardaba como `failed` con el error `'fin'`. O sea: la
  puerta que existe para explicarle las cosas al agente era lo que le impedía
  explicarle nada. Dos de los tres `return` del bucle traían `fin`; el tercero se
  escribió después y se olvidó.
- **Y de paso, dos cosas que nadie miraba**:
  - Una **base en rojo** no paraba el run: `decide()` devolvía un «no» sin más, el
    bucle lo leía como respuesta («sigue con otra cosa») y el run se consumía
    entero —16 pasos— denegando la misma escritura. Ahora el «no» puede decir que
    es un tope.
  - Un **Ollama que no responde** se llevaba el run entero, sin traza ni episodio,
    porque `_escribir_jsonl_de_autopilot` y `remember()` estaban **después** del
    run y sin ningún `try`. Lo que se perdía no era un dato: era el aprendizaje.
- **Regla**: **todo `return` de un bucle lleva su motivo, y el motivo se escribe en
  la lista cerrada de `docs/runbook.md` §1.1.** Un motivo que no está en la lista
  no existe; uno que no se escribe, tampoco.
- **Y la de más fondo**: **toda salida tiene que dejar rastro, incluso la
  exception**. `except` que escribe es infraestructura; `finally` que registra es un
  diario. Un fallo que no deja rastro es un fallo que no se puede ni detectar
  ni corregir, y todo este repo está montado para que los fallos se puedan
  corregir.

## A-080 — Medir dos prompts alternando, o medir ruido

- **Qué pasó** (2026-10-04): al reemplazar las 120 KB de lecciones por un índice
  de 8 000 caracteres, la puerta que yo mismo había fijado («latencia en frío
  ≤ 15 s») **no se cumplió: 20,0 s**. La primera reacción fue pensar que el
  arreglo no valía. No era verdad: la medición estaba mal hecha.
- **El fallo de medición**: comparé «con lecciones» contra un número absoluto
  medido **en otra sesión**. La misma variante sin lecciones dio 10,5 s en una
  tanda y 14,8 s en otra, con la máquina igual: **±4 s de deriva**. Con ese
  ruido, cualquier umbral absoluto de segundos es inventado.
- **La medición que sí sirve**: alternar las dos variantes **en el mismo
  proceso**, que es lo que hace que la deriva afecte a las dos por igual. Resultado
  intercalado: índice 11,9 s, sin lecciones 10,1 s → **+1,8 s (+17%)** por
  llamada. El coste real del índice es un 17%, no 20 s.
- **Regla**: **un umbral absoluto solo vale si el ruido está por debajo del
  efecto**. Si no lo está, el criterio es relativo (cuánto más que la línea
  base) o la comparación es intercalada. Y antes de descartar un arreglo por una
  puerta que falla, comprobar que la puerta mide lo que dice medir: esta medía el
  reloj de la máquina, no el arreglo.
- **Y una segunda, más incómoda**: el motivo por el que las 120 KB salían tan
  caro no era solo el tamaño, sino que **el prompt entero se re-evalúa en cada
  paso**. 120 KB × 16 pasos es media hora de reloj por run. Un coste que se paga
  por paso es un coste que multiplica, y es el que hay que mirar primero.

## A-081 — Una tool que no está en el schema no se puede llamar

- **Qué pasó** (2026-10-04): al medir si quitar 11 tools de las 21 mejoraba el
  autopilot, la variante corta sacaba **0/5 tool calls** y la larga **5/5**, con
  la mitad de latencia. Leído en frío, «quitar tools hace que el modelo no llame
  a ninguna» parece un argumento definitivo para la poda. Era **al revés**: mi
  conjunto de 9 tools no incluía `aegis_read_file`, que es exactamente la que el
  encargo pedía. Le pedí una
  herramienta que no tenía, y el 7B respondió con texto, que es lo correcto.
- **Por qué no se vio**: el 0/5 era **demasiado bueno**. Un recorte de schema que
  rompe las tool calls empeora la tasa de acierto; una mejora de 5/5 a 0/5 suena
  a que el recorte funciona. Cuando un experimento sale mejor de lo posible, la
  lectura por defecto es que el experimento está mal, no que el efecto sea real.
- **La medición buena**: con las 10 tools (las 9 usadas alguna vez en 350 runs más
  la del encargo), intercalado, **5/5 en ambas** y 24,3 s → 15,2 s. O sea: quitar
  8,7 KB de schema ahorra el 37 % de la latencia del primer token **sin medirse
  pérdida de tool-calling** en una tarea de lectura.
- **Lo que NO midió**: n=5 y un solo tipo de tarea. A-016 degradó al 7B con
  encargos compuestos, no leyendo un fichero. **5/5 en la tarea fácil no es 5/5
  en las difíciles**, así que la conclusión honesta es «el schema se puede
  encoger sin coste medido», no «las tools sobran y se pueden borrar».
- **Regla**: antes de comparar dos schemas, comprobar que **la tool que el encargo
  nombra existe en los dos**. Un experimento mal armado produce un número
  impecable y una conclusión invertida, y el número es lo que se cita después.

## A-082 — Una tool que duplica otra no es una función, es un coste

- **Qué pasó** (2026-10-04): al meter `quien-eres.md` (lo que Aegis sabe del
  usuario) añadí dos tools: `quien_eres(tema)` para leer y
  `quien_eres_actualiza()` para escribir. El schema del prompt subió de 18 682 a
  **21 173** caracteres: +2 491, el 13%, en cada paso de cada run.
- **La observación que lo dejó claro**: la mitad del coste era una tool **que
  duplicaba `aegis_read_file`**, que ya existe, ya está en el schema y ya es de
  nivel libre. El fichero está en disco; leerlo era una llamada que ya se podía
  hacer. Lo único que aportaba `quien_eres` era un `## ` con el nombre de la
  sección.
- **El riesgo de quitarla** —y el test lo cazó—: sin tool propia, **el modelo no
  sabe que el fichero existe**. La sección inyectada decía «pídelo con
  `quien_eres(tema)`»… en un comentario HTML que el parser se come, o sea donde
  el modelo no lo lee. La solución no fue devolver la tool: fue **una línea en el
  bloque que ya se inyecta** diciendo que se lea con `aegis_read_file`. 70
  caracteres en el prompt, frente a 1 500 en el schema que se pagan aunque la tool
  no se use. Schema final: 20 033 (+1 351, por la tool de escritura, que sí
  aporta: es el guardarraíl de nivel 3).
- **Medido, el bloque de 543 caracteres no cuesta nada** (intercalado, como
  A-080): 12/12 tool_calls con y sin él, y la mediana de latencia **se dio la
  vuelta** entre las dos tandas (primero +2,3 s, después −1,6 s). Con un ruido de
  ±4 s en esta máquina, un signo que cambia es la definición de «no medible».
- **Regla**: antes de añadir una tool, mirar si ya hay una que haga eso. Y al
  elegir entre «tool nueva» y «una línea en el prompt», tener presente que **el
  schema se paga aunque la tool no se use** (A-081: 8,7 KB de schema eran el 37 %
  de la latencia). Una tool que solo ahorra escribir el nombre del fichero no
  sale a cuenta.
- **Y la parte incómoda**: la primera medición dio +2,3 s y casi sale en el
  commit como «el bloque cuesta un 15%». Con n=5 y ±4 s de ruido, ese número no
  distinguía nada. Repetido a n=12 por variante, la diferencia no solo desapareció:
  cambió de signo. A-080 ya lo había escrito y no lo había aprendido del todo.
