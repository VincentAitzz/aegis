"""Las fases de trabajo: solo se pagan los runs que las piden.

Tres cosas se comprueban aquí, y las tres importan:

- una fase válida **aparece** en el prompt;
- una fase inventada o con traversal **no rompe el run** y no lee nada;
- sin fase, el prompt **no crece**: es el presupuesto del 7B (A-016), y una
  fase que se colara en todos los runs se pagaría en los de operación.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fases  # noqa: E402


class TestCarga(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(fases, "FASES_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        fases._CACHE.clear()
        self.addCleanup(fases._CACHE.clear)

    def test_una_fase_se_lee(self) -> None:
        (self.tmp / "idea.md").write_text("Aterriza la idea.\n", encoding="utf-8")
        self.assertEqual(fases.load_phase("idea"), "Aterriza la idea.")

    def test_una_fase_inventada_no_tumba_nada(self) -> None:
        self.assertEqual(fases.load_phase("no-existe"), "")

    def test_un_nombre_con_traversal_no_lee_fuera(self) -> None:
        """`fase` viene de una app. Un `../` en un parámetro no es una hipótesis."""
        fuera = self.tmp.parent / "secreto.md"
        fuera.write_text("no deberías leerme\n", encoding="utf-8")
        self.assertEqual(fases.load_phase("../secreto"), "")
        self.assertEqual(fases.load_phase(".."), "")

    def test_el_tope_de_caracteres_trunca_y_lo_dice(self) -> None:
        (self.tmp / "larga.md").write_text("x" * (fases.MAX_CHARS + 500),
                                          encoding="utf-8")
        texto = fases.load_phase("larga")
        self.assertLessEqual(len(texto), fases.MAX_CHARS + 40)
        self.assertIn("truncada", texto)

    def test_los_underscores_no_son_fases(self) -> None:
        """Los ficheros con `_` son plantillas o notas, no fases."""
        (self.tmp / "_nota.md").write_text("nada", encoding="utf-8")
        self.assertNotIn("_nota", fases.known_fases())


class TestPrompt(unittest.TestCase):
    def test_sin_fase_no_aporta_nada(self) -> None:
        self.assertEqual(fases.phase_context(""), "")

    def test_la_fase_se_anuncia_con_su_nombre(self) -> None:
        self.assertIn("arquitectura", fases.phase_context("arquitectura"))

    def test_el_prompt_no_crece_sin_fase(self) -> None:
        from app.autopilot import build_system_prompt
        with mock.patch("app.autonomy.almacen", lambda: mock.Mock(
                resume_denegaciones=lambda limite=4: "")):
            a = build_system_prompt("", "aegis", "")
            b = build_system_prompt("", "aegis", "", "arquitectura")
            # Y una fase que no existe deja el prompt exactamente igual, ni una
            # letra más: un parámetro de una app no puede cambiar el prompt.
            c = build_system_prompt("", "aegis", "", "no-existe")
        self.assertNotIn("FASE DE TRABAJO", a)
        self.assertIn("FASE DE TRABAJO", b)
        self.assertEqual(a, c)


class TestLasFasesQueHay(unittest.TestCase):
    """Lo que hay en disco tiene que estar bien escrito, no solo existir."""

    def test_las_fases_publicadas_caben_en_el_presupuesto(self) -> None:
        for nombre in fases.known_fases():
            self.assertLessEqual(len(fases.load_phase(nombre)), fases.MAX_CHARS,
                                 f"la fase '{nombre}' se pasó del tope")

    def test_hay_idea_y_arquitectura(self) -> None:
        self.assertIn("idea", fases.known_fases())
        self.assertIn("arquitectura", fases.known_fases())


if __name__ == "__main__":
    unittest.main()