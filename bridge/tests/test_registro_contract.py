"""El registro y quienes lo leen no pueden desincronizarse en silencio.

Este test existe por un bug real: `neon.py` leía `cfg.branch` y el campo se
llama `neon_branch`, así que **todas** las llamadas a la base estaban rotas y
ningún test lo notó, porque los tests de Neon mockean la red. El atributo
equivocado no falla en el import: falla cuando alguien usa la base.

Ahora se lee el código de los módulos y se comprueba que cada atributo que
acceden existe de verdad en el dataclass.
"""

import ast
import os
import re
import sys
import unittest
from dataclasses import fields
from pathlib import Path

RAIZ = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(RAIZ))

from app.projects import PROJECTS, Project  # noqa: E402

# Módulos que leen el registro.
CONSUMIDORES = ("neon.py", "mcp_ops.py", "workspaces.py")


def _viene_del_registro(nodo: ast.expr) -> bool:
    """¿La expresión es una lectura del registro (PROJECTS[...], project(), config())?"""
    if isinstance(nodo, ast.Subscript) and isinstance(nodo.value, ast.Name) \
            and nodo.value.id == "PROJECTS":
        return True
    return (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id in {"project", "config"})


def _atributos_leidos(ruta: Path) -> set[str]:
    """Atributos leidos sobre algo que viene del registro.

    Se siguen dos formas: `cfg = project(x)` seguido de `cfg.branch`, y el acceso
    directo `PROJECTS[alias].root`. Solo esas: en `mcp_ops.py` el nombre `proj` se
    reutiliza para un `Project` y para un `Path`, y `Path.exists()` no es un
    campo roto.
    """
    arbol = ast.parse(ruta.read_text())
    de_registro: set[str] = set()
    leidos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            valor = getattr(nodo, "value", None)
            if valor is None or not _viene_del_registro(valor):
                continue
            objetivos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            for objetivo in objetivos:
                for hijo in ast.walk(objetivo):
                    if isinstance(hijo, ast.Name):
                        de_registro.add(hijo.id)
        if isinstance(nodo, ast.Attribute):
            if _viene_del_registro(nodo.value):
                leidos.add(nodo.attr)
            elif (isinstance(nodo.value, ast.Name)
                  and nodo.value.id in de_registro):
                leidos.add(nodo.attr)
    return leidos


class TestRegistroYConsumidores(unittest.TestCase):
    def test_campos_existentes(self):
        campos = {f.name for f in fields(Project)}
        self.assertIn("neon_branch", campos)
        self.assertIn("neon_project", campos)

    def test_ningun_consumidor_lee_un_campo_inexistente(self):
        campos = {f.name for f in fields(Project)}
        for nombre in CONSUMIDORES:
            leidos = _atributos_leidos(RAIZ / "app" / nombre)
            self.assertTrue(leidos, f"{nombre} no lee el registro: revisa el test")
            for attr in sorted(leidos):
                with self.subTest(archivo=nombre, atributo=attr):
                    self.assertIn(
                        attr, campos,
                        f"app/{nombre} lee .{attr}, que no existe en Project")

    def test_todo_proyecto_con_base_tiene_rama(self):
        for alias, cfg in PROJECTS.items():
            if cfg.neon_project:
                self.assertTrue(cfg.neon_branch, f"{alias} tiene base y no rama")

    def test_permisos_coherentes(self):
        """No se puede migrar sin poder crear ramas ni leer."""
        for alias, cfg in PROJECTS.items():
            if cfg.can_migrate:
                self.assertTrue(cfg.can_branch, f"{alias} migra pero no crea ramas")
                self.assertTrue(cfg.can_read, f"{alias} migra pero no lee")

    def test_todo_registro_usa_alias_como_clave(self):
        for alias, cfg in PROJECTS.items():
            self.assertEqual(alias, cfg.alias,
                             f"la clave {alias} no coincide con cfg.alias")


class TestSinCopiasDelRegistro(unittest.TestCase):
    """El registro es una fuente de verdad: una segunda copia es un bug."""

    def test_ningun_otro_modulo_declara_projects(self):
        culpables: list[str] = []
        for ruta in sorted((RAIZ / "app").glob("*.py")):
            if ruta.name == "projects.py":
                continue
            texto = ruta.read_text()
            if re.search(r"^PROJECTS\s*[:=]", texto, re.M):
                culpables.append(ruta.name)
        self.assertEqual(culpables, [], f"copias de PROJECTS en: {culpables}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
