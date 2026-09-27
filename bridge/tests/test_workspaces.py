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
        texto = describe_workspace()
        self.assertIn("aegis", texto)
        self.assertIn("portafolio", texto)

    def test_alias_lookup(self):
        from app.projects import PROJECTS
        self.assertEqual(alias_de(PROJECTS["portafolio"].root), "portafolio")
        self.assertEqual(alias_de(Path("/tmp")), "")

    def test_subproject_of_registered_is_not_a_candidate(self):
        """`aegis/bridge` tiene requirements.txt y NO es un proyecto aparte."""
        from app.projects import PROJECTS
        candidatos = {str(c) for c in workspace_candidates()}
        self.assertNotIn(str(PROJECTS["aegis"].root / "bridge"), candidatos)

    def test_describe_says_what_a_project_can_do(self):
        texto = describe_workspace()
        self.assertIn("migrable", texto)          # portafolio
        self.assertIn("solo lectura", texto)      # compra-unida
        self.assertRegex(texto, r"registrados")


if __name__ == "__main__":
    unittest.main(verbosity=2)
