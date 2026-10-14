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
from pathlib import Path

#: La raíz del repo: `bridge/app/entorno.py` → `bridge/app` → `bridge` → raíz.
#: `.resolve()` porque un clon puede vivir detrás de un symlink, y un symlink en
#: la raíz rompe la comparación de rutas que hacen los guardarraíles de
#: `mcp_ops.py`.
RAIZ: Path = Path(__file__).resolve().parents[2]

#: `bridge/`, que es donde viven `data/`, `.env` y el paquete `app/`.
BRIDGE: Path = RAIZ / "bridge"
MOBILE: Path = RAIZ / "mobile"


def datos(*partes: str) -> Path:
    """`bridge/data/…`, que es lo que no se versiona.

    Los SQLite de memoria, notas y autonomía cuelgan de aquí. Que sea función y
    no constante permite que los tests apunten a un temporal.
    """
    return BRIDGE.joinpath("data", *partes)


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
