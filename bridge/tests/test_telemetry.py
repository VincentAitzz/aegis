"""Tests de la capa de observabilidad (telemetría JSON)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.telemetry import Telemetry, stopwatch  # noqa: E402


class TestTelemetry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="aegis-tel-")
        self.t = Telemetry(self.tmp)

    def _read(self, path: str) -> list[dict]:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_record_escribe_jsonl_valido(self) -> None:
        self.t.record("INFO", "memory.recall", run_id="r1", prompt_len=10, ms=3.2)
        recs = self._read(self.t.bridge_path)
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["event"], "memory.recall")
        self.assertEqual(rec["run_id"], "r1")
        self.assertAlmostEqual(rec["ms"], 3.2)
        self.assertIn("at", rec)
        self.assertNotIn("trace", rec)  # sin error no traza

    def test_run_event_y_fallo(self) -> None:
        self.t.run_event("r9", "task.done", "worker", "1.0", {"final_text": "ok"})
        self.t.run_failed("r9", "boom")
        path = self.t.run_path("r9")
        self.assertTrue(os.path.isfile(path))
        lines = self._read(path)
        self.assertEqual(lines[0]["event"], "task.done")
        self.assertEqual(lines[0]["agent"], "worker")
        self.assertEqual(lines[1]["event"], "run.failed.detail")
        self.assertIn("boom", lines[1]["error"])
        # además la telemetría global registra el fallo
        global_lines = self._read(self.t.bridge_path)
        self.assertEqual(global_lines[-1]["event"], "run.failed")

    def test_record_sin_run_id(self) -> None:
        self.t.record("WARN", "x")
        rec = self._read(self.t.bridge_path)[0]
        self.assertNotIn("run_id", rec)

    def test_stopwatch(self) -> None:
        with stopwatch() as ms:
            pass
        self.assertGreaterEqual(ms(), 0.0)


if __name__ == "__main__":
    unittest.main()