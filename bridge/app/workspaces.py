"""Descubrimiento de proyectos: qué hay en el disco y qué puede operar Aegis.

Existe porque el registro de `projects.py` sabe qué proyectos **deben** existir,
pero no cuáles **hay**: un proyecto nuevo en el workspace pasaba desapercibido
hasta que alguien lo descubriera a mano. Aquí se ven las dos cosas.

Lo escribió el supervisor, no el agente, tras cuatro intentos: ver
`lessons/aegis.md` §A-008.
"""

from pathlib import Path

from .projects import PROJECTS, project

MANIFIESTOS = frozenset({"package.json", "pubspec.yaml", "requirements.txt",
                         "pyproject.toml", "Cargo.toml", "go.mod", "manage.py",
                         "pom.xml"})


def _bajo_registrado(carpeta: Path, raiz: Path) -> bool:
    """¿Algún ancestro de la carpeta ya es un proyecto registrado?

    Sin esto, `aegis/bridge` (que tiene requirements.txt) aparecería como un
    proyecto aparte del repo `aegis`. Un subproyecto no es un proyecto nuevo.
    """
    for ancestro in carpeta.parents:
        if ancestro == raiz:
            break
        for cfg in PROJECTS.values():
            if cfg.root.resolve() == ancestro.resolve():
                return True
    return False


def _tiene_manifiesto(carpeta: Path) -> bool:
    return any((carpeta / m).is_file() for m in MANIFIESTOS)


def workspace_candidates(workspace: str = "/RUTA/AL/WORKSPACE") -> list[Path]:
    """Carpetas que parecen proyecto: tienen un archivo de manifiesto.

    El workspace **no es plano**: sus proyectos viven un nivel más adentro
    (`web/portafolio`, `apps/compra-unida`, `mobile/trazeurs`), pero también
    hay alguno suelto. Se revisan los dos niveles, y se descartan los
    subdirectorios de un proyecto que ya está registrado.
    """
    raiz = Path(workspace)
    if not raiz.is_dir():
        return []
    encontradas: list[Path] = []
    for carpeta in sorted(raiz.iterdir()):
        if not carpeta.is_dir() or carpeta.name.startswith("."):
            continue
        if _tiene_manifiesto(carpeta):
            encontradas.append(carpeta)
        for sub in sorted(carpeta.iterdir()):
            if (sub.is_dir() and not sub.name.startswith(".")
                    and _tiene_manifiesto(sub)
                    and not _bajo_registrado(sub, raiz)):
                encontradas.append(sub)
    return encontradas


def alias_de(carpeta: Path) -> str:
    """Alias registrado para esa carpeta, o cadena vacía si no está registrada."""
    objetivo = carpeta.resolve()
    for alias, cfg in PROJECTS.items():
        if cfg.root.resolve() == objetivo:
            return alias
    return ""


def describe_workspace(workspace: str = "/RUTA/AL/WORKSPACE") -> str:
    """Todo lo que Aegis puede operar, y lo que hay en el disco sin registrar.

    Incluye los proyectos registrados aunque no tengan manifiesto (el repo de
    Aegis no lo tiene), para que la lista nunca esconda algo operativo.
    """
    raiz = Path(workspace)
    candidatos = workspace_candidates(workspace)
    vistos = {c.resolve() for c in candidatos}
    lineas = []

    for carpeta in candidatos:
        alias = alias_de(carpeta)
        if not alias:
            rel = carpeta.relative_to(raiz) if carpeta.is_relative_to(raiz) else carpeta
            lineas.append(f"{str(rel):22} tiene código pero NO está en el registro")
            continue
        cfg = project(alias)
        verificador = ", ".join(sorted(cfg.verify)) or "sin verificador"
        base = cfg.neon_project or "sin base"
        estado = "migrable" if cfg.can_migrate else "solo lectura"
        lineas.append(f"{alias:22} {verificador:24} {base:22} {estado}")
        if cfg.note:
            lineas.append(f"{'':22} ↳ {cfg.note[:70]}")

    for alias, cfg in PROJECTS.items():
        if cfg.root.resolve() in vistos:
            continue
        verificador = ", ".join(sorted(cfg.verify)) or "sin verificador"
        estado = "migrable" if cfg.can_migrate else "solo lectura"
        lineas.append(f"{alias:22} {verificador:24} {cfg.neon_project or 'sin base':22} "
                      f"{estado} (sin manifiesto)")

    registrados = sum(1 for c in candidatos if alias_de(c))
    sin_registrar = len(candidatos) - registrados
    lineas.append(f"\n{registrados} registrados · {sin_registrar} con código sin registrar "
                  f"· {len(PROJECTS)} en el registro")
    return "\n".join(lineas)
