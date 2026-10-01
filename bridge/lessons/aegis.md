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
| 2026-09-30 | `app/fichas.py` (**yo**) | el filtro de comentarios era de una línea y las subsecciones `###` rellenaban su `##`: la puerta se abría sola | A-018 |
| 2026-09-30 | `.gitignore` (**yo**) | `data/` sin ancla también excluía `mobile/lib/data/`: la capa de datos de la app nunca estuvo versionada y el móvil no compilaba desde un clone | A-017 |



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

