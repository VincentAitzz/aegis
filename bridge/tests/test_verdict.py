"""Un run solo puede llamarse `success` si ejecutó una tool de verdad.

Regresión de A-016: `hooks.py` marcaba `success` a cualquier `task.done`. El
modelo respondía "OK" sin llamar a ninguna tool, ese "OK" entraba a memoria, y
el recall se lo inyectaba al siguiente run como "episodio similar resuelto". Con
tres episodios falsos, el tool calling del 7B pasó de 7/8 a 0/8.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import hooks  # noqa: E402
from app.memory import ProjectMemory  # noqa: E402


def _trace(directory: str, run_id: str, records: list[dict]) -> str:
    path = os.path.join(directory, f"{run_id}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    return path


def _tool_event(tool: str, error: object = None) -> dict:
    return {"event": "tool.completed",
            "payload": {"data": {"tool": tool, "error": error}}}


class TestToolsExecuted(unittest.TestCase):
    """La traza es la única fuente de veredicto."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.object(hooks.telemetry, "run_path",
                                    side_effect=lambda rid: os.path.join(self.tmp, f"{rid}.jsonl"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_devuelve_las_tools_ok(self) -> None:
        _trace(self.tmp, "r1", [_tool_event("projects_list"), _tool_event("repo_verify")])
        self.assertEqual(hooks.tools_executed("r1"), ["projects_list", "repo_verify"])

    def test_ignora_tools_con_error(self) -> None:
        _trace(self.tmp, "r2", [_tool_event("projects_list", error="boom")])
        self.assertEqual(hooks.tools_executed("r2"), [])

    def test_sin_traza_no_hay_evidencia(self) -> None:
        self.assertEqual(hooks.tools_executed("no-existe"), [])

    def test_no_duplica_nombres(self) -> None:
        _trace(self.tmp, "r3", [_tool_event("projects_list"), _tool_event("projects_list")])
        self.assertEqual(hooks.tools_executed("r3"), ["projects_list"])

    def test_ignora_lineas_corruptas(self) -> None:
        path = _trace(self.tmp, "r4", [_tool_event("projects_list")])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{no es json\n")
        self.assertEqual(hooks.tools_executed("r4"), ["projects_list"])


class TestVeredictoDelEpisodio(unittest.TestCase):
    """Un run sin tool ejecutada no puede grabarse como `success`."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.object(hooks.telemetry, "run_path",
                                    side_effect=lambda rid: os.path.join(self.tmp, f"{rid}.jsonl"))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = mock.patch.object(hooks, "_run_state",
                                     return_value={"agent": "worker", "prompt": "lista los proyectos"})
        patcher2.start()
        self.addCleanup(patcher2.stop)
        patcher3 = mock.patch.object(hooks.hermes, "run_status",
                                     new=mock.AsyncMock(return_value={"final_text": "OK"}))
        patcher3.start()
        self.addCleanup(patcher3.stop)

    def test_con_tool_es_success_y_las_nombra(self) -> None:
        _trace(self.tmp, "ok", [_tool_event("projects_list")])
        ep = asyncio.run(hooks.build_success_episode("ok"))
        self.assertEqual(ep["outcome"], "success")
        self.assertEqual(ep["tools"], ["projects_list"])
        self.assertIn("projects_list", ep["summary"])

    def test_sin_tool_es_conversacion(self) -> None:
        """Un run de Hermes ya no ejecuta tools: eso es por diseño, no un fallo.

        Se llamaba `sin_evidencia`, que era verdad pero envejecía mal: la suma de
        esas conversaciones es veneno con otro nombre (A-016). Y `conversacion`
        dice algo que `sin_evidencia` no: que **no era su trabajo**, no que el
        agente fallara.
        """
        _trace(self.tmp, "falso", [{"event": "run.completed", "payload": {"data": {}}}])
        ep = asyncio.run(hooks.build_success_episode("falso"))
        self.assertEqual(ep["outcome"], "conversacion")
        self.assertEqual(ep["tools"], [])
        # El texto del modelo no se guarda: si se guarda, se reimita como ejemplo.
        self.assertEqual(ep["text"], "")
        self.assertNotEqual(ep["outcome"], "success")

    def test_conversacion_no_entra_al_recall(self) -> None:
        """El filtro del recall es lo que evita que estas conversaciones
        reaparezcan como «episodios resueltos antes». Debe seguir excluyéndolas."""
        memoria = ProjectMemory(SimpleNamespace(
            memory_enabled=False, memory_dir=self.tmp, memory_graph_backend="sqlite",
            memory_recall_k=3, embed_model="nomic-embed-text"))
        ctx = memoria.render_context({"episodes": [
            {"document": "TAREA: algo SOLUCION: ok", "metadata": {"outcome": "conversacion"},
             "distance": 0.01}]})
        self.assertNotIn("algo", ctx)


class TestRecallSoloInyectaResueltos(unittest.TestCase):
    """Un fallo no puede aparecer bajo el rótulo "resueltos antes"."""

    def _memoria(self, directory: str) -> ProjectMemory:
        return ProjectMemory(SimpleNamespace(memory_enabled=False, memory_dir=directory,
                                             memory_graph_backend="sqlite", memory_recall_k=3,
                                             embed_model="nomic-embed-text"))

    def test_filtra_fallos_y_sin_evidencia(self) -> None:
        mem = self._memoria(tempfile.mkdtemp())
        results = {"episodes": [
            {"document": "TAREA: lista proyectos SOLUCION: OK", "metadata": {"outcome": "failed"}, "distance": 0.01},
            {"document": "TAREA: lista proyectos SOLUCION: OK", "metadata": {"outcome": "sin_evidencia"}, "distance": 0.02},
            {"document": "TAREA: arregla el verificador SOLUCION: anadido el test", "metadata": {"outcome": "success"}, "distance": 0.03},
        ], "graph": []}
        ctx = mem.render_context(results)
        self.assertIn("anadido el test", ctx)
        self.assertNotIn("SOLUCION: OK", ctx)

    def test_solo_fallos_no_produce_contexto(self) -> None:
        mem = self._memoria(tempfile.mkdtemp())
        results = {"episodes": [
            {"document": "TAREA: x SOLUCION: nada", "metadata": {"outcome": "sin_evidencia"}, "distance": 0.01},
        ], "graph": []}
        self.assertEqual(mem.render_context(results), "")


if __name__ == "__main__":
    unittest.main()

class TestCoerceArgs(unittest.TestCase):
    """Un 7B envuelve escalares en objetos; la tool debe sobrevivir."""

    def setUp(self) -> None:
        from app.mcp_ops import mcp
        self.tool = mcp._tool_manager.get_tool("repo_verify")

    def _coerce(self, args: dict) -> dict:
        from app.mcp_ops import coerce_args
        return coerce_args(self.tool, args)

    def test_desenvuelve_objeto_con_una_clave(self) -> None:
        self.assertEqual(self._coerce({"repo": {"type": "portafolio"}})["repo"], "portafolio")

    def test_desenvuelve_por_clave_unica(self) -> None:
        self.assertEqual(self._coerce({"repo": {"value": "aegis"}})["repo"], "aegis")

    def test_no_toca_lo_que_ya_esta_bien(self) -> None:
        self.assertEqual(self._coerce({"repo": "portafolio", "tail": 10}),
                         {"repo": "portafolio", "tail": 10})

    def test_ambiguo_no_se_toca(self) -> None:
        # Dos valores del tipo pedido: adivinar sería inventar.
        args = {"repo": {"a": "x", "b": "y"}}
        self.assertEqual(self._coerce(args), args)

    def test_bool_no_sirve_como_string(self) -> None:
        args = {"repo": {"type": True}}
        self.assertEqual(self._coerce(args), args)

    def test_ejecuta_de_verdad_despues_de_reparar(self) -> None:
        from app.autopilot import _execute
        out = _execute("repo_verify", {"what": "check", "repo": {"type": "portafolio"}})
        self.assertNotIn("repo desconocido", out)
        self.assertIn("repo_verify(check)", out)


class TestUnSoloAgente(unittest.TestCase):
    """Aegis tiene un agente. `orchestrator` era configuracion muerta."""

    def test_orchestrator_se_normaliza_a_worker(self) -> None:
        from app.models import TaskIn
        self.assertEqual(TaskIn(prompt="x", agent="orchestrator").agent, "worker")

    def test_default_es_worker(self) -> None:
        from app.models import TaskIn
        self.assertEqual(TaskIn(prompt="x").agent, "worker")

    def test_agente_inventado_se_rechaza(self) -> None:
        from app.models import TaskIn
        with self.assertRaises(Exception):
            TaskIn(prompt="x", agent="inventado")

    def test_registro_de_agentes_tiene_uno_solo(self) -> None:
        from app.main import _agents
        self.assertEqual(list(_agents()), ["worker"])
