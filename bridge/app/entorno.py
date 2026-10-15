"""Dónde está el repo y dónde está el toolchain. **Un solo sitio.**

## Por qué este módulo existe

Había rutas absolutas repartidas por nueve ficheros: `mcp_ops.py`,
`dispositivos.py`, `deploy.py`, `notas.py`, `autonomy.py`, `verifier.py`,
`workspaces.py`, `projects.py` y `bin/lab/measure-models.py`. Todas apuntaban a
`/ruta/al/repo`, `/ruta/al/jdk` y `/ruta/a/flutter`.

Eso funciona en **una** máquina: la de quien lo escribió. En la de cualquiera que
haga `git clone` no hay `~/Workspace/aegis`, no hay `~/jdk` y no hay Flutter, así
que el bridge falla al importar o —peor— arranca y falla en la primera tool, con
un error que habla de una ruta que el que lee nunca ha visto.

La razón de fondo es la misma que hay detrás de los guardarraíles: **un invariante
que depende de un componente que ya no se usa no es un invariante, es una
intención.** «Funciona en mi máquina» era una intención, escrita como si fuera
una regla.

## La regla

1. **El repo se deriva de este fichero**, no de una constante: `RAIZ` son los
   dos niveles por encima de `app/entorno.py`. Donde Aegis esté clonado, vale.
2. **El toolchain se busca**, no se supone: primero la variable de entorno, luego
   `shutil.which()`, y solo como último recurso las rutas que la documentación de
   Flutter y del JDK ya hacen estándar en Linux. Si no aparece, se devuelve `""`
   y el llamador da un error que **dice qué variable poner** —nunca una ruta
   inventada que no existe.
3. **Nada se escribe fuera del repo** sin que la ruta pase por `datos()`.

Lo que queda fuera de este módulo, y por qué:

- El **workspace** (`~/Workspace` y los proyectos del usuario) sí es
  configurable, pero vive en `Settings.workspace_dir`, porque cambia por entorno
  y no por instalación. Ver `app/config.py`.
- El **Android SDK** se respeta como lo declare el sistema: `ANDROID_SDK_ROOT` o
  `ANDROID_HOME`, que es lo que ya usan Android Studio y la línea de órdenes.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

#: La raíz del repo: `bridge/app/entorno.py` → `bridge/app` → `bridge` → raíz.
#: `.resolve()` porque un clon puede vivir detrás de un symlink, y un symlink en
#: la raíz rompe la comparación de rutas que hacen los guardarraíles de
#: `mcp_ops.py`.
RAIZ: Path = Path(__file__).resolve().parents[2]

#: `bridge/`, que es donde viven `data/`, `.env` y el paquete `app/`.
BRIDGE: Path = RAIZ / "bridge"
MOBILE: Path = RAIZ / "mobile"


_EN_TEST: bool | None = None


def _desde_un_test() -> bool:
    """True si quien llama es un fichero que vive bajo un directorio `tests/`.

    ## Por qué hace falta esto, y por qué no bastaba con `conftest.py`
    Porque **este repo no usa pytest**. `conftest.py` es de pytest:
    `python -m unittest discover -s tests` no lo carga nunca. Se puso, se creyó
    que aislaba, y no aislaba — la fila de test volvió a aparecer en la cola real
    después de «arreglarlo».

    Y `tests/__init__.py` tampoco sirve: con `discover -s tests`, `unittest`
    mete `tests/` en `sys.path` e importa los módulos como **toplevel**, así que
    `__init__.py` no se ejecuta. Comprobado con un `print` dentro.

    Lo que sí funciona es un módulo `test_*.py` (se importa durante el
    descubrimiento) —y por eso existe `tests/test_00_aislamiento.py`—, pero
    **solo si ese módulo participa en la ejecución**. Correr un fichero suelto
    (`python -m unittest tests.test_enfoques`) no lo importa, y la fila se
    volvía a escribir. Verificado: es exactamente lo que pasó.

    ## Lo que se hace aquí
    Que la comprobación sea **estructural y no por importación**: si hay
    `AEGIS_DATA_DIR` se usa, y si no, se mira de dónde viene la llamada. Un
    fichero bajo `tests/` no puede abrir la base de producción ni queriendo.

    ## Y el coste
    Se calcula **una vez** y se cachea. `datos()` se llama al inicializar los
    almacenes, no en un bucle caliente, así que recorrer la pila una vez no
    cuesta nada. El caso normal —producción, sin tests— es una variable de
    entorno vacía y un `False` cacheado.
    """
    global _EN_TEST
    if _EN_TEST is not None:
        return _EN_TEST
    marco = sys._getframe(1)
    _EN_TEST = False
    while marco is not None:
        nombre = marco.f_globals.get("__file__") or ""
        partes = Path(str(nombre)).resolve().parts
        if partes and partes[-1] == "__init__.py":
            partes = partes[:-1]
        if "tests" in partes or "test" in partes[-2:-1]:
            _EN_TEST = True
            break
        marco = marco.f_back
    return _EN_TEST


def datos(*partes: str) -> Path:
    """`bridge/data/…`, que es lo que no se versiona.

    Los SQLite de memoria, notas, autonomía y planes cuelgan de aquí.

    ## Y por qué mira `AEGIS_DATA_DIR`
    Porque sin esto los tests escriben en las bases **reales**, y eso ya pasó:
    el lifespan de FastAPI ejecuta `init_autonomia()` en `test_lifespan.py`, y
    la cola de aprobaciones que ves en el móvil tenía una fila con
    `run_id: "r"` y `path: "x.txt"` — un test pidiendo permiso para escribir una
    fichero de una letra que Aegis nunca escribió.

    El problema no era ese test, que aísla su almacén, sino que **no había un
    sitio donde estar bien por defecto**: cada fichero de pruebas tenía que
    acordarse. Con la variable, es una vez y para todos, y `tests/conftest.py` la
    pone antes de importar nada de `app`.

    ## Por qué una variable y no un argumento
    Porque las bases se abren en la inicialización, que ocurre al importar o al
    arrancar. Un argumento habría que pasarlo por tres sitios, y el cuarto que
    se nace mañana se olvidaría.
    """
    base = os.environ.get("AEGIS_DATA_DIR", "").strip()
    raiz = Path(base) if base else BRIDGE / "data"
    if not base and _desde_un_test():
        # El invariante, puesto donde no se puede saltarse: **desde un fichero
        # bajo `tests/`, las bases van a un temporal**, se invoque como se
        # invoque. Ver `_desde_un_test()` para por qué hace falta.
        raiz = Path(tempfile.mkdtemp(prefix="aegis-test-")) / "data"
    return raiz.joinpath(*partes)


def _buscar(override: str, nombre: str, candidatos: tuple[str, ...]) -> str:
    """Override por entorno → `PATH` → rutas estándar de Linux. `""` si nada.

    El orden importa: `PATH` antes que las rutas estándar, porque en una máquina
    con dos JDK (el del sistema y el de un gestor de versiones) el que está en
    el `PATH` es el que el usuario quiere, aunque el otro exista.
    """
    if override:
        return override.rstrip("/")
    encontrado = shutil.which(nombre)
    if encontrado:
        return str(Path(encontrado).parent)
    for candidato in candidatos:
        ruta = Path(os.path.expanduser(candidato))
        if ruta.is_dir():
            return str(ruta)
    return ""


def adb_dir() -> str:
    """Carpeta de `platform-tools`, o `""` si no hay SDK de Android."""
    return str(Path(android_sdk() or "") / "platform-tools") if android_sdk() else ""


def android_sdk() -> str:
    """Raíz del SDK de Android, o `""` si no se puede saber.

    Es la variable que el propio Android usa (`ANDROID_SDK_ROOT`, o
    `ANDROID_HOME` en las instalaciones más viejas), y de ella se cuelgan tanto
    `platform-tools` como `build-tools`, que es de donde sale el `aapt` que lee
    el APK.
    """
    override = os.environ.get("AEGIS_ADB", "").rstrip("/")
    if override:
        return str(Path(override).parent.parent) if override.endswith("platform-tools") else override
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or ""
    if sdk:
        return sdk.rstrip("/")
    # Sin las dos variables, se prueban las rutas estándar antes de rendirse:
    # es lo que hace la propia línea de órdenes de Android cuando se instala
    # a mano, y evita exigirle al usuario que declare lo que ya tiene.
    for candidato in ("~/Android/Sdk", "~/.local/share/android-sdk", "/opt/android-sdk"):
        ruta = Path(os.path.expanduser(candidato))
        if (ruta / "platform-tools").is_dir():
            return str(ruta)
    return ""


def flutter_dir() -> str:
    """Carpeta `bin` de Flutter, o `""` si no está."""
    return _buscar(os.environ.get("AEGIS_FLUTTER_BIN", ""), "flutter",
                   ("~/development/flutter/bin", "~/flutter/bin",
                    "~/.local/share/flutter/bin"))


def java_home() -> str:
    """`JAVA_HOME`, o `""` si no se puede saber.

    `java` en el `PATH` **no** basta para saber el `JAVA_HOME`: Gradle no lo
    deduce, y por eso aquí se mira dónde está realmente el compilador.
    """
    override = os.environ.get("AEGIS_JAVA_HOME") or os.environ.get("JAVA_HOME") or ""
    if override:
        return override.rstrip("/")
    for candidato in ("~/jdk", "/usr/lib/jvm/default-java", "/usr/lib/jvm/java-21-openjdk"):
        ruta = Path(os.path.expanduser(candidato))
        if (ruta / "bin" / "javac").is_file():
            return str(ruta)
    return ""


def adb() -> str:
    """Ruta al binario `adb`, o `""`."""
    base = adb_dir()
    if base and (Path(base) / "adb").is_file():
        return f"{base}/adb"
    return shutil.which("adb") or ""


def flutter() -> str:
    """Ruta al binario `flutter`, o `""`."""
    base = flutter_dir()
    if base and (Path(base) / "flutter").is_file():
        return f"{base}/flutter"
    return shutil.which("flutter") or ""


def faltan() -> list[str]:
    """Qué falta para poder compilar e instalar, en el formato de un aviso.

    Vive aquí para que el mensaje sea **uno**: siete llamadores redactando su
    propia versión de «no encuentro Flutter» es siete formas de que una diga
    algo untrue.
    """
    ausentes = []
    if not flutter():
        ausentes.append("Flutter (pon AEGIS_FLUTTER_BIN=<ruta>/bin o añádelo al PATH)")
    if not adb():
        ausentes.append("adb (pon ANDROID_SDK_ROOT=<ruta> o AEGIS_ADB=<ruta>/platform-tools)")
    if not java_home():
        ausentes.append("un JDK (pon AEGIS_JAVA_HOME=<ruta> o JAVA_HOME=<ruta>)")
    return ausentes
