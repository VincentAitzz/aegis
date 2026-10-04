"""El método de trabajo, cargado de disco e inyectado en todos los runs.

Existe porque hay tres cosas distintas y conviene no confundirlas:

- `lessons/{project}.md`  reglas que **este** proyecto ya se pagó con un error.
- `fichas/{alias}.md`     qué es este proyecto y cómo se trabaja en él.
- `metodo.md`             cómo trabajo siempre, tenga o no tenga proyecto.
- `metodo_proyectos.md`   cómo trabajo **dentro** de un proyecto: verificador,
                          emulador, tu teléfono.

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

BASE = Path(__file__).resolve().parent.parent
METHOD_PATH = BASE / "metodo.md"
METHOD_PROYECTOS_PATH = BASE / "metodo_proyectos.md"

_CACHE: dict[str, str] = {}


def _leer(path: Path) -> str:
    """Un fichero de método, o cadena vacía si no está.

    Vacía y no excepción: un fichero ausente no puede tumbar un run, y este módulo
    tiene que poder cargarse en tests y despliegues mínimos sin el resto del repo.
    """
    key = str(path)
    if key not in _CACHE:
        try:
            _CACHE[key] = path.read_text(encoding="utf-8").strip()
        except OSError:
            _CACHE[key] = ""
    return _CACHE[key]


def load_method() -> str:
    """El método que aplica siempre, tenga o no tenga proyecto."""
    return _leer(METHOD_PATH)


def load_method_proyectos() -> str:
    """El método que solo aplica cuando el encargo tiene un proyecto."""
    return _leer(METHOD_PROYECTOS_PATH)


def method_context(project: str = "") -> str:
    """Bloque listo para inyectar en el system prompt.

    ## Por qué la parte de proyectos se paga solo
    `metodo.md` estaba escrito entero como si siempre hubiera un proyecto: «el
    verificador del proyecto», «pruebo en el emulador», «tu teléfono». Eso hace
    dos cosas malas a la vez. Le dice a Aegis que todo encargo es de trabajo en un
    repo —cuando debe servir para el uso cotidiano—, y hace que una pregunta por
    la mañana cargue ~1500 caracteres de instrucciones sobre emuladores que no
    van a usarse.

    Con el `project` vacío solo entra `metodo.md`: 1915 en vez de 3471.

    Devuelve "" si no hay fichero, porque un system prompt debe poder construirse
    sin este módulo.
    """
    method = load_method()
    if not method:
        return ""
    partes = [f"CÓMO TRABAJO (aplica a todo lo que hagas en este sistema):\n\n{method}"]
    if str(project or "").strip():
        dentro = load_method_proyectos()
        if dentro:
            partes.append(f"CÓMO TRABAJO EN EL PROYECTO '{project}':\n\n{dentro}")
    return "\n\n".join(partes)