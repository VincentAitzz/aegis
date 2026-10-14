"""Quién es el usuario, leído de disco.

Existe porque Aegis es el que ejecuta y hay cosas que solo puede saber quien
decide. La respuesta de OpenClaw a esto es un `USER.md` inyectado en cada turno.
Aquí **no**, y la razón está medida en este repo:

- A-016 midió que el 7B deja de emitir `tool_calls` cuando el prompt crece.
- A-080 Campaigns lo mismo en otro sitio: el prompt se **re-evalúa en cada
  paso**, así que un bloque grande es un coste que multiplica.
- El peor caso del system prompt está en **7 953** caracteres y el test que lo
  vigila está en 30 000. Antes eran 17 155: las lecciones eran 9 200 de ellos.
  El margen se descargó quitándolas, no recortando este fichero.

Por eso el fichero se parte en dos:

- la sección `RESUMEN` entra en **todos** los runs, con tope de `MAX_RESUMEN`;
- el resto del fichero **no se inyecta nunca**: se lee con
  `aegis_read_file('quien-eres.md')`, que ya existe. Por eso este módulo no
  necesita ninguna tool de lectura propia: duplicarla costaría ~1 500 caracteres
  de schema en cada paso de cada run, y el schema se paga aunque no se use.

Lo que va en el resumen no es «saberlo todo de ti», es lo que pesa: cómo quieres
que te hable y qué no quieres que Aegis decida. Eso son unos 450 caracteres. La
biografía se consulta cuando hace falta, y casi nunca hace falta.

**Quién escribe aquí.** Aegis puede, con `quien_eres_actualiza` (nivel 3, o sea
con tu OK) y tú puedes con cualquier editor. Deliberadamente **no** es una tool
libre: en el ecosistema de OpenClaw, poder reescribir tu propio `USER.md` es la
vulnerabilidad documentada —ClawHavac atacó precisamente esos ficheros con
base64 y caracteres de ancho cero—, porque un cambio persistente en el prompt
sobrevive a cualquier chat y a cualquier reinicio. Con nivel 3 la diferencia es
que lo apruebas tú y queda el motivo en la traza.

El canal privado por proyecto ya existía y sigue sin usarse:
`fichas-privadas/{alias}.md`, con su «no lo nombres ni lo repitas». Para PII de
clientes, esa sigue siendo la vía; este fichero es sobre cómo hablamos.

**Y el fichero no viene en el repo.** `quien-eres.md` está en `.gitignore` porque
es la respuesta a «quién eres», y esa respuesta es de quien lo instala, no del
proyecto. El repo trae `quien-eres.ejemplo.md` y `infra/setup.sh` lo copia al
arrancar. Si no está, este módulo devuelve `""` y Aegis sigue: el prompt se
construye con `metodo.md` y la ficha del proyecto, que son las dos cosas que sí
son del proyecto.
"""

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
QUIEN_PATH = BASE / "quien-eres.md"

#: La plantilla que sí viaja en el repo. `infra/setup.sh` la copia a
#: `QUIEN_PATH` en el primer arranque, y `.gitignore` excluye el destino: lo que
#: Aegis sabe de ti no es del proyecto, es tuyo.
PLANTILLA_PATH = BASE / "quien-eres.ejemplo.md"

#: La sección que se inyecta en todos los runs. Su **nombre** es el contrato:
#: si alguien reordena el fichero, lo que se inyecta no cambia.
RESUMEN = "Cómo hablo contigo"

#: Tope del bloque inyectado. Un bloque que se trunca a la mitad es peor que uno
#: corto: la instrucción que se pierde es la que no se va a cumplir, y no hay
#: forma de saber cuál era.
MAX_RESUMEN = 600

_HEAD = re.compile(r"^##\s+(.+?)\s*$")
_COMENTARIO = re.compile(r"<!--.*?-->", re.S)
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)

_CACHE: dict[str, str] = {}


def _leer() -> str:
    """El fichero entero, o cadena vacía si no está.

    Vacía y no excepción, como `method.py`: un fichero ausente no puede tumbar un
    run, y este módulo tiene que cargarse en despliegues mínimos.
    """
    if "texto" not in _CACHE:
        try:
            _CACHE["texto"] = QUIEN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            _CACHE["texto"] = ""
    return _CACHE["texto"]


def limpiar_cache() -> None:
    """Para los tests: si no, el fichero se lee una vez y no vuelve a cambiar."""
    _CACHE.clear()


def secciones() -> dict[str, str]:
    """Cada sección `## ` por nombre, con comentarios HTML fuera.

    Los comentarios se quitan porque quien rellena esto deja preguntas en un
    `<!-- -->`, y una pregunta sin responder no puede acabar en el prompt de un
    modelo como si fuera una instrucción.
    """
    texto = _COMENTARIO.sub("", _FRONTMATTER.sub("", _leer()))
    salida: dict[str, str] = {}
    nombre = ""
    for linea in texto.splitlines():
        encaja = _HEAD.match(linea)
        if encaja:
            nombre = encaja.group(1).strip()
            salida.setdefault(nombre, "")
        elif nombre:
            salida[nombre] += linea + "\n"
    return {k: v.strip() for k, v in salida.items() if v.strip()}


def resumen() -> str:
    """La sección que va en todos los runs, con tope.

    Si no existe la sección o está vacía, devuelve "" — no un error. El prompt
    tiene que poder construir sin este fichero, como con `metodo.md`.
    """
    cuerpo = secciones().get(RESUMEN, "")
    if not cuerpo:
        return ""
    if len(cuerpo) <= MAX_RESUMEN:
        return cuerpo
    cortado = cuerpo[:MAX_RESUMEN].rsplit("\n", 1)[0].rstrip()
    return (cortado + f"\n[…truncado en {MAX_RESUMEN} chars. El resto está en "
            f"`{QUIEN_PATH.name}`, se lee con aegis_read_file.]")


def contexto() -> str:
    """Bloque listo para inyectar en el system prompt."""
    cuerpo = resumen()
    if not cuerpo:
        return ""
    return (f"CONTIGO Y CÓMO TRATO DE TRATARTE (aplica siempre):\n\n{cuerpo}")


def por_tema(tema: str = "") -> str:
    """Lo que se devuelve al leer el fichero, para lo que no entra siempre.

    Sin tema, devuelve el fichero entero: quien pide el perfil sin saber qué
    busca se lo lleva completo, y son 2 KB.
    """
    libres = secciones()
    if not tema.strip():
        # Con nombre de sección, para que quien lee sepa qué está mirando. Y sin
        # el resumen: ya va en el prompt de este mismo run, y repetirlo aquí es
        # pagar dos veces por lo mismo.
        partes = [f"## {n}\n\n{c}" for n, c in libres.items() if n != RESUMEN]
        return "\n\n".join(partes) if partes else ""
    palabras = {p for p in re.findall(r"[\wáéíóúñü]{4,}", tema.lower())}
    puntuados: list[tuple[int, str, str]] = []
    for nombre, cuerpo in libres.items():
        if nombre == RESUMEN:
            continue  # ya va siempre: no se repite bajo demanda
        del_titulo = len(palabras & {p for p in re.findall(r"[\wáéíóúñü]{4,}", nombre.lower())})
        del_cuerpo = len(palabras & {p for p in re.findall(r"[\wáéíóúñü]{4,}", cuerpo.lower())})
        if del_titulo or del_cuerpo:
            puntuados.append((del_titulo * 3 + del_cuerpo, nombre, cuerpo))
    if not puntuados:
        return ""
    puntuados.sort(key=lambda t: (-t[0], t[1]))
    _, nombre, cuerpo = puntuados[0]
    return f"## {nombre}\n\n{cuerpo}"


def actualizar(seccion: str, texto: str) -> str:
    """Escribe o reemplaza una sección. **Se llama solo con tu aprobación.**

    ## Por qué reescribir y no añadir al final
    Se reconstruye el fichero entero desde sus secciones, así que dos ediciones
    seguidas no dejan lo de la primera duplicado. Es lo contrario de un append a
    ciegas, que con dos correcciones del mismo tema produce un fichero donde la
    mitad son contradicciones que nadie va a leer.

    ## Lo que se puede tocar
    También la sección `RESUMEN`, que va en todos los runs. Es el caso más natural:
    «háblame más corto» es exactamente esa sección. Lo que no se hace es tocarlo
    callado — el argumento de la tool lleva el texto entero, así que la aprobación
    lo enseña, y el valor de retorno dice lo que va a costar en cada paso.

    ## Lo que no se permite
    Meter un encabezado `## ` dentro del texto: partiría la sección en dos, y una
    sección partida es un bloque inyectado a medias.
    """
    nombre = (seccion or "").strip()
    cuerpo = (texto or "").strip()
    if not nombre:
        return "Falta el nombre de la sección."
    if not cuerpo:
        return f"La sección «{nombre}» quedaría vacía. Un encabezado sin contenido no dice nada."
    if _HEAD.match(nombre) or any(line.startswith("## ") for line in cuerpo.splitlines()):
        return ("El texto no puede contener encabezados `## `: partirían la "
                "sección en dos y el prompt recibiría medio bloque.")

    original = _leer()
    if not original:
        return (f"No encuentro {QUIEN_PATH.name}. Sin ese fichero, Aegis no sabe "
                "nada de ti y no hay dónde escribir.")

    actuales = secciones()
    if nombre not in actuales:
        texto_final = _reensamblar(original, nombre, cuerpo)
        accion = f"Añadida la sección «{nombre}» ({len(cuerpo)} chars)"
    else:
        texto_final = _reensamblar(original, nombre, cuerpo)
        accion = (f"Reescrita «{nombre}» ({len(actuales[nombre])} -> "
                  f"{len(cuerpo)} chars)")

    try:
        QUIEN_PATH.write_text(texto_final, encoding="utf-8")
    except OSError as exc:
        return f"No pude escribir {QUIEN_PATH.name}: {exc}"
    limpiar_cache()
    return (f"{accion}. Ahora mismo el prompt recibe {len(resumen())} chars de "
            "este fichero.")


def _reensamblar(original: str, nombre: str, cuerpo: str) -> str:
    """El fichero entero con una sección puesta, sin tocar el resto.

    Se reconstruye desde el texto original, no desde `secciones()`, para no perder
    los comentarios HTML de quien lo rellena: son notas para la persona, y el
    parseo se come a propósito.
    """
    patron = re.compile(r"^(##\s+" + re.escape(nombre) + r"\s*$.*?)(?=^##\s|\Z)",
                        re.M | re.S)
    sustituto = f"## {nombre}\n\n{cuerpo}\n"
    if patron.search(original):
        return patron.sub(lambda _m: sustituto, original, count=1)
    return original.rstrip("\n") + f"\n\n## {nombre}\n\n{cuerpo}\n"

