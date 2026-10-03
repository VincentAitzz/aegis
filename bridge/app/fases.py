"""Fases de trabajo: lo que solo tiene sentido mientras se piensa.

## Qué es esto

Un `metodo.md` vale para todos los proyectos y todos los momentos. Una **fase**
vale para un momento concreto: cómo se aterriza una idea, cuándo se puede ya
nombrar una tecnología. Meterlo en el método lo pagaría todo el mundo, siempre.

## Por qué van en un fichero aparte, y no en `metodo.md`

Medido (A-016): los modelos de 6 GB dejan de emitir `tool_calls` cuando el prompt
crece. El prompt es el presupuesto. Una fase inyectada a todo el mundo se paga en
los runs de operación —los que más necesitan llamar tools— pagárselo de un
piso que no están pisando. Aquí solo la pagan los runs que la piden.

## Por qué el límite de tamaño es una invariante y no una costumbre

`MAX_CHARS` es corto a propósito. Si una fase crece, lo primero que hay que
mirar es si sigue siendo una fase o ya es un método: eso se decide con
`probe-toolcall.sh`, no con la lectura.

Cuando el prompt crece hay que **medir**, no suponer que sigue funcionando.
"""

import re
from functools import lru_cache
from pathlib import Path

FASES_DIR = Path(__file__).resolve().parent.parent / "fases"

#: Tope por bloque. Suficiente para un criterio de salida y unas prohibiciones;
#: insuficiente para un tutorial. Si una fase necesita más, es un método.
MAX_CHARS = 2600

#: Un nombre de fase es un identificador, no un camino. Sin esto, `../../metodo`
#: sería una fase válida y leería lo que hubiera en ese sitio.
_NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")

_CACHE: dict[str, str] = {}


def known_fases() -> list[str]:
    """Qué fases existen en disco. Para la UI y para saber qué se puede pedir."""
    if not FASES_DIR.is_dir():
        return []
    return sorted(p.stem for p in FASES_DIR.glob("*.md")
                  if _NOMBRE.match(p.stem) and not p.name.startswith("_"))


def load_phase(fase: str) -> str:
    """El texto de la fase, o cadena vacía si no existe o no es válida.

    Vacía y no una excepción: un nombre de fase equivocado **no puede tumbar un
    run**. Es un parámetro de una app, y una app manda cosas raras.
    """
    key = str(fase or "").strip()
    if not _NOMBRE.match(key):
        return ""
    if key in _CACHE:
        return _CACHE[key]
    try:
        texto = (FASES_DIR / f"{key}.md").read_text(encoding="utf-8").strip()
    except OSError:
        texto = ""
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS].rstrip() + "\n\n[…truncada por tamaño]"
    _CACHE[key] = texto
    return texto


def phase_context(fase: str) -> str:
    """Bloque listo para inyectar, o "" si no hay fase."""
    texto = load_phase(fase)
    if not texto:
        return ""
    return f"FASE DE TRABAJO '{fase}'. Lo que sigue aplica a esta fase y a ninguna más:\n\n{texto}"