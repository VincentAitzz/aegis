"""El método de trabajo, cargado de disco e inyectado en todos los runs.

Existe porque hay tres cosas distintas y conviene no confundirlas:

- `lessons/{project}.md`  reglas que **este** proyecto ya se pagó con un error.
- `fichas/{alias}.md`     qué es este proyecto y cómo se trabaja en él.
- `metodo.md`             cómo trabaja un consultor, en cualquier proyecto.

El método es global a propósito: es la parte que el usuario no quiere volver a
explicar en cada encargo. Las lecciones son por proyecto porque nacen de un
error concreto y no tienen sentido fuera de él.

**Por qué vive en un fichero y no en el prompt del código:** para poder
corregirlo sin tocar Python, y para que sea revisable en un `git diff`. Y
porque `lessons/` ya demostró que esa es la vía por la que una corrección
escrita a mano llega sola a los runs siguientes.

**El tamaño importa.** Está medido: los modelos de 6 GB (`qwen2.5:7b`) dejan de
llamar tools cuando el prompt crece (A-016, y la ablación del 2026-09-30 donde
10k → 2k de prompt no cambió nada y 69 chars sí). Este fichero es corto a
propósito. Si crece, medir antes de asumir que sigue funcionando.
"""

from pathlib import Path

METHOD_PATH = Path(__file__).resolve().parent.parent / "metodo.md"

_CACHE: dict[str, str] = {}


def load_method() -> str:
    """El método, o cadena vacía si no está (un fichero ausente no rompe un run)."""
    key = str(METHOD_PATH)
    if key not in _CACHE:
        try:
            _CACHE[key] = METHOD_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            _CACHE[key] = ""
    return _CACHE[key]


def method_context() -> str:
    """Bloque listo para inyectar en el system prompt.

    Devuelve "" si no hay fichero, porque un system prompt debe poder construirse
    sin este módulo (tests, despliegues mínimos).
    """
    method = load_method()
    if not method:
        return ""
    return f"CÓMO TRABAJO (aplica a todo lo que hagas en este sistema):\n\n{method}"