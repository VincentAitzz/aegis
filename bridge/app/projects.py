import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("aegis.bridge.projects")

@dataclass
class Project:
    alias: str
    root: Path
    verify: dict = field(default_factory=dict)
    neon_project: str = ''
    neon_branch: str = 'dev'
    strategy: str = 'psql'
    can_read: bool = True
    can_migrate: bool = False
    can_branch: bool = False
    note: str = ''
    #: Motor de la base del proyecto, tal como lo declara `registro/*.json`:
    #: `neon`, `supabase`, `postgresql`… Vacío = no tiene, o no se sabe. No es
    #: lo mismo que `neon_project`: ese es el id de un proyecto de Neon
    #: concreto, y la mayoría de los clientes no viven ahí.
    db_provider: str = ''

PROJECTS: dict[str, Project] = {
    'aegis': Project(
        alias='aegis',
        root=Path('/RUTA/AL/WORKSPACE/aegis'),
        # No hay typechecker, pero sí un chequeo que vale: importar el paquete.
        # Sin esto el agente escribe Python sin que nada le diga que un símbolo
        # sin importar solo falla al importar, no al escribir.
        verify={
            'check': ['bridge/.venv/bin/python', 'bridge/bin/check-imports.py'],
            'test': ['bridge/.venv/bin/python', '-m', 'unittest', 'discover',
                      '-s', 'bridge/tests', '-q'],
        },
        neon_project='el-proyecto-de-neon-aegis',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
        note='base propia de Aegis. Sin esquema: la memoria sigue local.'
    ),
    'portafolio': Project(
        alias='portafolio',
        root=Path('/RUTA/AL/WORKSPACE/web/portafolio/'),
        verify={
            'check': ['node_modules/.bin/tsc', '--noEmit', '-p', 'tsconfig.json'],
            'test': ['node_modules/.bin/vitest', 'run'],
            'build': ['node_modules/.bin/astro', 'build']
        },
        neon_project='el-proyecto-de-neon-aegis',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=True,
        can_branch=True,
    ),
    'compra-unida': Project(
        alias='compra-unida',
        root=Path('/RUTA/AL/WORKSPACE/apps//compra-unida'),
        verify={
            'check': ['node_modules/.bin/tsc', '--noEmit'],
            'test': ['npm test']
        },
        neon_project='el-proyecto-de-neon-del-cliente',
        neon_branch='dev',
        strategy='drizzle',
        can_read=True,
        can_migrate=False,
        can_branch=True,
        note='journal de drizzle vacío con 24 tablas con datos en production y dev: db:migrate intentaría recrearlas.'
    ),
    'trazeurs': Project(
        alias='trazeurs',
        root=Path('/RUTA/AL/WORKSPACE/mobile//trazeurs'),
        verify={
            'check': ['/RUTA/A/FLUTTER/bin/flutter', 'analyze', '--no-pub'],
            'test': ['/RUTA/A/FLUTTER/bin/flutter', 'test', '--no-pub']
        },
        neon_project='',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
    ),
    'recepcion-persa': Project(
        alias='recepcion-persa',
        root=Path('/RUTA/AL/WORKSPACE/apps//recepcion_persa'),
        verify={
            'check': ['python3', '-m', 'compileall', '-q', '.'],
            'test': ['python3', '-m', 'pytest', '-q']
        },
        neon_project='',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
    )
}

#: Registros que viven en disco (`registro/*.json`), superpuestos a los de arriba.
#:
#: Por qué existe: `PROJECTS` estaba hardcodeado, así que dar de alta un
#: proyecto exigía editar Python. Eso no es un registro, es un parche.
#:
#: Por qué es seguro: **la raíz no se escribe en el fichero**. Se DERIVA de
#: `WORKSPACE/{area}/{alias}`, y tanto `area` como `alias` se validan. Un JSON
#: malicioso no puede apuntar a `/etc`: solo puede declarar que existe un
#: proyecto llamado X en el área Y. El fichero de registro amplía la whitelist,
#: pero no puede ampliarla fuera del workspace.
#:
#: Los proyectos de código que ya estaban (aegis, portafolio…) siguen declarados
#: arriba, con sus verificadores y sus bases. El registro solo añade clientes.

REGISTRO_DIR = Path(__file__).resolve().parent.parent / "registro"

_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,48}$")


class RegistroInvalido(ValueError):
    """Una entrada de `registro/` que no cumple el contrato. No se carga."""


def areas() -> list[str]:
    from .config import get_settings
    return [a.strip() for a in get_settings().workspace_areas.split(",") if a.strip()]


def workspace() -> Path:
    from .config import get_settings
    return Path(get_settings().workspace_dir).resolve()


_CARPETA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")


def _carpeta(valor: str, donde: str) -> str:
    """Nombre de carpeta válido, o se descarta la entrada.

    Es un solo segmento: el registro puede nombrar la carpeta real de un
    proyecto existente, pero no puede abrir la whitelist fuera del workspace.
    """
    valor = str(valor or "")
    if not _CARPETA.match(valor):
        raise RegistroInvalido(f"registro/{donde}: nombre de carpeta inválido {valor!r}")
    return valor


def _cargar_registro() -> dict[str, Project]:
    """Lee `registro/*.json`. Una entrada mala no tumba el arranque: se avisa."""
    from .config import get_settings
    raiz = workspace()
    settings = get_settings()
    permitidas = areas()
    cargados: dict[str, Project] = {}
    if not REGISTRO_DIR.is_dir():
        return cargados
    for fichero in sorted(REGISTRO_DIR.glob("*.json")):
        if fichero.name.startswith("_"):
            continue
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("registro/%s ilegible, se ignora: %s", fichero.name, exc)
            continue
        try:
            alias = str(datos["alias"])
            area = str(datos["area"])
            kind = str(datos["kind"])
            carpeta = _carpeta(datos.get("carpeta") or alias, fichero.name)
        except KeyError as exc:
            log.warning("registro/%s sin campo %s, se ignora", fichero.name, exc)
            continue
        except RegistroInvalido as exc:
            log.warning("%s, se ignora", exc)
            continue
        if not _ALIAS.match(alias):
            log.warning("registro/%s: alias inválido %r, se ignora", fichero.name, alias)
            continue
        if alias in PROJECTS:
            # El código manda sobre el disco: `aegis` y compañía ya están arriba
            # con sus bases y sus verificadores.
            continue
        if area not in permitidas:
            log.warning("registro/%s: área %r no permitida (conocidas: %s), se ignora",
                        fichero.name, area, ", ".join(permitidas))
            continue
        if kind not in ("encargo", "producto", "herramienta"):
            log.warning("registro/%s: kind %r inválido, se ignora", fichero.name, kind)
            continue
        root = raiz / area / _carpeta(datos.get("carpeta") or alias, fichero.name)
        if not str(root.resolve()).startswith(str(raiz)):
            log.warning("registro/%s: la raíz se sale del workspace, se ignora", fichero.name)
            continue
        verify = datos.get("verify") or {}
        if not isinstance(verify, dict):
            verify = {}
        verify = {str(k): [str(c) for c in v] for k, v in verify.items()
                  if isinstance(v, list) and v}
        cargados[alias] = Project(
            alias=alias,
            root=root,
            verify=verify,
            can_read=bool(datos.get("can_read", False)),
            can_migrate=False,   # una base de cliente no se migra desde aquí
            can_branch=False,
            note=str(datos.get("note", "")) or f"alta por registro · area={area}",
            db_provider=str(datos.get("db") or ""),
        )
    return cargados


#: Verificadores de proyecto. Los de código están arriba; los de cliente se
#: leen de `registro/`. Se junta al final del módulo para no intercalar el
#: registro entre las declaraciones.
_DATOS: set[str] = set()


def _recargar_registro() -> dict[str, Project]:
    """Lee `registro/` y recuerda qué aliases salieron de ahí."""
    nuevos = _cargar_registro()
    _DATOS.clear()
    _DATOS.update(nuevos)
    return nuevos


PROJECTS.update(_recargar_registro())


def reload() -> list[str]:
    """Vuelve a leer `registro/*.json` y devuelve los alias declarados en disco.

    Hace falta porque el alta escribe en disco: si el registro solo se leyera al
    importar, un proyecto recién dado de alta quedaría fuera de la whitelist
    hasta el siguiente reinicio del bridge, y la primera escritura en él
    fallaría con un error que no explica la causa.
    """
    for alias in list(_DATOS):
        PROJECTS.pop(alias, None)
    nuevos = _recargar_registro()
    PROJECTS.update(nuevos)
    return sorted(nuevos)


def project(alias: str) -> Project:
    if alias not in PROJECTS:
        raise ValueError(f"proyecto no registrado: {alias} "
                         f"(conocidos: {', '.join(sorted(PROJECTS))})")
    return PROJECTS[alias]


def neon_entry(alias: str) -> dict:
    p = project(alias)
    return {'neon_project': p.neon_project, 'neon_branch': p.neon_branch,
    }