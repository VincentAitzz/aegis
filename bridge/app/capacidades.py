"""Qué puede hacer Aegis: **una sola fuente de verdad**, deducida del código.

Existe porque se midió que no:

    «hola aegis, soy tu creador, cuentame un poco cuales son tus funciones»
      → 161 s · fin=esperando_ok
      → tools: [ficha_read, ficha_read, projects_list, project_create]

No llamó a ninguna tool para contestarlo: **se lo inventó**, y además decidió
que lo propio de un creador es darle un proyecto: llamó a `project_create` para
`mi-proyecto`, un proyecto que no existe en ninguna parte. Solo lo frenó que
`project_create` sea de nivel 3.

Lo mismo, en corto:

    «hola, que puedes hacer?»  → 56 s · fin=sin_tools · respuesta inventada
    «gracias, eso era todo»    → 27 s · fin=sin_tools

## Lo que este módulo arregla, y lo que no

Arregla **que la respuesta sea verdad**: la lista sale de las tools que existen,
de su nivel real y de su propósito real, no de lo que el modelo recuerde. Y sale
**sin pagar un modelo**: 0,02 ms en vez de 161 s.

**No arregla** que Aegis entienda cualquier frase. Eso no se arregla con más
patrones, y este módulo no lo intenta: lo que hace es que, para la pregunta que
más se le hace a un sistema —*qué sabes hacer*— la respuesta sea la del código y
no la de su memoria.

## Por qué el test es lo importante

`test_toda_tool_tiene_descripcion` falla si añades una tool y no la describes. Sin
él, esta lista se queda vieja y Aegis vuelve a contestarte lo que puede hacer en
octubre. **Una lista de capacidades que nadie ata al código es una lista de
capacidades inventadas**, que es exactamente el fallo que este módulo arregla.

## Y por qué esto no es un prompt

Porque ayer quitamos 9 200 caracteres de lecciones por no hacer nada, y añadir
otro bloque que se paga en cada paso para contestar una pregunta que se hace una
vez sería el mismo error con la caldería puesta al revés. Esto se llama como
función y se pinta como función.
"""

from __future__ import annotations

import re

#: Qué es cada grupo, para el texto que se pinta. La descripción **vive aquí**,
#: junto al nivel, no en el schema: el schema lo paga el modelo en cada paso.
GRUPOS = {
    "libre": ("Lo que hago sin preguntar", "leer y comprobar. Nada de esto cambia nada."),
    "con_permiso": (
        "Lo que hago si me lo has marcado",
        "escribir código en un proyecto que tengas marcado para escritura, "
        "pasando siempre por su verificador."),
    "requiere_ok": (
        "Lo que te pregunto antes de hacerlo",
        "siempre, en todos los modos. Que lo apruebes una vez no lo hace "
        "automático la siguiente."),
    "camino_rapido": (
        "Lo que contesto sin gastar modelo",
        "horas, fechas, tus proyectos y notas. Instantáneo."),
}


def _una_linea(texto: str) -> str:
    """La primera frase útil del docstring de una tool.

    Los docstrings de este repo son largos a propósito, y están escritos para
    quien los lee en el código. Pintarlos enteros aquí sería un muro; quedarse
    con la primera frase pierde el matiz que dice si hay puerta.

    Se corta en el primer punto del **primer párrafo**, que es donde el autor
    pone la idea, y no en el primer punto de la línea: «Ver docs/x.md» no es una
    frase.
    """
    if not texto:
        return ""
    parrafo = texto.strip().split("\n\n", 1)[0]
    parrafo = " ".join(parrafo.split())
    m = re.search(r"(?<=[a-záéíóúñ])\.\s", parrafo)
    return parrafo[: m.start() + 1].strip() if m else parrafo


def _nombres_de_tools() -> list[str]:
    """Los nombres que de verdad están en el schema del MCP.

    Se lee del propio `FastMCP`, no de una constante escrita a mano. Una lista
    escrita empieza a mentir el día que añades una tool, y lo hace **en
    silencio**: todo lo demás sigue verde porque no hay nada que se rompa.

    `list_tools()` devuelve objetos `Tool`, no cadenas. Se queda con `.name` y
    se filtra lo que venga por si el servidor MCP cambia de versión —que es
    exactamente lo que pasó la primera vez que se escribió esto.
    """
    from . import mcp_ops
    try:
        herramientas = mcp_ops.mcp._tool_manager.list_tools()
    except Exception:  # noqa: BLE001 — sin MCP, se cae al scanner del módulo
        import inspect
        return sorted(n for n, f in inspect.getmembers(mcp_ops, inspect.isfunction)
                      if getattr(f, "__doc__", None) and n not in ("_p",))
    nombres = [getattr(h, "name", h) for h in herramientas]
    return sorted(str(n) for n in nombres if isinstance(n, str))


def descripcion_de(nombre: str) -> str:
    """Lo que hace la tool `nombre`, en una línea. Vacía si no se puede."""
    from . import mcp_ops
    fn = getattr(mcp_ops, nombre, None)
    if fn is None:
        return ""
    return _una_linea(fn.__doc__ or "")


def capacidades() -> dict[str, list[dict[str, str]]]:
    """Las tools reales agrupadas por su nivel de autonomía. Sin escribir nada."""
    from .autonomy import CON_PERMISO, LIBRES, REQUIERE_OK

    grupos: dict[str, list[dict[str, str]]] = {g: [] for g in GRUPOS}
    for nombre in sorted(_nombres_de_tools()):
        nivel = ("libre" if nombre in LIBRES else
                 "con_permiso" if nombre in CON_PERMISO else
                 "requiere_ok" if nombre in REQUIERE_OK else "libre")
        grupos[nivel].append({"nombre": nombre,
                              "que_hace": descripcion_de(nombre)})
    return grupos


def identidad_para_el_prompt() -> str:
    """Quién es Aegis, en un párrafo, **dicho por el código**.

    ## Por qué hace falta, medido
    Sin esto, el 3B contesta de memoria y se equivoca en las dos formas que un
    asistente no puede equivocarse. Medido el 2026-10-14:

        «cuéntame qué puedes hacer»
          → «Puedo ayudarte con una amplia variedad de tareas relacionadas con la
             seguridad de la información» (32 000 chars de alucinación)

        «revisa el repositorio aegis y dime si el verificador está en verde»
          → «Sigo revisando el repositorio de Aegis. Verificando… Está en verde.»

    La segunda es la grave: **afirma haber hecho un trabajo que no hizo**. Sin
    tools y sin traza no hay forma de corregirla a posteriori, así que la única
    defensa es que no tenga con qué mentir: la lista de lo que puede hacer se la
    da el mismo código que la ejecuta.

    ## Y por qué aquí y no una tool que la pida
    Porque medido, con el schema de 21 tools delante, el modelo **llama a una
    tool aunque no haga falta**: un «hola, ¿qué tal?» produce una llamada a
    `quien_eres_actualiza`. La identidad no se pide, se da.

    ## Coste
    ~1 900 caracteres, estables byte a byte —que es lo que hace que entren en la
    caché de prefijo—, contra los 19 649 del schema de tools.
    """
    from .autonomy import LIBRES, REQUIERE_OK
    cuenta = f"{len(LIBRES) + len(REQUIERE_OK) + 2} herramientas"
    return (
        f"Eres **Aegis**, un asistente que vive en la máquina de quien te creó, "
        f"sin nube y sin cuenta. Tienes {cuenta} y unas pocas frases que "
        f"contestan al instante. No tienes cuerpo, ni piernas, ni dudas: "
        f"hablas corto y de lo que sabes."
    )


def como_texto(ancha: bool = False) -> str:
    """El texto que se le enseña a quien preguntó qué puede hacer.

    `ancha=True` incluye la descripción de cada tool. Pone el motivo ahí, no en
    el prompt de cada run, porque **solo se paga cuando alguien pregunta**.
    """
    from .intents import INTENTS

    g = capacidades()
    lineas = [
        "Soy Aegis. Funciono en tu máquina, sin nube y sin cuenta.",
        "",
    ]
    for clave in ("libre", "con_permiso", "requiere_ok"):
        if not g.get(clave):
            continue
        titulo, nota = GRUPOS[clave]
        lineas += [f"**{titulo}**", nota, ""]
        for t in g[clave]:
            if ancha and t["que_hace"]:
                lineas.append(f"- `{t['nombre']}` — {t['que_hace']}")
            else:
                lineas.append(f"- `{t['nombre']}`")
        lineas.append("")

    # El camino rápido se lista con su ejemplo, no con su nombre de tool:
    # `tarea_crear` no le dice nada a nadie, y «pon una alarma mañana» sí.
    ejemplos = [i.ayuda for i in INTENTS if i.ayuda]
    if ejemplos:
        titulo, nota = GRUPOS["camino_rapido"]
        lineas += [f"**{titulo}**", nota, ""]
        lineas += [f"- «{e}»" for e in ejemplos]
        lineas.append("")

    lineas += [
        f"En total: {sum(len(v) for v in g.values())} herramientas y "
        f"{len(ejemplos)} atajos de una línea.",
        "",
        "Lo que **no** hago: nada sale de tu disco sin preguntarte, y nada "
        "cuesta dinero sin que me lo apruebes esa vez.",
    ]
    return "\n".join(lineas).rstrip()


def falta_describir() -> list[str]:
    """Tools sin descripción. Vacía = bien.

    Lo llama `test_toda_tool_tiene_descripcion`. Una lista que se queda vieja
    contesta en octubre lo que Aegis sabía hacer entonces.
    """
    return [n for n in sorted(_nombres_de_tools()) if not descripcion_de(n)]