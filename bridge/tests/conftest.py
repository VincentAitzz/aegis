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

`run_id: "r"` y `path: "x.txt"`: **un test escribiendo en la cola real**. Una
petición de permiso de un fichero de una sola letra que Aegis nunca escribió.

## Por qué está aquí y no en cada test

Porque hacerlo en cada test es lo que no funcionó: cada fichero de pruebas
recuerda aislar su propia base, y basta con que **uno** de ellos ejecuten el
lifespan sin acordarse para que la cola real se contamine. `test_cola_aprobaciones`
sí lo hace bien, con su `_Almacen` temporal — y ese mismo fichero no era el
que fugaba.

Un `conftest.py` lo resuelve **una vez** y cubre los tests que existen y los
que se escriban mañana, que es la parte que importa: el fallo no era de un test,
era de que no había un sitio donde estar bien por defecto.

## Y por qué una variable de entorno y no parchear funciones

Porque las bases se abren por ruta y lo que cambia es **la ruta**. Se pone
`AEGIS_DATA_DIR` antes de que se importe nada de `app.*`, y todas las bases caen
dentro de un temporal que se borra al terminar.

Es además el mecanismo que ya usan las tres variables que existen
(`AEGIS_AGENDA_DB`, `AEGIS_AUTONOMIA_DB`, `AEGIS_PLANES_DB`), pero **por defecto**
y para todo el mundo, en vez de opcional y para quien se acuerde.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: El temporal de la sesión, creado **antes** de importar `app.*`. La posición
#: importa: si `app.config` ya está importado, sus valores por defecto ya se
#: calcularon con la ruta real.
_TMP = Path(tempfile.mkdtemp(prefix="aegis-tests-"))
os.environ["AEGIS_DATA_DIR"] = str(_TMP)

#: Las tres bases, por nombre. Se ponen aunque `AEGIS_DATA_DIR` ya las cubra:
#: una variable explícita no depende de que la función de `datos()` se entere de
#: que existe esta.
os.environ.setdefault("AEGIS_AGENDA_DB", str(_TMP / "notas.sqlite3"))
os.environ.setdefault("AEGIS_AUTONOMIA_DB", str(_TMP / "autonomia.sqlite3"))
os.environ.setdefault("AEGIS_PLANES_DB", str(_TMP / "planes.sqlite3"))
os.environ.setdefault("AEGIS_LOG_DIR", str(_TMP / "logs"))

# El puente no se anuncia en la LAN desde un test, y `zeroconf` puede tardar 90 s
# en una red que no contesta. Está también en `test_lifespan`, que es donde se
# descubrió que hacía falta; aquí está para que **todos** los tests lo tengan.
os.environ.setdefault("AEGIS_SIN_DESCUBRIMIENTO", "1")

if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def _limpiar() -> None:
    """Borra el temporal al terminar la sesión.

    Va en `atexit` y no en un `tearDownClass` porque los SQLite se abren por
    proceso y una suite puede dejar conexiones abiertas: borrar el directorio
    entero es más fiable que intentar cerrarlas todas.
    """
    shutil.rmtree(_TMP, ignore_errors=True)


import atexit  # noqa: E402

atexit.register(_limpiar)