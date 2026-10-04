#!/usr/bin/env python
"""Deriva de un repo lo que se puede derivar, para escribir su ficha.

    .venv/bin/python bin/derivar-ficha.py recepcion-persa

Qué hace: lee el disco y dice el stack, la estructura, la actividad de git y una
propuesta de verificador. Con eso se escriben de verdad las secciones técnicas
de la ficha.

Qué **no** hace, a propósito: inventar el problema, para qué sirve, quién lo usa
ni qué alternativas se consideraron. Eso no está en el repo, y una ficha con
respuestas inventadas es peor que una ficha a medio hacer: la puerta la dejaría
pasar y el agente trabajaría sobre ficción. Eso es exactamente el fallo de A-016,
en otro sitio.

Las secciones que quedan pendientes se imprimen vacías, que es como la puerta
las ve: como no escritas.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fichas  # noqa: E402
from app.projects import PROJECTS, project  # noqa: E402

MANIFIESTOS = {
    "package.json": "Node",
    "pubspec.yaml": "Flutter/Dart",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java/Maven",
    "manage.py": "Django",
}

LOCKS = {
    "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "package-lock.json": "npm",
    "bun.lockb": "bun", "pubspec.lock": "pub", "uv.lock": "uv",
    "poetry.lock": "poetry", "requirements.lock": "pip-tools",
}

IGNORAR = {".git", "node_modules", ".venv", "build", "dist", ".dart_tool",
           "__pycache__", ".next", "coverage", ".idea", ".vscode"}


def _sh(*args: str, cwd: Path) -> str:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def stack(raiz: Path) -> list[str]:
    visto: list[str] = []
    for nombre, etiqueta in MANIFIESTOS.items():
        for _dirpath, subdirs, files in _recorrer(raiz, 2):
            if nombre in files and etiqueta not in visto:
                visto.append(etiqueta)
    for nombre, etiqueta in LOCKS.items():
        for _dirpath, _subdirs, files in _recorrer(raiz, 2):
            if nombre in files and etiqueta not in visto:
                visto.append(etiqueta)
    return visto


def _recorrer(raiz: Path, profundidad: int):
    """Directorios hasta `profundidad` niveles, saltando generados."""
    base = raiz.resolve()
    yield raiz, [d for d in base.iterdir() if d.is_dir()], [
        f.name for f in base.iterdir() if f.is_file()]
    if profundidad <= 1:
        return
    for sub in base.iterdir():
        if not sub.is_dir() or sub.name in IGNORAR or sub.name.startswith("."):
            continue
        yield from _recorrer(sub, profundidad - 1)


def estructura(raiz: Path, limite: int = 12) -> list[str]:
    subs = sorted(d.name for d in raiz.iterdir()
                  if d.is_dir() and d.name not in IGNORAR and not d.name.startswith("."))
    return subs[:limite]


def docs(raiz: Path) -> list[str]:
    """Documentación que ya existe: sirve de fuente para la ficha."""
    salida = []
    for patron in ("*.md", "docs/*.md", "*.txt"):
        salida += [p.name for p in raiz.glob(patron) if p.is_file()]
    return sorted(set(salida))[:14]


def git(raiz: Path) -> dict:
    return {
        "commits": _sh("git", "rev-list", "--count", "HEAD", cwd=raiz) or "?",
        "ultimo": _sh("git", "log", "-1", "--format=%ad (%s)", "--date=short", cwd=raiz) or "?",
        "rama": _sh("git", "branch", "--show-current", cwd=raiz) or "?",
    }


def verificar_sugerido(alias: str) -> dict:
    """Lo que el registro ya declara. Si no declara nada, no se inventa."""
    cfg = PROJECTS.get(alias)
    return dict(cfg.verify) if cfg else {}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    alias = sys.argv[1]
    if alias not in PROJECTS:
        print(f"proyecto no registrado: {alias}")
        print(f"conocidos: {', '.join(sorted(PROJECTS))}")
        return 1
    raiz = project(alias).root
    if not raiz.is_dir():
        print(f"la raíz no existe: {raiz}")
        return 1

    ficha = fichas.read_ficha(alias)
    datos = {
        "alias": alias,
        "raiz": str(raiz),
        "tipo": ficha.kind or "(sin declarar)",
        "secciones_pendientes": ficha.faltan(),
        "stack": stack(raiz),
        "estructura": estructura(raiz),
        "docs": docs(raiz),
        "git": git(raiz),
        "verificador_registrado": verificar_sugerido(alias),
    }
    print(json.dumps(datos, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())