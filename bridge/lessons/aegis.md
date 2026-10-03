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
