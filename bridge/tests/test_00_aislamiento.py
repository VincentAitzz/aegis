"""Los tests no escriben en la base real. Nunca.

## Qué pasaba

`tests/test_lifespan.py` ejecuta el `lifespan` completo de FastAPI —que es lo
que hace `init_autonomia()`, `init_agenda()` e `init_memory()`—. Es lo que
permite testearlos, y hasta aquí nada malo.

El problema es que esos inicializadores abren **las bases de producción**:
`bridge/data/aegis/autonomia.sqlite3`, `notas.sqlite3` y `planes.sqlite3`. Y en
la cola de aprobaciones que ves en el móvil había una fila así:

    {"id": "ok-f255b6eb7c", "run_id": "r", "paso": 1,
     "tool": "aegis_write_file", "argumentos": '{"path": "x.txt"}',
     "motivo": "Primera vez que toco x.txt en 'aegis'..."}

`run_id: "r"` y `path: "x.txt"`: **un test escribiendo en la cola real**.

## Por qué este fichero se llama `test_00_…` y no `conftest.py`

Porque **este repo no usa pytest**, y `conftest.py` es cosa de pytest:
`python -m unittest discover -s tests` **no lo carga nunca**. Se puso, se creyó
que funcionaba, y no funcionaba: la fila volvió a aparecer después de arreglarlo.

La primera versión del arreglo fue un `tests/conftest.py`, y su propio comentario
decía «el conftest se carga antes que ningún test». Eso es verdad **en pytest** y
falso aquí. En `unittest discover` los módulos se importan como **toplevel**
(`tests/` se mete en `sys.path`), así que ni `tests/__init__.py` se ejecuta:
comprobado, un `__init__.py` con un `print` no imprimió nada bajo
`discover -s tests`.

Lo que sí funciona con `unittest` es un módulo que case con el patrón
`test*.py`, porque el descubrimiento **importa todos los módulos antes de
ejecutar ninguna prueba**. Por eso:

- se llama `test_00_aislamiento`, con dos ceros delante, para que ordene antes
  que cualquier otro `test_*` y quede a la vista **por qué**;
- pone las variables **en el cuerpo del módulo**, no dentro de una prueba, que
  es cuando se ejecuta la importación;
- no define pruebas, y por eso no aparece ningún `test_*` en el recuento.

`conftest.py` se queda, porque si alguien usa pytest el aislamiento tiene que
seguir ahí. Los dos apuntan al mismo sitio.

## Por qué una variable de entorno y no parchear funciones

Porque las bases se abren en la inicialización, que ocurre al importar o al
arrancar. Un argumento habría que pasarlo por tres sitios, y el cuarto que se
nace mañana se olvidaría.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

#: El temporal de la sesión, creado **antes** de que se importe nada de `app.*`.
#: Si `app.config` ya estuviera importado, sus valores por defecto se habrían
#: calculado con la ruta real, y el aislamiento no protegería de nada.
_TMP = Path(tempfile.mkdtemp(prefix="aegis-tests-"))
os.environ["AEGIS_DATA_DIR"] = str(_TMP)

#: Las tres bases, por nombre. Se ponen aunque `AEGIS_DATA_DIR` ya las cubra:
#: una variable explícita no depende de que la función de `datos()` se entere de
#: que existe esta.
os.environ.setdefault("AEGIS_AGENDA_DB", str(_TMP / "notas.sqlite3"))
os.environ.setdefault("AEGIS_AUTONOMIA_DB", str(_TMP / "autonomia.sqlite3"))
os.environ.setdefault("AEGIS_PLANES_DB", str(_TMP / "planes.sqlite3"))
os.environ.setdefault("AEGIS_LOG_DIR", str(_TMP / "logs"))

#: El puente no se anuncia en la LAN desde un test, y `zeroconf` puede tardar
#: 90 s en una red que no contesta.
os.environ.setdefault("AEGIS_SIN_DESCUBRIMIENTO", "1")

#: Rutas que los tests usan y que podrían pisar las reales. Se ignoran al
#: comparar, porque están en el repo y no son dato de nadie.
RAIZ = Path(__file__).resolve().parent.parent

#: Las variables que, puestas, significan «esto es una suite». Un test las
#: comprueba para poder decir «la suite notocó nada» sin tener que compararlo
#: con nada.
VARIABLES = ("AEGIS_DATA_DIR", "AEGIS_AGENDA_DB", "AEGIS_AUTONOMIA_DB",
             "AEGIS_PLANES_DB", "AEGIS_LOG_DIR")


def es_suite() -> bool:
    """True si estamos dentro de una suite y las bases están desviadas."""
    return all(os.environ.get(v) for v in VARIABLES)


import atexit  # noqa: E402


@atexit.register
def _limpiar() -> None:
    """Borra el temporal al terminar la sesión.

    Va en `atexit` y no en un `tearDownClass` porque los SQLite se abren por
    proceso y una suite puede dejar conexiones abiertas: borrar el directorio
    entero es más fiable que intentar cerrarlas todas.
    """
    shutil.rmtree(_TMP, ignore_errors=True)
