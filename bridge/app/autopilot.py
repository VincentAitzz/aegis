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

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

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
    "Respondes con texto plano corto cuando ya no necesitas tools."
)

LESSONS_DIR = Path(__file__).resolve().parent.parent / "lessons"


def load_lessons(project: str) -> str:
    """Lecciones curadas del proyecto: reglas que ya se pagaron con un error.

    Es la capa que hace que una corrección mía no se pierda. Cuando corrijo un
    módulo, escribo aquí la regla; la lee TODO run posterior de ese proyecto.
    """
    if not project:
        return ""
    path = LESSONS_DIR / f"{project}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def build_system_prompt(instructions: str = "", project: str = "",
                        memory: str = "") -> str:
    """Sistema = base + lecciones del proyecto + memoria episodica + el spec."""
    parts = [SYSTEM_PROMPT]
    lessons = load_lessons(project)
    if lessons:
        parts.append(
            "LECCIONES APRENDIDAS EN ESTE PROYECTO (aplícalas; ya se corrigieron "
            "estas cosas una vez):\n" + lessons
        )
    if memory:
        parts.append("EXPERIENCIA PASADA RELEVANTE:\n" + memory)
    if instructions:
        parts.append("INSTRUCCIONES DE ESTA TAREA:\n" + instructions)
    return "\n\n".join(parts)


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
    kwargs = {k: v for k, v in args.items() if v is not None}
    result = tool.fn(**kwargs)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


async def run_autopilot(prompt: str, *, ollama_url: str, model: str,
                        max_steps: int = MAX_STEPS, instructions: str = "",
                        project: str = "", memory: str = "",
                        gate: Any = None) -> dict[str, Any]:
    """Ejecuta la tarea en un bucle modelo→tool, y devuelve respuesta y traza.

    `gate` es el corrector de una sola llamada por paso: `await gate(step, tool,
    argumentos, resultado)` devuelve un veredicto y decide si el run sigue. Es lo
    que convierte "el modelo dijo que lo hizo" en "el verificador lo comprobó", y
    sin él el autopilot no tiene forma de saber si lo hizo. Un paso que la puerta
    reprueba se registra igual: el dato es justamente ese.
    """
    tools = _tools_schema()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(instructions, project, memory)},
        {"role": "user", "content": prompt},
    ]
    trace: list[dict[str, Any]] = []
    answer = ""
    repairs = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=300.0,
                                                       write=30.0, pool=5.0)) as client:
        for step in range(1, max_steps + 1):
            r = await client.post(
                f"{ollama_url.rstrip('/')}/v1/chat/completions",
                json={"model": model, "stream": False, "messages": messages, "tools": tools},
            )
            r.raise_for_status()
            choice = r.json()["choices"][0]
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
                if _mentions_tool(text) and repairs < MAX_REPAIRS:
                    repairs += 1
                    trace.append({"step": step, "action": "repair",
                                  "text": text[:200]})
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": repair_prompt()})
                    continue
                answer = text.strip()
                trace.append({"step": step, "action": "final", "text": answer[:800]})
                break

            messages.append({"role": "assistant", "content": text or "(tool call)"})
            for name, args in calls:
                entry: dict[str, Any] = {"step": step, "tool": name, "arguments": args}
                try:
                    result = _execute(name, args)
                except (ToolNotAllowed, ValueError, TypeError) as exc:
                    entry["ok"] = False
                    entry["result"] = f"ERROR: {exc}"
                    result = entry["result"]
                else:
                    entry["ok"] = True
                    entry["result"] = result[:1500]
                if gate is not None and entry["ok"]:
                    # La puerta solo juzga lo que la tool aceptó: si la propia tool
                    # falló, su error ya es el veredicto de este paso.
                    veredicto = await gate(step, name, args, result)
                    if veredicto:
                        entry["gate"] = veredicto
                        if veredicto.get("stop"):
                            messages.append({
                                "role": "user",
                                "content": "VEREDICTO DEL VERIFICADOR:\n"
                                           + json.dumps(veredicto, ensure_ascii=False)[:MAX_CHARS_PER_STEP],
                            })
                            return {
                                "model": model,
                                "answer": f"Pausado en el paso {step}: la puerta de "
                                          f"verificación reprueba el avance.\n"
                                          f"{json.dumps(veredicto, ensure_ascii=False)[:600]}",
                                "steps": len(trace),
                                "trace": trace,
                                "stopped_by_gate": True,
                            }
                trace.append(entry)
                messages.append({
                    "role": "user",
                    "content": f"RESULTADO de {name}:\n{result[:MAX_CHARS_PER_STEP]}",
                })
    return {
        "model": model,
        "answer": answer or answer_fallback(trace),
        "steps": len(trace),
        "trace": trace,
    }


def answer_fallback(trace: list[dict[str, Any]]) -> str:
    """Si el modelo se quedó sin respuesta, resume lo realmente ejecutado."""
    if not trace:
        return "El modelo no propuso ninguna tool; no se ejecutó nada."
    lines = ["El modelo agotó los pasos; traza real de lo ejecutado:"]
    for entry in trace:
        if entry.get("tool"):
            state = "ok" if entry.get("ok") else "ERROR"
            lines.append(f"- paso {entry['step']}: {entry['tool']} [{state}]")
            head = str(entry.get("result", ""))[:200].replace("\n", " ")
            lines.append(f"  {head}")
    return "\n".join(lines)
