"""Tests del grafo conceptual (backend SQLite) + memoria del proyecto.

Corren sin chromadb: gracias a la degradación, el flujo usa el grafo léxico.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory import ProjectMemory  # noqa: E402
from app.memory.sqlite_graph import SQLiteGraph, extract_concepts  # noqa: E402


def _settings(memory_dir: str) -> SimpleNamespace:
    return SimpleNamespace(memory_enabled=False, memory_dir=memory_dir,
                           memory_graph_backend="sqlite", memory_recall_k=3,
                           embed_model="nomic-embed-text")


class TestExtractConcepts(unittest.TestCase):
    def test_extrae_conceptos_frecuentes(self) -> None:
        text = ("Necesito crear un modulo en FastAPI con async y uvloop "
                "FastAPI y uvloop y FastAPI")
        concepts = extract_concepts(text, limit=2)
        self.assertEqual(concepts, ["fastapi", "uvloop"])

    def test_vacio(self) -> None:
        self.assertEqual(extract_concepts(""), [])
        self.assertEqual(extract_concepts("el la y para"), [])


class TestSQLiteGraph(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="aegis-graph-")
        self.g = SQLiteGraph(os.path.join(self.tmp, "brain.db"))

    def test_episodio_enlaza_conceptos(self) -> None:
        ep = {"run_id": "r1", "outcome": "success",
              "prompt": "crea un modulo",
              "summary": "usamos fastapi async", "error": ""}
        concepts = ["fastapi", "async", "uvloop"]
        self.g.save_episode(ep, concepts)
        nbs = self.g.neighbors(["fastapi"], depth=1)
        # fastapi debe estar enlazado con async y uvloop
        found = {n["concept"] for n in nbs}
        self.assertIn("async", found)
        self.assertIn("uvloop", found)
        self.assertTrue(all(n["total_runs"] >= 1 for n in nbs))

    def test_match_episodes_lexico(self) -> None:
        self.g.save_episode({"run_id": "r1", "outcome": "success", "prompt": "hola",
                             "summary": "ejemplo con azure blob", "error": ""}, ["azure"])
        hits = self.g.match_episodes("como hago azure blob?", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["run_id"], "r1")

    def test_sin_conceptos_no_revienta(self) -> None:
        self.g.save_episode({"run_id": "r0", "outcome": "failed",
                             "prompt": "", "summary": "", "error": "x"}, [])
        self.assertEqual(self.g.neighbors([], depth=1), [])


class TestProjectMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="aegis-mem-")
        self.mem = ProjectMemory(_settings(self.tmp))
        # degradación esperada: sin chromadb el store episódico queda off
        self.assertIsNone(self.mem.episodic)
        self.assertEqual(type(self.mem.graph).__name__, "SQLiteGraph")

    def test_remember_recall_render(self) -> None:
        asyncio.run(self.mem.remember({
            "run_id": "r1", "agent": "worker", "outcome": "success",
            "prompt": "haz un worker de rabbitmq con aio-pika",
            "summary": "worker consumiendo colas con aio-pika",
            "text": "ok", "code": ["import aio_pika"], "error": ""}))
        asyncio.run(self.mem.remember({
            "run_id": "r2", "agent": "worker", "outcome": "failed",
            "prompt": "otra tarea de rabbitmq",
            "summary": "FALLO: kafka no encontrado", "text": "x",
            "code": [], "error": "ModuleNotFoundError kafka"}))

        async def run() -> dict:
            ctx = await self.mem.recall("worker de rabbitmq con aio-pika", k=3)
            rendered = self.mem.render_context(ctx)
            return {"ctx": ctx, "rendered": rendered}

        out = asyncio.run(run())
        self.assertIn("Episodios similares", out["rendered"])
        self.assertIn("Contexto de experiencia previa", out["rendered"])
        # el episodio fallido debe quedar guardado con su error/traza
        self.assertIn("ModuleNotFoundError kafka",
                      asyncio.run(self.mem.recall("kafka fallo"))["episodes"][0]["document"])

    def test_status(self) -> None:
        st = self.mem.status()
        self.assertFalse(st["episodic_enabled"])
        self.assertEqual(st["graph_backend"], "SQLiteGraph")


if __name__ == "__main__":
    unittest.main()