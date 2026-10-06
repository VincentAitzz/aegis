"""Un run solo puede llamarse `success` si ejecutó una tool de verdad.

Regresión de A-016: `hooks.py` marcaba `success` a cualquier `task.done`. El
modelo respondía "OK" sin llamar a ninguna tool, ese "OK" entraba a memoria, y el
recall se lo inyectaba al siguiente run como "episodio similar resuelto". Con
tres episodios falsos, el tool calling del 7B pasó de 7/8 a 0/8. Ablación medida
(n=8).

## Qué cambió en la Fase 1 y qué es lo mismo
La regla **no** cambió: el veredicto sale de la traza, nunca de `final_text`.
Cambió dónde vive. `hooks.py` solo estaba cableado al relay de Hermes, que desde
el commit `2f1fccb` no creaba runs: su `tools_executed` leía la traza de Hermes
(`payload.data.tool`) mientras el autopilot escribe la suya (`payload.tool`), así
que aunque se hubiera reconnectado habría contado **cero** tools en todos los runs.
Es decir: la invariante de A-016 estaba escrita pero **no se estaba aplicando** a
ningún run real.

Ahora la aplica `app/veredicto.py`, que vive al lado del bucle y lee las tres
formas de traza (memoria, autopilot y Hermes). Estos tests apuntan ahí.
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory import ProjectMemory  # noqa: E402
from app.veredicto import _herramientas, clasificar, desde_jsonl  # noqa: E402


def _evento(tool: str, error: object = None) -> dict:
    """La forma **de Hermes**: la tool cuelga en `payload.data`."""
    return {"event": "tool.completed", "payload": {"data": {"tool": tool, "error": error}}}


def _evento_autopilot(tool: str, ok: bool = True) -> dict:
    """La forma **del autopilot**: la tool cuelga en `payload`, con `ok`."""
    return {"event": "tool.completed", "payload": {"tool": tool, "ok": ok}}


def _jsonl(eventos: list[dict]) -> list[str]:
    import json
    return [json.dumps(e, ensure_ascii=False) for e in eventos]


class TestLaTrazaEsLaUnicaFuente(unittest.TestCase):
    """`final_text` no prueba nada. La traza sí."""

    def test_devuelve_las_tools_ok(self) -> None:
        v = desde_jsonl(_jsonl([_evento("projects_list"), _evento("repo_verify"),
                                {"event": "task.done",
                                 "payload": {"fin": "sin_tools", "answer": "listo"}}]))
        self.assertEqual(v["tools_ok"], ["projects_list", "repo_verify"])

    def test_ignora_tools_con_error(self) -> None:
        ok, rojas = _herramientas([_evento("projects_list", error="boom")])
        self.assertEqual(ok, [])
        self.assertEqual(rojas, ["projects_list"])

    def test_una_tool_roja_no_se_confunde_con_una_verde(self) -> None:
        """El caso que A-016 no cubria: no basta con "hubo tools", tiene que
        haber una que terminó bien."""
        ok, _ = _herramientas([_evento_autopilot("repo_verify", ok=False)])
        self.assertEqual(ok, [])
        v = clasificar("sin_tools", [_evento_autopilot("repo_verify", ok=False)], "hecho")
        self.assertNotEqual(v["estado"], "completado")

    def test_sin_traza_no_hay_evidencia(self) -> None:
        ok, rojas = _herramientas([])
        self.assertEqual((ok, rojas), ([], []))

    def test_no_duplica_nombres(self) -> None:
        ok, _ = _herramientas([_evento("projects_list"), _evento("projects_list")])
        self.assertEqual(ok, ["projects_list"])

    def test_ignora_lineas_corruptas(self) -> None:
        lineas = _jsonl([_evento("projects_list"),
                         {"event": "task.done",
                          "payload": {"fin": "sin_tools", "answer": "listo"}}])
        lineas.insert(1, "{no es json\n")
        v = desde_jsonl(lineas)
        self.assertEqual(v["tools_ok"], ["projects_list"])
        self.assertEqual(v["estado"], "completado")

    def test_un_final_sin_tool_no_es_success(self) -> None:
        """El fallo original, textual: el modelo contesta "OK", no llama a nada."""
        v = desde_jsonl(_jsonl([{"event": "task.done",
                                 "payload": {"fin": "sin_tools", "answer": "OK"}}]))
        self.assertEqual(v["estado"], "incompleto")
        self.assertFalse(v["completado"])


class TestElRecallSoloInyectaResueltos(unittest.TestCase):
    """Un fallo no puede aparecer bajo el rótulo de «resueltos antes»."""

    def _memoria(self, directory: str) -> ProjectMemory:
        return ProjectMemory(SimpleNamespace(memory_enabled=False, memory_dir=directory,
                                             memory_graph_backend="sqlite", memory_recall_k=3,
                                             embed_model="nomic-embed-text"))

    def test_filtra_fallos_y_sin_evidencia(self) -> None:
        mem = self._memoria(tempfile.mkdtemp())
        ctx = mem.render_context({"episodes": [
            {"document": "TAREA: lista proyectos SOLUCION: OK",
             "metadata": {"outcome": "failed"}, "distance": 0.01},
            {"document": "TAREA: lista proyectos SOLUCION: OK",
             "metadata": {"outcome": "sin_evidencia"}, "distance": 0.02},
            {"document": "TAREA: arregla el verificador SOLUCION: anadido el test",
             "metadata": {"outcome": "success"}, "distance": 0.03},
        ], "graph": []})
        self.assertIn("anadido el test", ctx)
        self.assertNotIn("SOLUCION: OK", ctx)

    def test_solo_fallos_no_produce_contexto(self) -> None:
        mem = self._memoria(tempfile.mkdtemp())
        ctx = mem.render_context({"episodes": [
            {"document": "TAREA: x SOLUCION: nada",
             "metadata": {"outcome": "sin_evidencia"}, "distance": 0.01},
        ], "graph": []})
        self.assertEqual(ctx, "")

    def test_conversacion_no_entra_al_recall(self) -> None:
        """Un run de conversación no es un fallo, pero **tampoco** un
        «episodio similar resuelto antes»: su texto se reemitiría como ejemplo,
        que es el camino por el que A-016 envenenó la memoria."""
        mem = self._memoria(tempfile.mkdtemp())
        ctx = mem.render_context({"episodes": [
            {"document": "TAREA: algo SOLUCION: ok",
             "metadata": {"outcome": "conversacion"}, "distance": 0.01}]})
        self.assertNotIn("algo", ctx)


if __name__ == "__main__":
    unittest.main()