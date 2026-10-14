"""El descubrimiento de proyectos: lo que hay en el disco y lo registrado.

Estas pruebas fijan la regla que costó un error: un subdirectorio de un proyecto
ya registrado no es un proyecto nuevo. `aegis/bridge` tiene requirements.txt, y
sin esa regla aparecía como un proyecto aparte del repo `aegis`.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workspaces import (  # noqa: E402
    MANIFIESTOS,
    alias_de,
    describe_workspace,
    workspace_candidates,
)


class TestWorkspaceCandidates(unittest.TestCase):
    def _ws(self) -> str:
        tmp = tempfile.mkdtemp()
        ws = Path(tmp) / "Workspace"
        # proyecto a nivel 1
        (ws / "suelto").mkdir(parents=True)
        (ws / "suelto" / "package.json").write_text("{}")
        # proyecto a nivel 2 (el caso real del workspace)
        (ws / "web" / "portafolio").mkdir(parents=True)
        (ws / "web" / "portafolio" / "package.json").write_text("{}")
        # carpeta sin código
        (ws / "vision").mkdir(parents=True)
        # oculta
        (ws / ".cache").mkdir(parents=True)
        (ws / ".cache" / "package.json").write_text("{}")
        return str(ws)

    def test_finds_both_depths(self):
        ws = self._ws()
        nombres = {c.name for c in workspace_candidates(ws)}
        self.assertIn("suelto", nombres)
        self.assertIn("portafolio", nombres)

    def test_ignores_folders_without_code_and_hidden(self):
        ws = self._ws()
        nombres = {c.name for c in workspace_candidates(ws)}
        self.assertNotIn("vision", nombres)
        self.assertNotIn(".cache", nombres)

    def test_missing_workspace_is_empty_not_an_error(self):
        self.assertEqual(workspace_candidates("/no/existe/nada"), [])

    def test_every_manifest_is_considered(self):
        self.assertIn("pubspec.yaml", MANIFIESTOS)
        self.assertIn("requirements.txt", MANIFIESTOS)
        self.assertGreaterEqual(len(MANIFIESTOS), 7)


class TestRegisteredProjects(unittest.TestCase):
    def test_registry_roots_all_exist(self):
        from app.projects import PROJECTS
        for alias, cfg in PROJECTS.items():
            self.assertTrue(cfg.root.exists(), f"{alias}: {cfg.root} no existe")

    def test_registered_project_without_manifest_still_shows(self):
        """El repo de Aegis no tiene manifiesto en la raíz, y aun así tiene que
        aparecer: si no, la lista escondería algo que Aegis puede operar."""
        from app.projects import PROJECTS
        texto = describe_workspace()
        for alias in PROJECTS:
            self.assertIn(alias, texto)

    def test_alias_lookup(self):
        """Cada proyecto registrado se reconoce por su carpeta, y solo él.

        Antes miraba `portafolio`, que en un clon ajeno no existe. Ahora recorre
        el registro entero, que es la regla que importa: **todo** lo declarado
        tiene que poder(se) identificar, no uno que-resulta-que-esté.
        """
        from app.projects import PROJECTS
        for alias, cfg in PROJECTS.items():
            with self.subTest(alias=alias):
                self.assertEqual(alias_de(cfg.root), alias)
        self.assertEqual(alias_de(Path("/tmp")), "")

    def test_subproject_of_registered_is_not_a_candidate(self):
        """`aegis/bridge` tiene requirements.txt y NO es un proyecto aparte."""
        from app.projects import PROJECTS
        candidatos = {str(c) for c in workspace_candidates()}
        self.assertNotIn(str(PROJECTS["aegis"].root / "bridge"), candidatos)

    def test_describe_says_what_a_project_can_do(self):
        """Cada proyecto sale con su estado y con su base.

        Que haya al menos uno «solo lectura» no se comprueba contra un nombre: se
        comprueba que **el estado que se imprime es el que declara el registro**,
        para todos. Un test que dice «`portafolio` es migrable» describe la
        máquina; este describe el código.
        """
        from app.projects import PROJECTS
        texto = describe_workspace()
        self.assertRegex(texto, r"registrados")
        for alias, cfg in PROJECTS.items():
            with self.subTest(alias=alias):
                esperado = "migrable" if cfg.can_migrate else "solo lectura"
                linea = next((l for l in texto.splitlines()
                              if l.startswith(alias)), "")
                self.assertIn(esperado, linea,
                              f"{alias}: la línea no dice su estado real")


if __name__ == "__main__":
    unittest.main(verbosity=2)
