"""Regresión del autopilot: parser, whitelist de tools y ciclo real.

    .venv/bin/python -m unittest tests.test_autopilot -v
    AEGIS_SLOW_TESTS=1 .venv/bin/python -m unittest tests.test_autopilot -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.autopilot import (  # noqa: E402
    ToolNotAllowed,
    _execute,
    _looks_truncated,
    _mentions_tool,
    extract_tool_calls,
)
from app.mcp_ops import _safe_resolve, current_brand  # noqa: E402

SLOW = os.environ.get("AEGIS_SLOW_TESTS") == "1"


class TestExtractToolCalls(unittest.TestCase):
    def test_native_json(self):
        self.assertEqual(
            extract_tool_calls('{"name": "build_apk", "arguments": {"api_host": "1.2.3.4"}}'),
            [("build_apk", {"api_host": "1.2.3.4"})],
        )

    def test_prefixed_name(self):
        self.assertEqual(
            extract_tool_calls('{"name": "mcp__aegis_ops__verify_deploy", "arguments": {}}'),
            [("verify_deploy", {})],
        )

    def test_bridge_tool_with_calls_array(self):
        text = ('{"name": "tool_call", "arguments": {"calls": ['
                '{"name": "mcp__aegis_ops__adb_devices", "arguments": {}}]}}')
        self.assertEqual(extract_tool_calls(text), [("adb_devices", {})])

    def test_stdlib_wrapper(self):
        text = ('<stdlib_response>\n{"name": "verify_deploy", "arguments": {}}\n'
                "</stdlib_response>")
        self.assertEqual(extract_tool_calls(text), [("verify_deploy", {})])

    def test_markdown_fence(self):
        self.assertEqual(
            extract_tool_calls('```json\n{"name": "verify_deploy", "arguments": {}}\n```'),
            [("verify_deploy", {})],
        )

    def test_name_outside_json(self):
        self.assertEqual(
            extract_tool_calls('(tool call) build_apk {"api_host": "1.2.3.4"}'),
            [("build_apk", {"api_host": "1.2.3.4"})],
        )

    def test_arguments_as_string(self):
        text = '{"name": "adb_connect", "arguments": "{\\"target\\": \\"1.2.3.4:5555\\"}"}'
        self.assertEqual(extract_tool_calls(text), [("adb_connect", {"target": "1.2.3.4:5555"})])

    def test_two_calls_in_one_text(self):
        text = ('1) {"name":"aegis_read_file","arguments":{"path":"x"}} '
                '2) {"name":"build_apk","arguments":{"api_host":"1.2.3.4"}}')
        self.assertEqual(
            extract_tool_calls(text),
            [("aegis_read_file", {"path": "x"}), ("build_apk", {"api_host": "1.2.3.4"})],
        )

    def test_rejects_plain_text(self):
        self.assertEqual(extract_tool_calls("Listo, el build fue OK."), [])

    def test_rejects_unknown_tool(self):
        self.assertEqual(
            extract_tool_calls('{"name": "rm_rf", "arguments": {"path": "/"}}'), [])

    def test_deduplicates(self):
        text = ('<stdlib_response>{"name": "verify_deploy", "arguments": {}}</stdlib_response>'
                '{"name": "verify_deploy", "arguments": {}}')
        self.assertEqual(extract_tool_calls(text), [("verify_deploy", {})])


class TestDanglingIntent(unittest.TestCase):
    def test_mentions_tool(self):
        for text in ["(tool call)", "(工具调用)", "Llamada a `build_apk` ahora"]:
            self.assertTrue(_mentions_tool(text), text)

    def test_final_answer_is_not_dangling(self):
        self.assertFalse(_mentions_tool("Listo, el build fue OK."))
        self.assertFalse(_mentions_tool(""))

    def test_truncated_placeholder(self):
        self.assertTrue(_looks_truncated("(tool call)"))
        self.assertFalse(_looks_truncated("Una respuesta normal y bastante larga." * 5))


class TestWhitelist(unittest.TestCase):
    def test_unknown_tool_blocked(self):
        with self.assertRaises(ToolNotAllowed):
            _execute("rm_rf", {"path": "/"})

    def test_reads_real_repo(self):
        out = _execute("aegis_read_file", {"path": "mobile/lib/core/theme/dedsec_colors.dart"})
        self.assertIn("brand", out)
        self.assertIn(current_brand(), out)

    def test_path_outside_repo_blocked(self):
        with self.assertRaises(ValueError):
            _execute("aegis_read_file", {"path": "/etc/passwd"})

    def test_secret_content_blocked(self):
        with self.assertRaises(ValueError):
            _execute("aegis_write_file", {
                "path": "mobile/lib/core/theme/dedsec_colors.dart",
                "content": "token = sk-ABCDEFGHIJKLMNOPQRSTUVWX",
            })


@unittest.skipUnless(SLOW, "requiere AEGIS_SLOW_TESTS=1 (llama a Ollama)")
class TestRealCycle(unittest.TestCase):
    def test_model_drives_patch_and_restores(self):
        import asyncio

        from app.autopilot import run_autopilot
        from app.mcp_ops import _syntax_ok

        original = current_brand()
        probe = "0xFF00FF00" if original != "0xFF00FF00" else "0xFF00AA00"
        result = asyncio.run(run_autopilot(
            f"Usa aegis_patch_file para cambiar la constante brand a {probe} en "
            "mobile/lib/core/theme/dedsec_colors.dart. No compiles.",
            ollama_url="http://127.0.0.1:11434",
            model="qwen2.5:7b",
            max_steps=5,
        ))
        tools = [t for t in result["trace"] if t.get("tool")]
        self.assertTrue(tools, f"el modelo no pidió ninguna tool: {result['trace']}")

        path = "mobile/lib/core/theme/dedsec_colors.dart"
        ok, _ = _syntax_ok(_safe_resolve(path))
        self.assertTrue(ok, "el guardarraíl dejó el archivo con sintaxis inválida")
        if current_brand() != original:
            self.assertEqual(current_brand(), probe)
        _execute("aegis_patch_file", {
            "path": path,
            "old": f"Color({current_brand()})",
            "new": f"Color({original})",
        })
        self.assertEqual(current_brand(), original)


class TestSyntaxGuard(unittest.TestCase):
    def test_broken_dart_edit_is_rejected_and_reverted(self):
        from app.mcp_ops import _safe_resolve, _syntax_ok

        path = _safe_resolve("mobile/lib/core/theme/dedsec_colors.dart")
        before = current_brand()
        result = _execute("aegis_patch_file", {
            "path": "mobile/lib/core/theme/dedsec_colors.dart",
            "old": f"static const Color brand = Color({before});",
            "new": "static const Color 0xFF00FF00 = Color(0xFF2EFFA0);",
        })
        self.assertIn("RECHAZADO", result)
        self.assertEqual(current_brand(), before)
        self.assertTrue(_syntax_ok(path)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
