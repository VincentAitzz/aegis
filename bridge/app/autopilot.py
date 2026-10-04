"""Autopiloto: convierte la intención del modelo en ejecuciones reales de aegis-ops.

Los modelos locales disponibles (qwen2.5-coder:7b, qwen2.5:7b) no emiten
`tool_calls` estructurados de forma fiable en los runs de Hermes: escriben el
JSON de la llamada en el texto, a veces con XML de qwen, y luego se detienen.
Este módulo cierra ese hueco sin cambiar el modelo:

  1. Pide al modelo una tool con el schema real de aegis-ops.
  2. Extrae la llamada del texto (JSON plano, bloque ```json, <stdlib_response>).
  3. Valida el nombre contra la lista blanca de aegis-ops y ejecuta la función.
  4. Devuelve el resultado al modelo y repite (tope de pasos).
  5. Termina cuando el modelo ya no pide tools y devuelve la respuesta final.

La ejecución es determinista y auditable: cada tool llamada queda en la traza.
El modelo decide QUÉ hacer; el autopilot decide CÓMO ejecutarlo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from . import enfoques as enfoques_mod
from . import lecciones
from .fichas import context_for
from .method import method_context
from .quien import contexto as quien_context
from .mcp_ops import coerce_args
from .mcp_ops import mcp as ops_mcp

log = logging.getLogger("aegis.bridge.autopilot")

MCP_PREFIX = "mcp__aegis_ops__"
BRIDGE_TOOL = "tool_call"
MAX_STEPS = 6
MAX_CHARS_PER_STEP = 4000
MAX_REPAIRS = 3
_DANGLING_RE = re.compile(
    r"tool\s*call|tool\s*use|llamada|herramienta|工具|呼び出し", re.IGNORECASE
)


def repair_prompt() -> str:
    names = ", ".join(sorted(allowed_tools()))
    return (
        "Tu último mensaje quedó cortado y no se ejecutó ninguna tool. "
        "Emite ahora la llamada como JSON literal en una sola línea, sin texto antes "
        'ni después: {"name": "<tool>", "arguments": {...}}\n'
        f"Tools disponibles: {names}."
    )


def _mentions_tool(text: str) -> bool:
    """True si el texto anuncia una tool call o nombra alguna tool permitida."""
    if _DANGLING_RE.search(text):
        return True
    if _looks_truncated(text):
        return True
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in allowed_tools())


def _looks_truncated(text: str) -> bool:
    """Placeholder corto tipo '(tool call)' o '(工具调用)': la llamada se cortó."""
    stripped = text.strip()
    return 0 < len(stripped) <= 60 and stripped[-1] in "):："

SYSTEM_PROMPT = (
    "Eres el agente Aegis. Para trabajar en el host llamas SIEMPRE a las tools "
    "disponibles, una por llamada, y esperas su resultado antes de seguir. "
    "Respondes con texto plano corto cuando ya no necesitas tools.\n"
    "Si el encargo todavía NO es ejecutable —porque falta decidir cómo se "
    "construye algo, o cómo quedaría— puede que te venga un enfoque puesto. Si "
    "te viene, úsalo: es el bridge leyendo el encargo. Si no encaja, suéltalo con "
    "usar_enfoque(nombre='') y razona tú. Si no te viene ninguno y no sabes por "
    "dónde empezar, pide uno con usar_enfoque y explica en `por_que` por qué este "
    "encargo es de ese tipo."
)

LESSONS_DIR = Path(__file__).resolve().parent.parent / "lessons"


def load_lessons(project: str, encargo: str = "") -> str:
    """Lecciones del proyecto para el prompt: **el índice y la que más aplica**.

    ## Por qué ya no va el fichero entero
    Medido el 2026-10-04, mismo encargo, n=5 cada caso (`app/lecciones.py` tiene
    la tabla entera):

    | prompt | tool_calls | latencia en frío |
    |---|---|---|
    | con las 120 KB enteras | 5/5 | **60,2 s** |
    | sin lecciones | 5/5 | **10,5 s** |

    5,7× por llamada y el mismo número de tool_calls. Y el comportamiento que
    describen tampoco cambia: se probó A-014 («no repitas la llamada idéntica que
    ya falló dos veces») y el modelo la repitió **3 de 3 con las lecciones
    inyectadas y 3 de 3 sin ellas**.

    ## Qué va ahora
    Un índice (número, título y cuándo aplica) y la lección más relevante entera.
    El resto se pide con la tool `lecciones(alias, tema)`. Las lecciones siguen
    siendo el registro de por qué el código es como es —eso no cambia—; lo que
    cambia es lo que se le enseña a un modelo que no las iba a obedecer.

    ## Por qué una entera y no cero
    Una concreta cabe, y es la que de verdad puede darle un motivo para mirar.
   -meterla en el prompt la deja leída en el momento en que decide; depender de
    que pida la tool es depender de que el 7B se acuerde.
    """
    if not project:
        return ""
    indice = lecciones.indice(project)
    if not indice:
        return ""
    partes = [
        "LECCIONES DE ESTE PROYECTO (índice, no el texto entero). Si una encaja "
        "con lo que te toca, pídela con la tool `lecciones(alias, tema)` antes de "
        "actuar — o léela aquí si va entera:\n" + indice,
    ]
    encaja = lecciones.relevantes(project, encargo)
    if encaja:
        partes.append("La que más aplica a este encargo:\n\n"
                      + encaja[0].como_texto())
    return "\n\n".join(partes)


def build_system_prompt(instructions: str = "", project: str = "",
                        memory: str = "", enfoque: str = "",
                        enfoque_por_que: str = "",
                        enfoque_derivado: bool = False,
                        encargo: str = "") -> str:
    """Sistema = identidad + método + base + ficha + enfoque + lecciones + memoria.

    El `enfoque` inyecta `bridge/enfoques/{enfoque}.md`, que es donde vive lo que
    solo tiene sentido mientras se piensa: cómo se va a construir algo, y en qué
    orden se decide. Va **después** de la ficha y **antes** de las lecciones,
    porque el enfoque dice lo que hay que hacer y las lecciones lo que no hay que
    repetir.

    ## Y por qué cabe uno solo
    A-016 midió que los modelos de 6 GB dejan de emitir `tool_calls` cuando el
    prompt crece. `arquitectura.md` son ~1970 caracteres sobre ~3400 de base: un
    +58 %. El tope vive en `enfoques.MAX_CHARS` y se comprueba en cada peticion, no
    al cargar el indice.

    ## Por qué el bloque dice de quién es la propuesta
    `enfoque_derivado` es la diferencia entre «Aegis decidió esto» y «esto se lo
    puso el bridge encima». Dejarlo sin decir sería escribir una traza que miente:
    la auditoría de A-077 se apoyó justo en que se puede leer quién eligió qué, y
    un enfoque que parece elegido por el modelo y no lo fue rompe justo eso. Con
    el aviso, Aegis además sabe que puede corregirlo, que es lo que convierte la
    derivación en una propuesta y no en un impose.
    """
    parts = [SYSTEM_PROMPT]
    # El metodo se lee con el proyecto porque se parte en dos: lo que siempre es
    # cierto, y lo que solo tiene sentido trabajando en un proyecto. Un encargo
    # cotidiano sin proyecto paga la parte que no le sirve.
    metodo = method_context(project)
    if metodo:
        parts.append(metodo)
    # Contigo va justo después del método: los dos son «cómo se trabaja aquí», y
    # separarlos metiendo la ficha del proyecto en medio pondría tu perfil en la
    # mitad del prompt, donde el 7B le da menos peso. Va después y no antes
    # porque, si los dos se contradijeran, manda el método.
    #
    # Son ~384 caracteres con tope duro de 600 (`app/quien.py`). El resto del
    # fichero NO entra aquí: se pide con `quien_eres(tema)`, igual que las
    # lecciones. Añadirlo todo «porque el modelo lo aprovecha más» se pagaría en
    # cada paso de cada run —A-016, A-080—.
    quien = quien_context()
    if quien:
        parts.append(quien)
    # La ficha del proyecto va antes que las lecciones: dice de qué trata esto,
    # y las lecciones solo tienen sentido una vez que se sabe.
    ficha = context_for(project)
    if ficha:
        parts.append(ficha)
    bloque_enfoque = enfoques_mod.bloque(enfoque)
    if bloque_enfoque:
        # El **titulo** va delante, y no solo en la tool: un enfoque fijado o
        # derivado llega aqui sin pasar por `usar_enfoque`, y sin el titulo Aegis
        # leeria un bloque sin saber de donde sale.
        try:
            cabecera = (f"## ENFOQUE DERIVADO POR EL BRIDGE: "
                        if enfoque_derivado else "## ENFOQUE FIJADO: ")
            bloque_enfoque = (cabecera
                              + f"{enfoques_mod.ficha(enfoque)['titulo']}\n\n"
                              + bloque_enfoque)
        except enfoques_mod.EnfoqueNoExiste:
            pass
        if enfoque_derivado:
            bloque_enfoque += (
                "\n\n### De dónde salió este enfoque\n\n"
                f"{enfoque_por_que or 'el encargo encajaba con él'}. **No lo pediste "
                "tú**: lo sugirió el bridge porque las señales del encargo "
                "aparecen en su ficha. Si no encaja con lo que te han pedido, no "
                "lo arrastres: suéltalo con `usar_enfoque(nombre='')`, o pide otro "
                "con `usar_enfoque(nombre, por_que)` diciendo por qué.")
        partes_cerradas = []
        try:
            partes_cerradas = enfoques_mod.restringe(enfoque)
        except enfoques_mod.EnfoqueNoExiste:
            partes_cerradas = []
        if partes_cerradas:
            bloque_enfoque = (
                bloque_enfoque + "\n\n### Lo que este enfoque cierra\n\n"
                + "\n".join(f"- `{t}` — **prohibida** mientras dure este enfoque."
                            for t in partes_cerradas)
                + "\n\nNo es una recomendación: la autonomía las niega antes de "
                  "ejecutarlas. Suelta el enfoque cuando ya no lo necesites.")
        parts.append(bloque_enfoque)
    lessons = load_lessons(project, encargo)
    if lessons:
        parts.append(lessons)
    if memory:
        parts.append("EXPERIENCIA PASADA RELEVANTE:\n" + memory)
    # Lo que el usuario ya ha rechazado, con su motivo. Sin esto la columna
    # `razon_denegacion` se escribe y no la lee nadie: sería un registro del
    # bridge, no una memoria del agente.
    denegado = _denegaciones_recientes()
    if denegado:
        parts.append(denegado)
    if instructions:
        parts.append("INSTRUCCIONES DE ESTA TAREA:\n" + instructions)
    return "\n\n".join(parts)


def _denegaciones_recientes(limite: int = 4) -> str:
    """Lo que le han dicho que no. Envuelto en try porque la autonomía es un
    módulo aparte y este bucle no debe caer si su almacén no está."""
    try:
        from .autonomy import resume_denegaciones
        return resume_denegaciones(limite=limite)
    except Exception as exc:  # noqa: BLE001 — el prompt nunca es motivo de caída
        log.debug("no pude leer las denegaciones: %s", exc)
        return ""


class ToolNotAllowed(ValueError):
    """El modelo pidió una tool fuera de la lista blanca."""


def _tools_schema() -> list[dict[str, Any]]:
    """Deriva el schema OpenAI de las tools reales de aegis-ops."""
    schema: list[dict[str, Any]] = []
    for tool in ops_mcp._tool_manager.list_tools():
        params = tool.model_dump().get("parameters") or {}
        schema.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.model_dump().get("description") or "",
                "parameters": {
                    "type": "object",
                    "properties": params.get("properties", {}),
                    "required": params.get("required", []),
                },
            },
        })
    return schema


def allowed_tools() -> set[str]:
    return {t.name for t in ops_mcp._tool_manager.list_tools()}


def _json_objects(text: str) -> list[Any]:
    """Saca los objetos JSON de primer nivel de un texto, ignorando ruido."""
    out: list[Any] = []
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        out.append(json.loads(text[start:i + 1]))
                    except json.JSONDecodeError:
                        pass
                    start = -1
    return out


_STDLIB_RE = re.compile(r"<stdlib_response>(.*?)</stdlib_response>", re.DOTALL)
# El modelo a veces escribe el nombre FUERA del JSON: "(tool call) build_apk {"api_host": ...}"
_PREFIXED_CALL_RE = re.compile(
    r"(?:tool_call|tool\s*call)\s*\)?\s*[:\-]?\s*([A-Za-z0-9_:]+)\s*(\{.*)", re.DOTALL | re.IGNORECASE
)


def _coerce_args(args: Any) -> dict[str, Any]:
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def extract_tool_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Devuelve [(nombre_tool, argumentos)] tal y como la pide el modelo en texto."""
    found: list[tuple[str, dict[str, Any]]] = []
    allowed = allowed_tools()
    for block in _STDLIB_RE.findall(text):
        found.extend(extract_tool_calls(block))
    for obj in _json_objects(text):
        if not isinstance(obj, dict):
            continue
        entries: list[Any] = []
        if isinstance(obj.get("calls"), list):
            entries = obj["calls"]
        elif obj.get("name") and obj.get("name") not in {BRIDGE_TOOL, "tool_search"}:
            entries = [obj]
        args_obj = obj.get("arguments")
        if isinstance(args_obj, dict) and (
            isinstance(args_obj.get("calls"), list) or args_obj.get("name")
        ):
            found.extend(extract_tool_calls(json.dumps(args_obj)))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in {BRIDGE_TOOL, "tool_search"}:
                continue
            short = name[len(MCP_PREFIX):] if name.startswith(MCP_PREFIX) else name
            if short in allowed:
                found.append((short, _coerce_args(entry.get("arguments"))))
    for match in _PREFIXED_CALL_RE.finditer(text):
        raw_name = match.group(1).strip()
        short = raw_name[len(MCP_PREFIX):] if raw_name.startswith(MCP_PREFIX) else raw_name
        if short not in allowed:
            continue
        for obj in _json_objects(match.group(2)):
            if isinstance(obj, dict) and not obj.get("name"):
                found.append((short, _coerce_args(obj)))
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, dict[str, Any]]] = []
    for name, args in found:
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            unique.append((name, args))
    return unique


def _execute(name: str, args: dict[str, Any]) -> str:
    if name not in allowed_tools():
        raise ToolNotAllowed(
            f"tool no permitida: {name} (permitidas: {sorted(allowed_tools())})"
        )
    tool = ops_mcp._tool_manager.get_tool(name)
    if tool is None:
        raise ToolNotAllowed(f"tool desconocida: {name}")
    if not isinstance(args, dict):
        raise ValueError(f"argumentos inválidos para {name}: {type(args).__name__}")
    kwargs = coerce_args(tool, {k: v for k, v in args.items() if v is not None})
    result = tool.fn(**kwargs)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


TOOL_ENFOQUE = "usar_enfoque"


def _aplicar_enfoque(args: dict, activos: list[str], *,
                     run_id: str = "", paso: int = 0
                     ) -> tuple[list[str], str]:
    """Aplica lo que Aegis pidió con `usar_enfoque`, y dice si lo attachment.

    ## Por qué aquí y no dentro de la tool
    La tool no puede cambiar el estado del run: `_execute` es una funcion suelta
    y no sabe de que run se trata. Y el estado que importa —**cuales** hay
    ahora— vive en el bucle. Ademas el ajuste tiene que ocurrir **antes** de que
    este paso pase por la autonomia, no despues: si no, el primer write posterior
    al enfoque se cuela sin que nadie lo mire.

    ## Y por que se comprueba el presupuesto aquí
    El tope de enfoques y de caracteres se evalua en cada peticion, no solo al
    cargar el indice. Un unico enfoque de 2600 caracteres podria pasar al
    cargarse y ser el segundo de 2600 mas 2600.
    """
    from . import enfoques as mod

    nombre = str(args.get("nombre") or "").strip()
    por_que = str(args.get("por_que") or "").strip()

    # Soltar: nombre vacio. No es un caso raro, es la salida normal.
    if not nombre:
        if not activos:
            return activos, ""
        return [], f"suelta {', '.join(activos)}"

    if nombre in activos:
        return activos, f"'{nombre}' ya estaba activo"
    if not por_que:
        return activos, ""
    try:
        mod.ficha(nombre)
    except mod.EnfoqueNoExiste:
        return activos, ""
    cabe, motivo = mod.cabe(nombre, tuple(activos))
    if not cabe:
        return activos, f"'{nombre}' no cabe: {motivo}"
    return [*activos, nombre], f"-activa '{nombre}': {por_que[:160]}"


def _aviso_de_enfoque(activos: list[str], por_que: str) -> str:
    """Lo que Aegis lee de vuelta tras pedir un enfoque."""
    from . import enfoques as mod
    if not activos:
        return ("Sin enfoque activo. El método de siempre es lo que queda.")
    nombre = activos[0]
    try:
        texto = mod.bloque(nombre)
        f = mod.ficha(nombre)
    except mod.EnfoqueNoExiste as exc:
        return str(exc)
    if not texto:
        return ""
    cabecera = f"## ENFOQUE ACTIVO: {f['titulo']}\n\n"
    if f.get("restringe"):
        cerrado = "\n".join(f"- `{t}` — **prohibida** en este enfoque."
                            for t in f["restringe"])
        cabecera += (f"### Lo que este enfoque cierra\n\n{cerrado}\n\n"
                     "No es una recomendación: `decide()` las niega antes de "
                     "ejecutarlas.\n\n")
    if por_que:
        cabecera += f"Por qué lo pediste: {por_que[:400]}\n\n"
    return cabecera + texto


def _sembrar_enfoque(enfoque: str, prompt: str
                     ) -> tuple[list[str], str, dict[str, Any]]:
    """El enfoque con el que arranca el run: `(activos, motivo, entrada_de_traza)`.

    ## Por qué el bridge propone y Aegis corrige
    Porque está medido (A-077) que Aegis **no pide** un enfoque solo: con
    `qwen2.5:7b` razonó bien y no llamó a la tool, tres veces de tres. Tener la
    capacidad y que no dispare no es tenerla.

    Así que al arrancar se lee el encargo con reglas (`enfoques.derivar`), y si hay
    señal clara se propose el enfoque con su motivo **escrito en la traza**. Aegis
    sigue teniendo la última palabra: lo suelta con `usar_enfoque(nombre='')` o
    pide otro con su propio `por_que`.

    ## Por qué lo fijado manda sobre lo derivado
    Una persona que elige en la app sabe más que una regla, y el modo de derivar
    es el que se equivoca solo. Si viene fijado, no se deriva nada.

    ## Y por qué devuelve la entrada de traza en vez de escribirla
    Para que sea comprobable sin llamar a un modelo. El bucle entero necesita
    inferencia, y una parte que solo se puede medir con un 7B delante termina sin
    medirse. Esta se prueba en milisegundos.
    """
    from . import enfoques as mod

    if enfoque and mod.bloque(enfoque):
        return [enfoque], "", {}
    sug = mod.derivar(prompt)
    if not sug or not sug[0]:
        return [], "", {}
    nombre, motivo = sug
    cabe, _ = mod.cabe(nombre, ())
    if not cabe:
        # Un enfoque que no cabe no se propone: el prompt es el presupuesto y
        # recortarlo a medias daría a Aegis un método sin su final.
        return [], "", {}
    entrada = {"step": 0, "action": "enfoque_derivado", "enfoque": nombre,
               "por_que": motivo, "propuesto_por": "bridge"}
    return [nombre], motivo, entrada


def _con_empeora(result: dict[str, Any], estado_base: Optional[dict[str, Any]],
                  trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Añade al resultado si el verificador quedó **peor** que al empezar.

    `autonomy.empeora` estaba escrita y sin usar: la comparación entre la línea
    base y el final no la hacía nadie. Se hace aquí con el último veredicto que
    la puerta ya dejó en la traza, así que **no se vuelve a correr el verificador**
    — que es de lo más caro que hay — solo se leen los números que ya se midió.

    Y solo se dice si empeoró de verdad: con una base de 452 problemas, 452 → 460
    es empeorar aunque los dos estén "en rojo", y 452 → 452 no es nada.
    """
    from .autonomy import empeora
    ultimos = [t["gate"] for t in trace if t.get("gate")]
    if not ultimos or not estado_base:
        return result
    nuevo = {"alias": estado_base.get("alias"), "problemas": ultimos[-1].get("problemas")}
    motivo = empeora(estado_base, nuevo)
    result["empeorada"] = bool(motivo)
    if motivo:
        result["answer"] = f"{result.get('answer', '')}\n\nAviso: {motivo}"
    return result


async def run_autopilot(prompt: str, *, ollama_url: str, model: str,
                        max_steps: int = MAX_STEPS, instructions: str = "",
                        project: str = "", memory: str = "",
                        gate: Any = None,
                        on_step: Any = None,
                        run_id: str = "run_sin_id",
                        autonomy: Any = None,
                        token: str = "",
                        enfoque: str = "",
                        estado_base: Optional[dict[str, Any]] = None,
                        parar: Optional[asyncio.Event] = None,
                        extra: Optional[asyncio.Queue] = None) -> dict[str, Any]:
    """Ejecuta la tarea en un bucle modelo→tool, y devuelve respuesta y traza.

    `gate` es el corrector de una sola llamada por paso: `await gate(step, tool,
    argumentos, resultado)` devuelve un veredicto y decide si el run sigue. Es lo
    que convierte "el modelo dijo que lo hizo" en "el verificador lo comprobó", y
    sin él el autopilot no tiene forma de saber si lo hizo. Un paso que la puerta
    reprueba se registra igual: el dato es justamente ese.

    `on_step` es `await on_step(step, entry)` y se llama con cada entrada de la
    traza en cuanto existe. Sin él el run es una caja negra: en un 7B un paso
    puede tardar medio minuto, y el móvil necesita ver que avanza.

    `parar` y `extra` son el **control del run en marcha**, y viven aquí y no en
    el endpoint porque el bucle es el único que sabe dónde está el paso. Un run
    de autopilot no se puede parar cancelando la tarea de asyncio —el `await` del
    modelo está a punto de devolver y el `finally` se comería el resultado a
    medias— ni se puede dirigir desde fuera sin tocar la lista `messages`.

    ## Por qué el corte es **entre pasos**, no en mitad de uno
    `_execute` es síncrono y ya se está escribiendo cuando leas esto: no hay
    punto seguro dentro de una tool. Un paso que ya empezó se termina y se
    registra entero. La parada es por lo tanto «no empieces otro», que es la
    misma garantía que da un interruptor de proceso, y es honesta: el móvil
    muestra la traza real, sin el último paso a medias.

    `parar` se comprueba **antes** de pedirle nada al modelo, no después: así un
    run parado entre pasos no llega a gastar un paso más en inferencia.

    `autonomy` decide **antes** de ejecutar si una llamada está permitida. No es
    un filtro de la traza: si una tool no está autorizada, `_execute` no llega a
    llamarse. Un permiso comprobado después de la escritura es un informe, y un
    informe llega tarde.

    Cuando la decisión es "pregunta", el run **termina** con `fin:
    "esperando_ok"` y devuelve el id de la petición. No es un fallo ni un paso
    más: es el run esperando a una persona, y el móvil lo pinta como tal.
    """
    tools = _tools_schema()
    activos, motivo_derivado, entrada_enfoque = _sembrar_enfoque(enfoque, prompt)
    messages: list[dict[str, Any]] = [
        {"role": "system",
         "content": build_system_prompt(
             instructions, project, memory,
             activos[0] if activos else "",
             motivo_derivado, bool(motivo_derivado),
             encargo=prompt)},
        {"role": "user", "content": prompt},
    ]
    trace: list[dict[str, Any]] = []
    # El enfoque derivado entra en la traza como su propia entrada, y no como un
    # `final` ni como un campo suelto: A-077 se mide sobre estas líneas. Un enfoque
    # que no se puede ver en la traza no se puede auditar, que es justo lo que un
    # 7B necesita para que se le pueda preguntar por qué lo cogió.
    if entrada_enfoque:
        trace.append(entrada_enfoque)
    answer = ""
    repairs = 0
    fin = "max_steps"
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=300.0,
                                                       write=30.0, pool=5.0)) as client:
        for step in range(1, max_steps + 1):
            # La parada se mira antes de gastar una inferencia. El paso que ya
            # está en marcha no se interrumpe —`_execute` es síncrono y ya se
            # está escribiendo— así que parar significa «no empieces otro».
            if parar is not None and parar.is_set():
                log.info("autopilot %s: parado por la persona en el paso %d "
                         "(%d pasos en la traza)", run_id, step, len(trace))
                return {
                    "model": model,
                    "answer": f"Parado a petición tuya tras {len(trace)} paso(s). "
                              f"La traza de abajo es lo que se llegó a ejecutar.",
                    "steps": len(trace),
                    "trace": trace,
                    "fin": "parado",
                }
            # Lo que la persona escriba a mitad de run entra como un turno más.
            # No interrumpe el paso en curso: se drena aquí, así que surte efecto
            # en el siguiente, que es el mismo criterio que la parada.
            steering = 0
            while extra is not None and not extra.empty():
                try:
                    texto = str(extra.get_nowait()).strip()
                except asyncio.QueueEmpty:  # pragma: no cover — carrera con otro lector
                    break
                if not texto:
                    continue
                steering += 1
                messages.append({
                    "role": "user",
                    "content": f"INSTRUCCIÓN DE QUIEN TE MANDÓ (llega a mitad de "
                               f"run, aplícala a lo que hagas de aquí en adelante): {texto}",
                })
            if steering:
                log.info("autopilot %s: %d instrucción(es) del usuario aplicadas "
                         "antes del paso %d", run_id, steering, step)
            try:
                r = await client.post(
                    f"{ollama_url.rstrip('/')}/v1/chat/completions",
                    json={"model": model, "stream": False, "messages": messages, "tools": tools},
                )
                r.raise_for_status()
                choice = r.json()["choices"][0]
            except Exception as exc:  # noqa: BLE001 — el run muere, pero no en silencio
                # Antes esto se propagaba tal cual: el run se guardaba `failed`
                # sin traza ni episodio (los dos están **después** de esta llamada),
                # y un parpadeo de Ollama costaba un run entero sin dejar rastro.
                # Un Ollama que no contesta es un `fin` con nombre, no un silêncio.
                detalle = f"{type(exc).__name__}: {exc}".strip()[:300]
                log.warning("autopilot %s: el modelo no respondió en el paso %d: %s",
                            run_id, step, detalle)
                trace.append({"step": step, "action": "modelo_caido",
                              "text": detalle})
                if on_step is not None:
                    await on_step(step, trace[-1])
                return {
                    "model": model,
                    "answer": f"El modelo no respondió en el paso {step}: {detalle}\n"
                              f"Hasta aquí llegué:\n{answer_fallback(trace)}",
                    "steps": len(trace),
                    "trace": trace,
                    "fin": "modelo_caido",
                    # El motivo también en su campo: el JSONL se consulta con
                    # `jq`, no leyéndolo como un cuento.
                    "error": detalle,
                }
            message = choice.get("message") or {}
            text = message.get("content") or ""

            calls: list[tuple[str, dict[str, Any]]] = []
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function") or {}
                raw = str(fn.get("name") or "").strip()
                name = raw[len(MCP_PREFIX):] if raw.startswith(MCP_PREFIX) else raw
                if name in allowed_tools():
                    calls.append((name, _coerce_args(fn.get("arguments"))))
            if not calls:
                calls = extract_tool_calls(text)

            if not calls:
                # Una respuesta vacía no es una respuesta: es el modelo fallando.
                # Termin ahí waste un run entero sin dejar rastro de por qué.
                if not text.strip() and repairs < MAX_REPAIRS:
                    repairs += 1
                    trace.append({"step": step, "action": "repair",
                                  "text": "respuesta vacía"})
                    messages.append({"role": "assistant", "content": "(vacío)"})
                    messages.append({
                        "role": "user",
                        "content": "Tu mensaje anterior llegó vacío. Si ya no "
                                   "necesitas tools, responde con el texto plano de "
                                   "tu respuesta. Si sí, emite la llamada JSON."
                                   + "\n" + repair_prompt()})
                    continue
                if _mentions_tool(text) and repairs < MAX_REPAIRS:
                    repairs += 1
                    trace.append({"step": step, "action": "repair",
                                  "text": text[:200]})
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": repair_prompt()})
                    continue
                answer = text.strip()
                trace.append({"step": step, "action": "final", "text": answer[:800]})
                # Por qué terminó el run. Sin esto, "agotó los pasos" se confundía
                # con "el modelo respondió" y el motivo real se perdía.
                fin = "respuesta_vacia" if not answer else "sin_tools"
                break

            # El mensaje del asistente lleva **la llamada que hizo**. Antes solo
            # iba el texto, con un "(tool call)" de relleno, así que el historial
            # no decía qué se había pedido: el modelo recibía un mensaje de usuario
            # con un resultado y sin la llamada a la que correspondía.
            #
            # ## Lo que medía esto
            # Es la causa de que Aegis se quedara sin pasos. Contando cuántas veces
            # repite la misma tool en el paso 2, con el bucle tal cual estaba:
            #
            #     qwen2.5:7b    3 de 4 veces repetía la llamada
            #     llama3.2:3b   1 de 4
            #
            # Con el resultado devuelto **con su rol y su `tool_call_id`**: 0 de 4
            # en los dos modelos. El problema no era la cabeza del modelo, era que
            # el historial no le enseñaba que ya tenía la respuesta.
            #
            # Y el `"(tool call)"` de relleno era peor que inútil: un mensaje de
            # asistente que dice "(tool call)" y no tiene ninguna llamada es un
            # historial que se contradice a sí mismo.
            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": f"call_{step}_{i}", "type": "function",
                     "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                    for i, (name, args) in enumerate(calls)
                ] or None,
            })
            # El autopilot también «habla»: cuando el modelo narra lo que va a
            # hacer, hay texto saliendo. Sin esto, el glifo se quedaría en celeste
            # durante un trabajo de veinte pasos, que es justo cuando más está
            # trabajando y menos parece que habla. Ver `app/actividad.py`.
            if (narracion := (text or "").strip()) and not narracion.startswith("{"):
                from . import actividad
                actividad.marcar("autopilot", run_id)
            for indice, (name, args) in enumerate(calls):
                # El enfoque se ajusta **antes** de la autonomia de este paso, no
                # despues. Es lo unico que hace que el cierre de puertas valga:
                # si `usar_enfoque` se contara al final del paso, el primer write
                # de despues del enfoque habria pasado sin mirarlo.
                if name == TOOL_ENFOQUE:
                    activos, por_que = _aplicar_enfoque(
                        args, activos, run_id=run_id, paso=step)
                    if por_que:
                        entry_extra = {"step": step, "action": "enfoque",
                                       "por_que": por_que, "activos": list(activos)}
                        trace.append(entry_extra)
                        if on_step is not None:
                            await on_step(step, entry_extra)
                    messages.append({
                        "role": "user",
                        "content": f"RESULTADO de {name}:\n" + (
                            _aviso_de_enfoque(activos, por_que))})
                    continue

                # El texto del modelo **sí** va en la traza. Antes no, y era una
                # pérdida doble: se perdía para el móvil (que solo pintaba
                # "projects_list OK") y para el log de disco. Es la diferencia
                # entre ver qué herramienta se ejecutó y ver por qué la pidió.
                #
                # Se corta a 400 caracteres porque es una frase de intención, no
                # un informe: más de eso es el modelo divagando.
                entry: dict[str, Any] = {"step": step, "tool": name, "arguments": args}
                if (narracion := (text or "").strip()) and not narracion.startswith("{"):
                    entry["text"] = narracion[:400]

                # La autonomía se consulta **antes** de ejecutar, nunca después.
                # Consultarla después sería un informe, y un informe llega tarde:
                # la escritura ya está en el disco.
                if autonomy is not None:
                    veredicto = autonomy.decide(
                        name, args, run_id=run_id, paso=step,
                        estado_base=estado_base, token=token,
                        enfoque=activos[0] if activos else "")
                    entry["autonomia"] = {"ok": veredicto.ok, "motivo": veredicto.motivo,
                                          "peticion": veredicto.peticion}
                    # El token era para **esa** llamada. En cuanto se gasta, el run
                    # sigue por el camino normal: si se reenvía, todos los pasos
                    # siguientes morirían con "ese permiso ya se usó", y hay medido
                    # que eso es lo que pasaba tras un alta correcta.
                    if veredicto.uso_token:
                        token = ""
                    if not veredicto.ok and veredicto.peticion:
                        # El run se para con un motivo que el móvil sabe leer: no
                        # es un fallo, es que alguien tiene que responder. Se
                        # registra igual en la traza porque el dato es ese.
                        entry["ok"] = False
                        entry["result"] = (
                            f"ESPERO TU OK. {veredicto.motivo}\n"
                            f"id de peticion: {veredicto.peticion}. "
                            f"Esta llamada NO se ha ejecutado. Apruébala en el "
                            f"móvil y vuelve a pedirme lo mismo.")
                        trace.append(entry)
                        if on_step is not None:
                            await on_step(step, entry)
                        return {
                            "model": model,
                            "answer": f"Me he parado antes de usar `{name}`.\n\n"
                                      f"{veredicto.motivo}\n\n"
                                      f"No he hecho nada todavía. Te lo pregunto "
                                      f"porque no me autorizaste a hacerlo solo.",
                            "steps": len(trace),
                            "trace": trace,
                            "fin": "esperando_ok",
                            "peticion": veredicto.peticion,
                        }
                    if not veredicto.ok:
                        # Un "no" con motivo: Aegis lo sabe y puede seguir con
                        # otra cosa. No es una puerta cerrada, es una respuesta.
                        entry["ok"] = False
                        entry["result"] = f"NO AUTORIZADO: {veredicto.motivo}"
                        trace.append(entry)
                        if on_step is not None:
                            await on_step(step, entry)
                        if veredicto.fin:
                            # Y un "no" que es un tope: aquí seguir es tonto, cada
                            # paso va a recibir el mismo. Se acaba con su motivo.
                            return {
                                "model": model,
                                "answer": f"Me he parado antes de usar `{name}`.\n\n"
                                          f"{veredicto.motivo}",
                                "steps": len(trace),
                                "trace": trace,
                                "fin": veredicto.fin,
                            }
                        messages.append({
                            "role": "user",
                            "content": f"NO PUEDES HACER ESTO: {veredicto.motivo}\n"
                                       f"Sigue con otra cosa o da esto por terminado.",
                        })
                        continue

                try:
                    # La tool corre en un hilo, nunca en el event loop.
                    #
                    # ## Por qué
                    # `_execute` llama a la función de la tool, y varias lanzan
                    # procesos: `repo_verify` es `subprocess.run(timeout=900)`, y
                    # `tsc` o `vitest` tardan **minutos**. En el bucle de eventos,
                    # eso congela el bridge entero: `/health`, `/actividad`, el
                    # poll de 3 s del móvil, el WebSocket y el propio
                    # `POST /autopilot/{id}/stop` — que no se atiende hasta que la
                    # verificación termina. Parar un run durante su propia
                    # verificación era imposible.
                    #
                    # El repo ya había detectado el problema y lo había arreglado
                    # dos veces en el sitio equivocado (`main.py`, en las dos rutas
                    # que lanzan hilo para deploy y aprobaciones). Aquí es donde se
                    # pasa el 95 % del tiempo.
                    #
                    # ## Lo que cuesta
                    # La tool deja de estar en el loop, así que su rollback de
                    # sintaxis y sus guardarraíles pasan a ejecutarse desde un hilo.
                    # `_write_guarded` lo tiene en cuenta (lock de módulo), y
                    # `SQLiteGraph` se abrió con `check_same_thread=False` y un
                    # lock por el mismo motivo. **Las dos cosas van en el mismo
                    # commit**: cambiar solo esto rompe la memoria.
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        None, _execute, name, args)
                except (ToolNotAllowed, ValueError, TypeError) as exc:
                    entry["ok"] = False
                    entry["result"] = f"ERROR: {exc}"
                    result = entry["result"]
                except Exception as exc:  # noqa: BLE001 — una tool que revienta es un paso rojo, no un run muerto
                    # Se atrapa **todo**, y no por lujo: una tool que lance un
                    # `OSError` o un `KeyError` se llevaba el run entero por
                    # delante, sin traza y sin episodio. El modelo debería poder
                    # leer el error y reintentar con otra cosa, que es justo lo que
                    # se le ofrece aquí: el error vuelve como texto en el paso.
                    result = f"ERROR: {type(exc).__name__}: {exc}"[:500]
                    entry["ok"] = False
                    entry["result"] = result
                    log.warning("autopilot %s: la tool %s levantó %s en el paso %d",
                                run_id, name, type(exc).__name__, step)
                else:
                    entry["ok"] = True
                    entry["result"] = result[:1500]
                if on_step is not None:
                    await on_step(step, entry)
                if gate is not None and entry["ok"]:
                    # La puerta solo juzga lo que la tool aceptó: si la propia tool
                    # falló, su error ya es el veredicto de este paso.
                    veredicto = await gate(step, name, args, result)
                    if veredicto:
                        entry["gate"] = veredicto
                        if veredicto.get("stop"):
                            # Sin `fin` aquí, `_runner` hacía `result["fin"]` y
                            # reventaba con KeyError: el run se guardaba como
                            # `failed` con el error `'fin'`. Cada vez que la puerta
                            # reprendía el avance, el registro decía «falló» sin
                            # decir por qué. Un `fin` que no está es un `fin` que
                            # no se puede leer.
                            #
                            # El mensaje al modelo no se añade: el run termina, y
                            # nadie lo va a leer.
                            return _con_empeora({
                                "model": model,
                                "answer": f"Pausado en el paso {step}: la puerta de "
                                          f"verificación reprueba el avance.\n"
                                          f"{json.dumps(veredicto, ensure_ascii=False)[:600]}",
                                "steps": len(trace),
                                "trace": trace,
                                "stopped_by_gate": True,
                                "fin": "llamada_repetida" if veredicto.get("repetida")
                                        else "verificador_rojo",
                            }, estado_base, trace)
                trace.append(entry)
                # El resultado vuelve **con su rol**, no como un mensaje de
                # usuario. Con `role: user` el modelo lo lee como una peticion
                # nueva, y lo natural ante una peticion es volver a actuar.
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{step}_{indice}",
                    "content": f"RESULTADO de {name}:\n{result[:MAX_CHARS_PER_STEP]}",
                })
    return _con_empeora({
        "model": model,
        "answer": answer or answer_fallback(trace),
        "steps": len(trace),
        "trace": trace,
        # El motivo de cierre es un dato, no un detalle: distingue "el modelo no
        # pidió más tools" de "se acabaron los pasos" de "la puerta lo paró".
        "fin": fin,
    }, estado_base, trace)


def answer_fallback(trace: list[dict[str, Any]]) -> str:
    """Si el modelo se quedó sin respuesta, resume lo realmente ejecutado."""
    if not trace:
        return ("El modelo no propuso ninguna tool y tampoco devolvió texto: "
                "no se ejecutó nada.")
    lines = ["El modelo agotó los pasos; traza real de lo ejecutado:"]
    for entry in trace:
        if entry.get("tool"):
            state = "ok" if entry.get("ok") else "ERROR"
            lines.append(f"- paso {entry['step']}: {entry['tool']} [{state}]")
            head = str(entry.get("result", ""))[:200].replace("\n", " ")
            lines.append(f"  {head}")
    return "\n".join(lines)
