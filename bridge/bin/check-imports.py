#!/usr/bin/env python
"""check-imports.py — ¿importa todo el paquete?

El guardarraíl de sintaxis (`ast.parse`) no ve los nombres: un `field(...)` sin
importar es un archivo perfectamente válido que revienta al importarlo. Ese hueco
apareció el 2026-09-27 con `app/projects.py`, y el verificador que falaba es
justo este: el más barato que dice algo real sobre un proyecto Python.

No ejecuta la app: importa los módulos y nada más. Los efectos secundarios de
importar (que deberían ser ninguno) son un problema del módulo, no de este script.

    .venv/bin/python bin/check-imports.py
"""

import importlib
import pkgutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "app"


def main() -> int:
    if str(PKG.parent) not in sys.path:
        sys.path.insert(0, str(PKG.parent))
    names = [m.name for m in pkgutil.iter_modules([str(PKG)])
             if not m.name.startswith("_")]
    fallos = []
    for name in sorted(names):
        try:
            importlib.import_module(f"app.{name}")
            print(f"  app.{name}: importa")
        except Exception as exc:  # noqa: BLE001 — aquí cualquier excepción cuenta
            fallos.append((name, f"{type(exc).__name__}: {exc}"))
    print(f"\n{len(names) - len(fallos)}/{len(names)} módulos importan")
    for name, err in fallos:
        print(f"  ✗ app.{name}: {err}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
