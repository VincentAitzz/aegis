"""Servidor MCP "aegis-ops": tools de build e instalación del móvil en el HOST.

El sandbox docker del agente NO tiene Flutter/JDK/adb, así que estas tools
ejecutan el toolchain real del host (usuario demo) vía subprocess:

  * aegis_read_file / aegis_write_file / aegis_patch_file  — edición SEGURA del repo en el host.
  * build_apk(api_host)      — valida el cambio de tema y compila el APK debug.
  * adb_devices()            — estado de adb (conexiones por Mesh/LAN).
  * adb_connect(ip)          — adb connect a un teléfono por su IP Tailscale.
  * install_apk()            — adb install -r + arranque de Aegis Console.

La escritura está restringida al árbol del repo (whitelist), veta .git/.env* y
binomios, y se niega a perseguir secretos. Solo sirve como bus de "ci/cd"
local: un único usuario, cero secretos aquí.
"""

import ast
import inspect
import logging
import os
import re
import subprocess
import typing
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("aegis.bridge.mcp_ops")

#: Se leen aquí y no como import global porque `mcp_ops` se carga en el proceso
#: del MCP, que es **distinto** del bridge: la clave llega por su propia variable
#: de entorno, y leerla de la configuración del otro proceso daría vacío sin
#: avisar —y un APK sin token que solo falla en 401 (A-038).
from .config import get_settings

settings = get_settings()

ROOT = Path("/RUTA/AL/WORKSPACE/aegis")
MOBILE = ROOT / "mobile"
#: La paleta de la app. `build_apk` la lee para no compilar un APK con una marca
#: que no es la de Aegis.
#:
#: Antes este path era `dedsec_colors.dart` y el nombre de la clase iba dentro.
#: Un rebranding no debería obligar a tocar el guardarraíl: si el fichero se
#: renombra y esta constante no se actualiza, `current_brand()` devuelve
#: `<no existe el tema>`, la comparación contra el centinela **no** da igual y la
#: puerta deja de comprobar lo que dice comprobar. En silencio. Por eso la
#: comprobación es de estructura y no de color: sobrevive a los rebranding.
THEME = MOBILE / "lib/core/theme/aegis_palette.dart"

#: Todos los nombres por los que puede estar la paleta. El primero es el bueno;
#: los otros son por los que pasó el repo, para que un árbol a medio migrado
#: siga siendo verificable en vez de dar la paleta por perdida en silencio.
RUTAS_PALETA = (
    MOBILE / "lib/core/theme/aegis_palette.dart",
    MOBILE / "lib/core/theme/aegis_colors.dart",
    MOBILE / "lib/core/theme/dedsec_colors.dart",
)

APK = MOBILE / "build/app/outputs/flutter-apk/app-debug.apk"

# La raíz del repo de Aegis. Las demás raíces y los verificadores por proyecto
# viven en `app/projects.py`: un solo registro, y agregar un proyecto es una fila.

ADB = "/RUTA/AL/SDK-ANDROID/platform-tools"
JAVA = "/RUTA/AL/JDK/bin"
FLUTTER = "/RUTA/A/FLUTTER/bin"

DEFAULT_MESH_IP = "100.101.102.103"                     # galaxy-a17 por Tailscale
DEFAULT_MESH_PORT = "43679"                            # puerto adb de respaldo
DEFAULT_MESH_DEVICE = f"{DEFAULT_MESH_IP}:{DEFAULT_MESH_PORT}"
#: El centinela: el hex con el que el tema nació, antes de tener identidad. Si
#: `brand` sigue siendo este, la app todavía no es Aegis.
#:
#: ## Por qué sigue siendo un hex, y no el nombre de la clase
#: Porque es lo único que no depende de una decisión de nombres. `AegisPalette`
#: se puede renombrar mañana y esta puerta seguiría funcionando; `0xFFC83BFE` es
#: un hecho sobre el color que se está buscando. Lo que sí era frágil era
#: comprobar **el archivo**, y eso ya no se hace.
LEGACY_BRAND = "0xFFC83BFE"

_BRAND_RE = re.compile(r"brand\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)")

# Rutas prohibidas dentro de las raíces (nunca editables vía aegis-ops):
# control de versiones, dependencias instaladas y árboles generados. Editarlos a
# mano rompe el entorno de una forma que ningún test explica después.
#
# `.dev.vars` está aquí porque es donde `wrangler dev` guarda los secrets del
# Worker (incluida la URL de Postgres con contraseña). Allow-listarlo sería darle
# al agente lectura de credenciales, y el escaneo de contenido no lo evita: una
# URL de base de datos no tiene forma de secreto de aspecto «clave».
_DENY_PARTS = (".git", "node_modules", "dist", ".astro", ".wrangler", ".venv",
               "__pycache__", "build", ".next", ".cache", ".dev.vars")
_DENY_NAMES = (".env", ".env.local", ".env.production", ".env.production.local",
               ".dev.vars", ".dev.vars.example")
_BIN_SUFFIXES = (".apk", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".so", ".a",
                 ".idx", ".pack", ".zip", ".keystore", ".jks", ".p12", ".pfx")

# Patrones de secretos: la tool se NEGA a escribir/leer contenido así, y lo
# adivina en el path/archivo (p. ej. .env). Esto NO expone el secreto: solo dice
# que hay algo sensible en esa ruta.
#
# Los de la segunda línea se agregaron cuando Aegis pasó a manejar credenciales de
# Neon: una URL de Postgres y un bearer NO tienen forma de «clave» y pasaban
# limpios. El filtro de placeholders (_PLACEHOLDER_RE) evita el falso positivo
# de bloquear un `.env.example`, que es una plantilla y su trabajo es existir.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|figd_[0-9A-Za-z]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|password\s*[=:]\s*\S+|token\s*[=:]\s*\S+)"
    r"|((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://(?:[^\s:/@]*:)?[^\s@]{4,}@\S+)"
    r"|(NEON_API_KEY\s*[=:]\s*\S+)"
    r"|(Authorization:\s*Bearer\s+\S+)"
    r"|(\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,})"
    r"|((?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token)\s*[=:]\s*[\"']?\S{12,})",
    re.IGNORECASE,
)

# Valores que son plantilla, no secreto. La comparación es sobre el VALOR
# ENTERO, nunca sobre una palabra suelta: una key real de AWS contiene "EXAMPLE"
# en medio, y un filtro que busca la palabra suelta la deja pasar.
_PLACEHOLDER_MARKERS = ("<", "{{", "${", "...", "…")
_PLACEHOLDER_PREFIXES = (
    "cambiar", "cambia", "placeholder", "changeme", "change_me", "your", "tus_", "tu_",
    "ejemplo", "example", "dummy", "fake", "xxx", "valor", "aqui", "aquí", "reemplaza",
)


def _is_placeholder(found: str) -> bool:
    if any(m in found for m in _PLACEHOLDER_MARKERS):
        return True
    raw = found.strip().strip("\"'")
    # El valor es lo que va DESPUÉS del `=` o del `:`. Sin esto, "API_KEY=tus-datos"
    # se compara entero contra los prefijos y una plantilla legítima se bloquea.
    if "=" in raw:
        value = raw.split("=", 1)[1]
    elif ":" in raw and "://" not in raw:
        value = raw.split(":", 1)[1]
    else:
        value = raw.split()[-1] if raw.split() else ""
    # "tus-datos-aqui" y "tus datos aqui" cuentan igual que "tus_datos"
    value = re.sub(r"[^a-z0-9]+", "_", value.strip("\"',;)]").lower())
    return value.startswith(_PLACEHOLDER_PREFIXES)

mcp = FastMCP("aegis-ops")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["JAVA_HOME"] = "/RUTA/AL/JDK"
    env["PATH"] = ":".join([JAVA, FLUTTER, ADB, env.get("PATH", "")])
    return env


def _run(args: list[str], timeout: int = 600,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, env=_env(), timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def _safe_resolve(path: str) -> Path:
    """Resuelve `path` y se asegura de que caiga dentro de una raíz permitida.

    Formas aceptadas:
      * `portafolio/src/lib/db.ts`  → alias explícito
      * `mobile/lib/main.dart`       → relativa a ROOT (aegis)
      * `/ruta/absoluta`            → se valida contra cualquier raíz
    """
    alias = None
    head, sep, rest = path.partition("/")
    from .projects import PROJECTS
    if sep and head in PROJECTS:
        alias, path = head, rest
    if path.startswith(("/", "~")):
        target = Path(path).expanduser().resolve()
    elif alias is not None:
        target = (PROJECTS[alias].root / path).resolve()
    else:
        target = (ROOT / path).resolve()
    roots_r = {a: p.root.resolve() for a, p in PROJECTS.items()}
    if not any(target.is_relative_to(r) for r in roots_r.values()):
        permitidas = ", ".join(str(r) for r in roots_r.values())
        pista = _sugerir_ruta(target, list(roots_r.values()))
        raise ValueError(f"ruta fuera de las raíces permitidas: {target} "
                         f"(permitido: {permitidas}).{pista}")
    if any(p in target.parts for p in _DENY_PARTS):
        raise ValueError(f"ruta prohibida: {target}")
    if (target.name in _DENY_NAMES or target.name.startswith(".env")
            or target.name.startswith(".dev.vars")):
        raise ValueError(f"archivo de entorno prohibido: {target.name}")
    if target.suffix.lower() in _BIN_SUFFIXES:
        raise ValueError(f"archivo binario/no editable: {target.name}")
    if _SECRET_RE.search(target.name):
        raise ValueError(f"nombre de archivo sospechoso de secreto: {target.name}")
    return target


def root_of(path: Path) -> str:
    """Alias de la raíz a la que pertenece un archivo ya resuelto."""
    from .projects import PROJECTS
    for alias, proj in PROJECTS.items():
        if path.is_relative_to(proj.root.resolve()):
            return alias
    return "?"


def _no_secrets(content: str) -> None:
    """Niega contenido con aspecto de secreto. Nunca imprime el valor encontrado."""
    for m in _SECRET_RE.finditer(content):
        found = m.group(0)
        if _is_placeholder(found):
            continue          # es una plantilla: su trabajo es existir
        leak = re.sub(r"[A-Za-z0-9]", "x", found)[:12]
        raise ValueError(f"contenido con posible secreto → denegado (visto: {leak}…)")


def _verificador_de(check: str, test: str) -> str:
    """Los dos argumentos planos del verificador, como el JSON que entiende `alta`.

    Aceptar comas o espacios: lo que viene de un modelo es `a, b` y lo que viene
    de una persona es `a  b`. Normalizar aquí evita que un alto escribe el
    registro con una lista de tres comandos donde había dos.
    """
    def limpia(texto: str) -> list[str]:
        partes = [p.strip() for chunk in str(texto or "").split(",") for p in [chunk]]
        return [p for p in partes if p]
    out: dict[str, list[str]] = {}
    if cs := limpia(check):
        out["check"] = cs
    if ts := limpia(test):
        out["test"] = ts
    import json as _json
    return _json.dumps(out, ensure_ascii=False) if out else ""


@mcp.tool()
def project_create(alias: str, area: str, kind: str, nombre: str = "",
                   alcance: str = "", verificar: str = "",
                   verificar_check: str = "", verificar_test: str = "",
                   db: str = "", carpeta: str = "", ya_existe: bool = False) -> str:
    """Da de alta un proyecto nuevo: carpeta, ficha y registro. Sin tocar Python.

    Es el camino para un encargo nuevo. Deja el proyecto operable por Aegis y
    devuelve su ficha a medio hacer: **la puerta va a negar la escritura** hasta
    que las secciones de fondo estén escritas, y eso es lo correcto, porque
    significa que todavía no se sabe para qué es.

    ## Por qué el verificador va en dos argumentos planos
    `verificar_check` y `verificar_test` son **cadenas**, separadas por comas, no
    un JSON dentro de una cadena. Medido: con un JSON embebido, el modelo lo emite
    como objeto en una llamada y como texto en la siguiente, y basta para que
    los argumentos **no coincidan** con los que se aprobaron. Como el token
    valida la llamada exacta, eso convierte el relanzado en una ruleta y cada
    intento vuelve a pedirte permiso.

    Es la misma clase de error que A-016, dos capas más abajo: el 7B es literal
    con las formas que se le dan. Un argumento simple es un argumento que el
    modelo repite igual.

    Argumentos:
        alias      identificador en minúsculas, sin espacios (ej. `acme-inventario`)
        area       carpeta del workspace donde va (ver WORKSPACE_AREAS)
        kind       encargo | producto | herramienta — decide qué secciones
                   exige la ficha. El tipo se elige según el proyecto, no según
                   lo que te resulte más fácil de responder.
        nombre     nombre legible del proyecto
        alcance    lo que sí entra, si ya lo sabes
        verificar  cómo se verifica. Admite un JSON
                   (`{"check": [...], "test": [...]}`) o una nota. Es la vía para
                   quien escribe la llamada a mano; **para el modelo, usa
                   verificar_check y verificar_test**.
        verificar_check  comandos de chequeo, separados por comas
        verificar_test   comandos de test, separados por comas
        db        motor de la base, si lo tiene: `neon` o vacío si no se sabe.
                   Vacío **no** significa "no tiene": significa "no lo sabemos
                   todavía". La autoridad de los datos nunca es esta máquina.
        carpeta    nombre en disco cuando no coincide con el alias, para dar de
                   alta algo que ya existe (`Sistema-Gestor-Financiero`)
        ya_existe  no crear la carpeta: solo registrar lo que ya está
    """
    from .alta import alta as _alta, AltaInvalida
    try:
        return _alta(alias, area, kind, nombre=nombre, alcance=alcance,
                     verificar=verificar or _verificador_de(
                         verificar_check, verificar_test),
                     db=db, carpeta=carpeta, ya_existe=ya_existe)
    except AltaInvalida as exc:
        return f"ALTA RECHAZADA: {exc}"


@mcp.tool()
def ficha_read(alias: str) -> str:
    """Lee la ficha de un proyecto del workspace.

    Devuelve el texto tal cual, con su tipo y su estado. Si el proyecto no tiene
    ficha, **no falla**: responde diciendo qué secciones habría que escribir, que
    es justo por lo que se la llama — para proponer una, o para preguntar por
    lo que falta.
    """
    from .fichas import leer_para_agente
    return leer_para_agente(alias)


@mcp.tool()
def registry_list() -> str:
    """Qué proyectos puede operar Aegis y qué ficha tiene cada uno.

    Separate de `projects_list`: esa dice qué hay en el disco; esta dice qué está
    en alta y **qué le falta a cada ficha**. Es el punto de partida para trabajar
    un proyecto nuevo: aquí se ve que tres proyectos no tienen ficha escrita.
    """
    from .alta import resumen_registro
    return resumen_registro()


@mcp.tool()
def projects_list() -> str:
    """Qué proyectos hay en el workspace y cuáles puede operar Aegis.

    Responde la pregunta que antes exigía leer código: qué proyectos son, tienen
    verificador, tienen base de datos, y qué les falta para entrar al registro.
    """
    from .workspaces import describe_workspace
    return describe_workspace()


#: Tipos que un modelo small suele envolver en un objeto por error.
_SCALARES = (str, int, float, bool)


def _matches(value: Any, expected: type) -> bool:
    """¿Es `value` del tipo que la tool pide?

    `bool` es subclase de `int`, así que sin este cuidado un `True` se colaría
    como `int` y `1` como `bool`.
    """
    if expected is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    return isinstance(value, expected)


def coerce_args(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Desenvuelve un escalar que el modelo mandó dentro de un objeto.

    Un 7B responde `{"repo": {"type": "portafolio"}}` cuando la tool declara
    `repo: str`. Sin reparar, `PROJECTS.get(dict)` revienta con `TypeError` y el
    run entero se cae por una llamada mal formada. Con reparar, la tool corre.

    La regla es conservadora a propósito: solo desenvuelve si el objeto tiene
    una única clave, o si exactamente uno de sus valores es del tipo que la
    tool pide. Cualquier otra forma se deja intacta para que la validación
    normal la rechace con su mensaje propio.
    """
    if not isinstance(args, dict):
        return args
    try:
        hints = typing.get_type_hints(tool.fn)
    except Exception:  # noqa: BLE001 — si no se puede tipar, no se inventa
        return args
    out = dict(args)
    for key, value in args.items():
        expected = hints.get(key)
        if expected not in _SCALARES or not isinstance(value, dict):
            continue
        if len(value) == 1:
            only = next(iter(value.values()))
            if _matches(only, expected):
                out[key] = only
                continue
        matches = [candidate for candidate in value.values() if _matches(candidate, expected)]
        if len(matches) == 1:
            out[key] = matches[0]
    return out


@mcp.tool()
def repo_verify(what: str = "check", repo: str = "portafolio", tail: int = 40) -> str:
    """Verifica el proyecto: `check` (tipos), `test` (vitest), `build` (astro).

    Es la única tool de verificación a propósito: un modelo 7B rinde peor con
    muchas tools que con una que hace bien una cosa. Sin esto el agente escribe
    a ciegas, y escribir a ciegas es exactamente como falló antes.

    Argumentos:
        what  check | test | build
        repo  alias de la raíz (portafolio | aegis)
        tail  cuántas líneas de salida devolver
    """
    from .projects import PROJECTS
    proj = PROJECTS.get(repo)
    if proj is None:
        return f"repo desconocido: {repo} (conocidos: {', '.join(PROJECTS)})"
    root = proj.root
    if not root.exists():
        return f"la raíz de '{repo}' no existe: {root}"
    node_dir = os.path.expanduser("~/.local/node/bin")
    env = dict(os.environ)
    env["PATH"] = f"{node_dir}:{env.get('PATH', '')}"
    env.setdefault("JAVA_HOME", "/RUTA/AL/JDK")

    spec = proj.verify or {}
    if what not in ("check", "test", "build"):
        return f"what inválido: {what} (usa check, test o build)"
    cmd = spec.get(what)
    if not cmd:
        return (f"'{repo}' no declara verificador para '{what}'. "
                f"Disponibles: {sorted(spec) or 'ninguno'}. "
                f"Sin verificador, el agente solo tiene la validación de sintaxis.")
    exe = Path(cmd[0])
    if not exe.is_absolute() and "/" in cmd[0]:
        # Un binario local del proyecto (node_modules/.bin/...) se ejecuta desde
        # la raíz: si no existe, el proyecto no instaló sus dependencias.
        if not (root / cmd[0]).exists():
            return f"falta {cmd[0]} en {root} (¿`npm install` sin correr?)"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=env, cwd=str(root), timeout=900)
    except subprocess.TimeoutExpired:
        return f"repo_verify({what}) agotó el tiempo"
    except FileNotFoundError as exc:
        return f"repo_verify({what}): no encontré {cmd[0]} ({exc})"
    out = (proc.stdout + proc.stderr).strip().splitlines()
    estado = "OK" if proc.returncode == 0 else f"FALLÓ (exit={proc.returncode})"
    resumen = out[-tail:] if out else ["(sin salida)"]
    return f"repo_verify({what}) en {repo}: {estado}\n" + "\n".join(resumen)


@mcp.tool()
def db_query(project: str, sql: str, limit_rows: int = 200) -> str:
    """Lee datos de la rama de DESARROLLO de un proyecto registrado en Neon.

    Solo admite sentencias que empiecen por SELECT o WITH, y una por llamada.
    Es la herramienta de verificación: los invariantes se comprueban contra la
    base real. No muta nada, y por eso no pide confirmación.

    `project` es un alias del registro (app/neon.py), NO una ruta ni un host.
    """
    from .neon import NeonError, db_query as _query
    try:
        return _query(project, sql, limit_rows=limit_rows)
    except NeonError as exc:
        return f"db_query: {exc}"


@mcp.tool()
def db_migrate(project: str, file: str = "") -> str:
    """Aplica las migraciones de un proyecto contra su rama de DESARROLLO.

    Sin `file`, aplica todas las de `migrations/` en orden. Con `file`, solo esa,
    y tiene que estar dentro de la raíz del proyecto y bajo `migrations/`.

    La URL sale SIEMPRE de la rama registrada: quien llama no elige base, ni rama,
    ni host. El error posible no es "aplicó a producción", es "no encontré esa
    migración".
    """
    from .neon import NeonError, db_migrate as _migrate
    try:
        return _migrate(project, file or None)
    except NeonError as exc:
        return f"db_migrate: {exc}"


@mcp.tool()
def neon_branch(project: str, branch: str = "") -> str:
    """Crea la rama de desarrollo de un proyecto si falta, y dice en qué estado
    están las ramas. Sin argumentos crea la que tenga registrada el proyecto."""
    from .neon import NeonError, neon_branch as _branch
    try:
        return _branch(project, branch or None)
    except NeonError as exc:
        return f"neon_branch: {exc}"


def current_brand() -> str:
    """El hex de `brand` en la paleta del host, o qué le falta.

    ## Por qué busca por una lista de rutas
    Este valor decide si `build_apk` compila. Si el fichero se renombra y aquí
    no se busca el nuevo nombre, devuelve `<no existe el tema>` — que no es igual
    que el centinela, así que la comprobación pasa y el APK sale con lo que
    hubiera. Un guardarraíl que deja de mirar cuando le cambian el nombre es peor
    que uno que no existe, porque parece que sigue ahí.

    El orden es el de la historia del rebranding: primero el nombre propio, y
    los antiguos detrás para que un repo a medio migrar siga siendo verificable.
    """
    for ruta in RUTAS_PALETA:
        try:
            text = ruta.read_text()
        except OSError:
            continue
        m = _BRAND_RE.search(text)
        if m:
            return "0x" + m.group(1).upper()
    return "<no existe el tema>"


def _short_diff() -> str:
    """git diff --stat resumido (trazabilidad del cambio tras build)."""
    proc = _run(["git", "-C", str(ROOT), "diff", "--stat", "--", "mobile/lib"], timeout=30)
    stat = proc.stdout.strip() or "(sin cambios en mobile/lib)"
    return f"git diff --stat\n{stat}\n"


@mcp.tool()
def aegis_read_file(path: str, section: str = "") -> str:
    """Lee un archivo TEXTUAL del repo (whitelist; deniega .env/binar./secretos).

    Argumentos:
        path    ruta `<alias>/…` (p.ej. `portafolio/docs/modelo-datos.md`),
                relativa al repo de Aegis, o absoluta dentro de una raíz.
        section en markdown, opcional: '3' devuelve desde `## 3.` hasta el
                siguiente `## `; '4.4' desde `### 4.4`. Vacío = el archivo
                entero (máx. 400 líneas).
    Devuelve el contenido con números de línea.
    """
    target = _safe_resolve(path)
    if not target.exists():
        return f"NO existe: {target}"
    if target.is_dir():
        return f"es un directorio ({target}); esto no es lectura de archivo."
    data = target.read_bytes()
    if b"\x00" in data[:4096]:
        return f"archivo binario: {target}"
    _no_secrets(data.decode(errors="replace"))
    lines = data.decode(errors="replace").splitlines()
    lo, hi = 1, len(lines)
    if section:
        marker = re.compile(rf"^(#{{2,4}})\s+{re.escape(section)}[.\s]")
        start = end = None
        for idx, ln in enumerate(lines):
            if start is None and marker.match(ln):
                start, level = idx, len(marker.match(ln).group(1))
                continue
            if start is not None:
                other = re.match(r"^(#{2,4})\s", ln)
                if other and len(other.group(1)) <= level:
                    end = idx
                    break
        if start is None:
            heads = [ln for ln in lines if re.match(r"^#{2,4}\s", ln)]
            return (f"No encontré la sección '{section}' en {target}. "
                    f"Encabezados disponibles:\n" + "\n".join(heads[:40]))
        lo = start + 1
        hi = end if end is not None else len(lines)
    body = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines[lo - 1:hi], start=lo))
    return f"{target} (sección '{section}' líneas {lo}-{hi} de {len(lines)})\n---\n{body}"


TS_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".mjs", ".js", ".jsx")
PY_SUFFIXES = (".py",)


def _python_ok(path: Path) -> tuple[bool, str]:
    """Valida la sintaxis de un fuente Python con el parser de la stdlib.

    `ast.parse` no ejecuta nada: no importa el módulo ni pide sus dependencias, y
    por eso sirve sobre un archivo a medio escribir. Cierra el agujero que dejó
    pasar un `def` perdido: hasta ahora los `.py` no se comprobaban en absoluto.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, str(exc)
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return False, f"línea {exc.lineno}: {exc.msg}"
    return True, ""


def _syntax_ok(path: Path) -> tuple[bool, str]:
    """Valida la sintaxis de un fuente. Dart con `dart format`, TS con la API de
    TypeScript: ambos soncheap, no escriben nada y no exigen que el proyecto
    entero typecheque todavía."""
    if path.suffix == ".dart":
        try:
            proc = _run([str(FLUTTER + "/dart"), "format", "--output=none", str(path)], timeout=60)
        except subprocess.TimeoutExpired:
            return True, ""
        if proc.returncode == 0:
            return True, ""
        lines = [ln.strip() for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
        detail = next((ln for ln in lines if ln.startswith("Could not format")), "")
        if not detail:
            detail = next((ln for ln in lines if ln.startswith("line ")), "")
        return False, (detail or (lines[0] if lines else "sintaxis inválida"))
    if path.suffix in PY_SUFFIXES:
        return _python_ok(path)
    if path.suffix in TS_SUFFIXES:
        checker = _root_of_script("check-syntax.mjs")
        if checker is None:
            return True, ""
        try:
            proc = _run(["node", str(checker), str(path)], timeout=90)
        except subprocess.TimeoutExpired:
            return True, ""
        if proc.returncode == 0:
            return True, ""
        out = (proc.stdout + proc.stderr).strip().splitlines()
        return False, " | ".join(out[:6]) or "sintaxis inválida"
    return True, ""


def _root_of_script(name: str) -> Path | None:
    """Busca un script de apoyo en cualquiera de las raíces conocidas."""
    from .projects import PROJECTS
    for proj in PROJECTS.values():
        candidate = proj.root / "scripts" / name
        if candidate.exists():
            return candidate
    return None


def _sugerir_ruta(target: Path, roots: list[Path]) -> str:
    """Deduce la ruta correcta cuando parece que se olvidó un segmento.

    El error real que se repite es `/RUTA/AL/REPO/...` en vez de
    `/RUTA/AL/REPO/...`: el alias es cierto, falta el segmento de
    en medio. Un "ruta no permitida" sin más deja al agente reintentando lo mismo;
    con la ruta buena a la vista, se recupera en un paso.
    """
    t, mejor = list(target.parts), ""
    for root in roots:
        r = list(root.parts)
        comun = 0
        while comun < min(len(r), len(t)) and r[comun] == t[comun]:
            comun += 1
        rr, tt = r[comun:], t[comun:]
        for k in range(min(len(rr), len(tt)), 0, -1):
            if rr[-k:] == tt[:k]:
                cand = str(Path(*(r[:comun] + rr + tt[k:])))
                if cand != str(target) and (not mejor or len(cand) < len(mejor)):
                    mejor = cand
                break
    return f" ¿Querías decir: {mejor}?" if mejor else ""


def _quarantine(target: Path, content: str, detail: str) -> str:
    """Guarda lo que se rechazó y devuelve dónde quedó.

    Revertir protege el repo, pero borrar el contenido destruye la única evidencia
    de por qué falló. Un guardarraíl que solo borra obliga a repetir el error a
    ciegas: el agente no puede leer lo que escribió. Con la cuarentena puede.
    """
    import time

    base = ROOT / "bridge" / "data" / "quarantine"
    try:
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destino = base / f"{stamp}-{target.name}.rejected"
        destino.write_text(
            f"# rechazado: {target}\n# motivo: {detail}\n\n{content}",
            encoding="utf-8")
        return str(destino)
    except OSError:
        return ""


def _write_guarded(target: Path, content: str, before: str | None) -> tuple[bool, str]:
    """Escribe y, si el fuente deja de parsear, revierte. Devuelve (ok, mensaje)."""
    if before is None:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    ok, detail = _syntax_ok(target)
    if ok:
        return True, ""
    if before is None:
        target.unlink(missing_ok=True)
        revert = "se eliminó (era nuevo)"
    else:
        target.write_text(before, encoding="utf-8")
        revert = "se revirtió al contenido anterior"
    copia = _quarantine(target, content, detail)
    pista = (f" Lo que escribiste quedó en {copia}: léelo con aegis_read_file y "
             f"corrige esa línea.") if copia else ""
    return False, (
        f"AVISO: la edición dejó el archivo sin sintaxis válida, así que {revert}.\n"
        f"{detail}\nRepite la edición correctamente (no sustituyas el nombre de la "
        f"constante por su valor).{pista}"
    )


def _denegar_sin_ficha(target: Path) -> str:
    """La puerta: no se escribe en un proyecto que no se sabe qué es.

    Devuelve "" si la ficha está completa, o el motivo del rechazo si no.
    No lanza, a propósito: el motivo vuelve al agente como resultado de la tool,
    se ve en la traza, y puede seguir trabajando en otra cosa. Una excepción
    aquí sería un error opaco, que es justo lo que A-016 vino a evitar.
    """
    from .fichas import exige, FichaIncompleta
    alias = root_of(target)
    if alias == "?":
        return ""
    try:
        exige(alias)
    except FichaIncompleta as exc:
        return (f"ESCRITURA DENEGADA en {target}. {exc} "
                f"Esto no es un fallo: es la regla de no construir nada antes de "
                f"saber para qué. Pregúntale a tu usuario o crea la ficha y vuelve a "
                f"intentar. Leer el proyecto sí se permite: es parte de entenderlo.")
    return ""


@mcp.tool()
def aegis_write_file(path: str, content: str) -> str:
    """Escribe contenido COMPLETO en un archivo del repo (whitelist + anti-secretos).

    Sobrescribe el archivo entero. Si el resultado no parsea, se revierte solo.
    Para cambios quirúrgicos usa aegis_patch_file.

    Requiere que el proyecto tenga su ficha completa: no se escribe en algo que
    no se sabe qué es.
    """
    target = _safe_resolve(path)
    # Orden deliberado: primero los guardarraíles duros (secretos), después la
    # puerta procedural. Si la puerta corriera antes, una ficha ausente
    # enmascararía un secreto en el contenido — y el error que vería el
    # operador hablaría del trámite y no del problema real.
    _no_secrets(content)
    denegado = _denegar_sin_ficha(target)
    if denegado:
        return denegado
    before = target.read_text() if target.exists() else None
    ok, message = _write_guarded(target, content, before)
    if not ok:
        return f"escritura RECHAZADA en {target}. {message}"
    if before is None:
        return f"creado {target}"
    delta = len(content.splitlines()) - len(before.splitlines())
    return f"actualizado {target} ({delta:+d} líneas)\n{_short_diff()}"


@mcp.tool()
def aegis_patch_file(path: str, old: str, new: str, replace_all: bool = False) -> str:
    """Reemplazo quirúrgico: sustituye `old` por `new` en el repo (whitelist).

    Argumentos:
        path        ruta del archivo (relativa al repo o absoluta dentro de él).
        old         fragmento existente a reemplazar (debe ser único a menos
                    que replace_all=true).
        new         texto nuevo.
        replace_all reemplaza todas las ocurrencias de `old` (default: 1°).

    Si el archivo deja de parsear tras el cambio, se revierte automáticamente.
    """
    target = _safe_resolve(path)
    _no_secrets(old + new)
    denegado = _denegar_sin_ficha(target)
    if denegado:
        return denegado
    if not target.exists():
        return f"NO existe: {target}"
    before = target.read_text()
    n = before.count(old)
    if n == 0:
        listing = "\n".join(before.splitlines()[:60])[:3000]
        return (f"aegis_patch_file: no se encontró el fragmento en {target}.\n"
                f"Contenido actual del archivo (para que rehagas la edición exacta):\n"
                f"---8<---\n{listing}\n---8<---")
    if n > 1 and not replace_all:
        return (f"aegis_patch_file: el fragmento aparece {n} veces; pasa replace_all=true "
                f"o afina `old`.")
    content = before.replace(old, new) if replace_all else before.replace(old, new, 1)
    ok, message = _write_guarded(target, content, before)
    if not ok:
        return f"parche RECHAZADO en {target}. {message}"
    replaced = n if replace_all else 1
    return f"aegis_patch_file OK ({replaced} de {n} ocurrencia(s) reemplazada(s)) en {target}"


@mcp.tool()
def build_apk(target: str = "emulador", force: bool = False) -> str:
    """Compila el APK debug para un destino.

    ## target

    - `emulador` (por defecto): apunta a `localhost`, que llega al bridge por
      `adb reverse`, y se marca `AEGIS_ORIGIN=emulador` para que el bridge sepa
      de dónde viene la llamada.
    - `telefono`: apunta a la IP de la tailnet y se marca como `telefono`.

    Confundir los dos produce una app que **arranca pero no ve nada**, que es el
    fallo más difícil de detectar en una prueba. Por eso el destino no se
    adivina: va explícito.

    ## El token va incluido
    Si `AEGIS_API_KEY` está puesta en `bridge/.env`, el APK se compila con ella
    dentro. El valor **no** se devuelve en el mensaje: un secreto que sale por
    la cola del agente es un secreto en la historia del repositorio.

    Antes de compilar valida que el tema se haya recoloreado (si brand sigue
    siendo el magenta original y force=False, aborta con la ruta correcta).
    """
    from .dispositivos import DeviceError, api_host_para, apk_para, TARGETS
    base = target.split(":")[0]
    if base not in TARGETS:
        return f"target inválido: {target!r}. Usa {TARGETS}."
    try:
        api_host = api_host_para(target)
    except DeviceError as exc:
        return f"NO COMPILADO. {exc}"
    brand = current_brand()
    if brand == "<no existe el tema>":
        return (
            "NO COMPILADO: no encuentro la paleta de Aegis. La he buscado en:\n"
            + "".join(f"  {r}\n" for r in RUTAS_PALETA)
            + "No compilo sin saber de qué color es la marca: un APK con la paleta "
            "equivocada se instala igual y no se nota hasta que se abre."
        )
    if not force and brand == LEGACY_BRAND:
        return (
            f"El tema aún NO tiene el tono nuevo: brand = {brand}.\n"
            "Edita primero el archivo host:\n"
            f"  {THEME}\n"
            "  (busca `static const Color brand = Color(...)`)\n"
            "Después vuelve a llamar build_apk. No compilo un APK sin el cambio."
        )
    if not MOBILE.exists():
        return f"No existe el proyecto en {MOBILE}"
    cmd = [
        str(FLUTTER + "/flutter"), "build", "apk", "--debug",
        f"--dart-define=API_HOST={api_host}",
        f"--dart-define=AEGIS_ORIGIN={base}",
    ]
    # El token de la API de operación viaja con el APK. **Nunca se imprime**: va
    # dentro del binario y volvería a la cola de trabajo del agente, que es
    # exactamente el sitio donde un secreto no debe estar.
    #
    # Por qué se mete aquí y no solo en el manual: un APK compilado sin él abre,
    # pinta, y falla **solo** en las secciones nuevas con un 401. Es el fallo que
    # más se parece a "la app va Fallando" y el que más cuesta encontrar, porque
    # la mitad de la app funciona.
    if settings.aegis_api_key:
        cmd.append(f"--dart-define=AEGIS_TOKEN={settings.aegis_api_key}")
    else:
        log.info("build_apk: AEGIS_API_KEY vacía; el APK sale sin token y los "
                 "endpoints nuevos responderán 401")
    try:
        proc = _run(cmd, cwd=MOBILE)
    except subprocess.TimeoutExpired:
        return "build_apk agotó el tiempo (600s). Todo el gradle quedó caliente; reinténtalo."
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-12:])
    # Flutter deja el APK en app-debug.apk siempre. Se mueve al nombre del
    # destino para que instalar en el teléfono no pueda tomar el binario que
    # apunta a localhost, ni el humo tomar el que apunta a la tailnet.
    destino = apk_para(base)
    movido = False
    if proc.returncode == 0 and APK.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(APK.read_bytes())
        APK.unlink()
        movido = destino.exists()
        # Anota con qué token se compiló. Sin esto el humo no puede distinguir
        # "abrió" de "funciona": un APK sin token abre, dibuja y habla con el
        # bridge igual (A-039).
        #
        # ## Por qué se **comprueba** y no se da por hecho
        # La puerta se cierra con «hay clave puesta pero este APK se compiló sin
        # anotar token. Recompílalo», y eso es un mensaje desconcertante cuando
        # lo que hiciste fue justo recompilar. Se llegó a esa situación porque
        # anotar es una escritura que puede fallar en silencio (`OSError` → un
        # `log.warning` que nadie ve) y el resultado —un APK que no puede pasar
        # la puerta— no se refleja en la respuesta de la tool. Ahora el resultado
        # del sellado se **devuelve**, y quien lee sabe si el APK sirve.
        anotado = "no se anoto el token (el APK no podra pasar la puerta)"
        if movido and settings.aegis_api_key:
            from .deploy import _sello_de_token, anotar_token_del_apk
            anotar_token_del_apk(destino, settings.aegis_api_key)
            if not _sello_de_token(destino).exists():
                # ## Por qué esto es un fallo y no un aviso
                # Un APK sin sello **no puede pasar la puerta**: el humo lo
                # rechaza con «se compiló sin anotar token. Recompílalo», que es
                # un mensaje desconcertante cuando lo que hiciste fue justo
                # recompilar. Pasó varias veces antes de que esto existiera, y en
                # cada una el misterio era el mismo: el `log.warning` de dentro de
                # `anotar_token_del_apk` no lo veía nadie, porque la tool
                # respondía como si todo fuera bien.
                #
                # Anotar es una escritura que puede fallar. Si falla, la tool
                # devuelve un fallo con salida distinta de cero, no un APK que no
                # sirve y un mensaje que dice que sí.
                return (f"build_apk FALLÓ al anotar el token de "
                        f"{destino.name}: ese APK no podría pasar la puerta de "
                        "despliegue. Sin sello, el humo no puede distinguir "
                        "'abrió' de 'funciona' (A-039).")
            anotado = f"token anotado en {_sello_de_token(destino).name}"
        elif movido:
            anotado = "sin token (AEGIS_API_KEY vacia: los endpoints nuevos daran 401)"
    ok = proc.returncode == 0 and movido
    diff = _short_diff()
    return (
        f"build_apk {'OK' if ok else 'FALLÓ'} (exit={proc.returncode}). "
        f"brand actual={brand}, api_host={api_host}\n"
        f"APK: {destino}\n"
        f"{anotado}\n"
        f"{diff}\n"
        f"--- salida (tail) ---\n{tail}"
    )


@mcp.tool()
def adb_devices() -> str:
    """Qué dispositivos ve adb, con cuál es el emulador y cuál es tu teléfono.

    Etiquetado a propósito: con los dos conectados, la salida cruda de adb no
    los distingue, y es donde más fácil es instalar en el que no es.
    """
    from .dispositivos import estado_humano, DeviceError
    try:
        return estado_humano()
    except DeviceError as exc:
        return f"no pude listar: {exc}"


def _adb(args: list[str], timeout: int = 60) -> tuple[int, str]:
    """Ejecuta adb tolerando timeouts: un teléfono offline no debe romper la tool."""
    try:
        proc = _run([ADB + "/adb", *args], timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"adb {args[0]} agotó {timeout}s (dispositivo inalcanzable)"
    return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())


def _resolve_device(target: str = "emulador") -> str:
    """El serial del dispositivo para `target`.

    **Ya no hay auto-selección.** Antes esto devolvía el galaxy por mDNS o
    Tailscale, y `install_apk` lanzaba la app encima: una prueba de Aegis te
    podía interrumpir sin avisar. Ahora el emulador es el destino por defecto y
    el teléfono hay que nombrarlo, y aun así pasa por la puerta de despliegue.

    Se mantiene el nombre para no romper llamadas existentes; lo que cambió es
    lo que devuelve.
    """
    from .dispositivos import resolver, DeviceError
    return resolver(target).serial


def _mdns_adb_port() -> str:
    """Puerto adb actual del teléfono vía mDNS (cambia al reiniciar el debug)."""
    proc = _run([ADB + "/adb", "mdns", "services"], timeout=20)
    for line in (proc.stdout or "").splitlines():
        if "_adb-tls-connect" in line and ":" in line:
            port = line.rsplit(":", 1)[-1].strip()
            if port.isdigit():
                return port
    return ""


@mcp.tool()
def adb_connect(target: str = "") -> str:
    """Conecta adb al teléfono. Sin argumentos descubre el puerto por mDNS.

    El puerto de depuración inalámbrica cambia cada vez que se reinicia en el
    teléfono, así que se resuelve con mDNS sobre la IP de la tailnet y, si el
    teléfono no está en la tailnet, sobre la IP de la LAN.

    ## Por qué mira si el **teléfono** está conectado, no si hay algo conectado
    La versión anterior contaba dispositivos conectados y, si encontraba alguno,
    respondía "ya conectado". Con el emulador siempre levantado —que es lo
    normal, porque es donde van todas las pruebas— eso significaba que **nunca
    intentaba conectar el teléfono**: la tool seńalaba éxito y el teléfono
    seguía sin verse. Es un fallo que informa de algo que no ha comprobado, que
    es A-016 con forma de mensaje de tool.

    Además, que un puerto esté **abierto en TCP no significa que adbd sirva**:
    cuando la pantalla del teléfono se bloquea, Android retira la sesión de
    depuración y el anuncio mDNS se queda cacheado. Por eso se intenta de verdad
    y se reporta el fallo, en vez de asumir que por tener el puerto basta.
    """
    from . import dispositivos as disp
    if not target:
        ya = disp.telefono()
        if ya is not None:
            return f"tu teléfono ya está conectado: {ya.serial}"
        candidatos = _puertos_mdns()
        if not candidatos:
            return (
                "No encuentro el teléfono por mDNS. Tres motivos posibles, en "
                "orden:\n"
                "  1. La pantalla está bloqueada: Android apaga la depuración "
                "inalámbrica al bloquearla, y el anuncio que ves es viejo.\n"
                "  2. La depuración inalámbrica está apagada "
                "(Ajustes → Developers).\n"
                "  3. El teléfono no está en la misma red que el portátil.\n"
                "Con la pantalla encendida, vuelve a llamarme.")
        partes = []
        for host, puerto in candidatos:
            code, out = _adb(["connect", f"{host}:{puerto}"], timeout=30)
            partes.append(f"{host}:{puerto} -> {out.strip() or f'exit={code}'}")
            if code == 0 and "connected to" in out:
                return "conectado: " + "; ".join(partes)
        return ("No pude conectar por ninguno de los puertos anunciados:\n  "
                + "\n  ".join(partes)
                + "\nSi el puerto está abierto y adb no contesta, casi siempre "
                  "es que la pantalla del teléfono está bloqueada. Desbloquéala "
                  "con la depuración inalámbrica encendida y vuelve a llamarme.")
    code, out = _adb(["connect", target], timeout=30)
    return f"connect {target} (exit={code}): {out}"


def _puertos_mdns() -> list[tuple[str, str]]:
    """Los pares (host, puerto) que adb anuncia para el teléfono, y solo él.

    ## Por qué se quitan las repeticiones
    adb anuncia el mismo teléfono dos veces y marca el duplicado con ` (2)`, con
    el contador en medio del serial. Sin quitarlo, se intenta dos veces el mismo
    puerto y el mensaje dice que fallaron dos, que se lee como dos teléfonos.

    ## Por qué los dos hosts
    mDNS es link-local: no cruza la tailnet. Si el teléfono está en la red
    privada se anuncia con su IP de LAN; si está fuera, con la de Tailscale. Se
    prueban los dos, y el orden no importa porque `adb connect` dice cuál aceptó.
    """
    proc = _run([ADB + "/adb", "mdns", "services"], timeout=20)
    vistos: set[tuple[str, str]] = set()
    for line in (proc.stdout or "").splitlines():
        if "_adb-tls-connect" not in line or ":" not in line:
            continue
        ultimo = line.rsplit(":", 1)[-1].strip()
        if not ultimo.isdigit():
            continue
        host = line[: line.rindex(":")].split()[-1]
        if "." in host and not host.endswith(f":{ultimo}"):
            host = host.rsplit(".", 1)[0] if host.count(".") > 3 else host
        vistos.add((host, ultimo))
    if not vistos:
        return []
    salida = []
    for host, puerto in sorted(vistos):
        salida.append((host, puerto))
    return salida


@mcp.tool()
def install_apk(target: str = "emulador", lanzar: bool = False,
                token: str = "") -> str:
    """Instala el APK. **Por defecto en el emulador**, nunca en tu teléfono.

    ## target

    - `emulador` (por defecto): el AVD que replica tu galaxy a17. Ahí van todas
      las pruebas. No te interrumpe.
    - `telefono`: pasa por la puerta. Necesita verificación en verde **y** un
      token de autorización de un solo uso que se aprueba desde la app. Sin
      token **no instala**: deja la petición pendiente y te avisa.

    ## lanzar

    Instalar y abrir son cosas distintas. Por defecto `lanzar=False`: instalar
    sin abrir la app molesta mucho menos, y aun así puedes abrirla tú.

    ## La diferencia con antes

    Antes esto apuntaba al teléfono por mDNS y abría la app encima, sin avisar.
    Ahora el teléfono no se elige solo y nunca se abre sin que alguien lo autorice.
    """
    from .deploy import (PuertaCerrada, instalar_en_telefono,
                         pasar_puerta_deploy, pedir_deploy)
    from .dispositivos import apk_para, resolver, DeviceError

    destino = apk_para(target.split(":")[0])
    if not destino.exists():
        return (f"No hay APK para '{target}': {destino}. Compílalo antes con "
                f"build_apk(target='{target}').")
    try:
        dev = resolver(target)
    except DeviceError as exc:
        return f"NO INSTALADO. {exc}"

    # El emulador: siempre pasa. Para eso está.
    if dev.emulador:
        code, out = _adb(["-s", dev.serial, "install", "-r", str(destino)], timeout=600)
        if code != 0:
            return f"install en el emulador falló (exit={code}): {out[:200]}"
        partes = [f"instalado en el emulador {dev.serial}"]
        if lanzar:
            scode, _ = _adb(
                ["-s", dev.serial, "shell", "am", "start", "-n",
                 "com.aegis.aegis_console/.MainActivity"], timeout=90)
            partes.append(f"abierto (exit={scode})")
        return "\n".join(partes)

    # El teléfono: la puerta va antes de tocar nada.
    try:
        # La puerta devuelve el device verificado; el serial sale de ahí. Antes
        # devolvía el serial y cada quien lo resolvía por su cuenta, que es
        # exactamente la forma de instalar en un aparato distinto del comprobado.
        serial = pasar_puerta_deploy(lanzar=lanzar).serial
    except PuertaCerrada as exc:
        return f"NO INSTALADO EN TU TELÉFONO. {exc}"

    if not token:
        from .deploy import buscar_aprobacion, es_primera_instalacion
        if es_primera_instalacion(dev):
            # Primera vez: no hay app corriendo que interrumpir y el botón para
            # aprobar está dentro de la app que aún no está. Se instala sin
            # preguntar; la puerta (analyze, tests, humo y ruta) ya pasó.
            token = ""
        elif buscar_aprobacion(lanzar=lanzar) is not None:
            # Ya hay una aprobación viva: se instala. El token no lo pide ni lo
            # ve el agente, que es justo lo que quiero — si lo manejara, bastaría
            # con que se lo imprimieran una vez para que la puerta no significara nada.
            token = ""
        else:
            peticion = pedir_deploy(
                razon=f"APK verificado, listo para instalar en {serial}",
                lanzar=lanzar)
            return (
                "NO INSTALADO, y es lo correcto: falta tu autorización.\n"
                f"  id de petición: {peticion['id']}\n"
                f"  aviso: {peticion.get('aviso', '')}\n"
                "Ábrelo en el móvil, aprueba y vuelve a llamar a "
                "install_apk(target='telefono'): con la aprobación a la vista, "
                "esta vez instala. Si no lo apruebas, aquí no se instala nada.\n"
                "No vuelvas a llamar a install_apk para que se entere: preguntar "
                "no es instalar. Con la petición viva, una llamada basta.")

    try:
        return instalar_en_telefono(dev, token, lanzar=lanzar)
    except PuertaCerrada as exc:
        return f"NO INSTALADO EN TU TELÉFONO. {exc}"


@mcp.tool()
def deploy_estado() -> str:
    """Estado de la puerta de despliegue: emulador, teléfono y autorizaciones.

    Se mira antes de intentar instalar en el teléfono, para saber si lo que
    falta es el emulador, el teléfono, la verificación o tu aprobación.
    """
    import json as _json

    from .deploy import snapshot
    st = snapshot()
    st["emulador_arriba"] = st.pop("emulador")
    st["telefono_conectado"] = st.pop("telefono")
    st["tokens_vivos"] = (
        "ninguno: hay que aprobar una instalación desde el móvil" if not st["tokens_vivos"]
        else st["tokens_vivos"])
    if st["pendientes"]:
        st["que_hacer"] = ("hay peticiones esperando: aprueba en la app y vuelve a "
                           "llamar a install_apk con el token que te dé")
    else:
        st["que_hacer"] = ("para instalar en el teléfono: llámalo con "
                           "target='telefono', y te devolverá un id de petición "
                           "para aprobar desde la app")
    return _json.dumps(st, ensure_ascii=False, indent=2)


@mcp.tool()
def deploy_smoke() -> str:
    """Comprueba, en el emulador, que el APK arranca y habla con el bridge.

    Esto es lo que la puerta exige antes de tocar tu teléfono. Instala en el
    emulador, lo abre, y verifica que el bridge recibió una llamada marcada como
    'emulador' — porque instalar y arrancar no prueba nada si la app no habla
    con el bridge.
    """
    from .deploy import humo_emulador

    ok, detalle = humo_emulador()
    return ("OK · " + detalle) if ok else ("FALLO · " + detalle)


@mcp.tool()
def verify_deploy(target: str = "emulador") -> str:
    """Comprueba que la app está instalada y corriendo. **En el emulador** por
    defecto; para el teléfono hay que nombrarlo.
    """
    from .dispositivos import resolver, DeviceError
    try:
        dev = resolver(target)
    except DeviceError as exc:
        return f"no pude comprobar nada: {exc}"
    pcode, pid = _adb(["-s", dev.serial, "shell", "pidof", "com.aegis.aegis_console"],
                      timeout=60)
    _, installed = _adb(["-s", dev.serial, "shell", "pm", "list", "packages", "-3"],
                        timeout=60)
    pid_clean = pid.strip() if (pid.strip().split() or [""])[0].isdigit() else ""
    vivo = "corriendo" if pid_clean else "NO está corriendo"
    return (
        f"{dev.etiqueta}={dev.serial} | instalada={'aegis_console' in installed} | "
        f"proceso: {vivo} | pid={pid_clean or '-'} | pidof_exit={pcode}"
    )


def main() -> None:
    log.info("aegis-ops MCP listo (file-tools + build/install del host). brand actual=%s", current_brand())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()