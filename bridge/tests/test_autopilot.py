"""Regresión del autopilot: parser, whitelist de tools y ciclo real.

    .venv/bin/python -m unittest tests.test_autopilot -v
    AEGIS_SLOW_TESTS=1 .venv/bin/python -m unittest tests.test_autopilot -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.autopilot import (  # noqa: E402
    ToolNotAllowed,
    _execute,
    _looks_truncated,
    _mentions_tool,
    extract_tool_calls,
)
from app.mcp_ops import (  # noqa: E402
    LEGACY_BRAND,
    RUTAS_PALETA,
    _safe_resolve,
    current_brand,
)

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
        out = _execute("aegis_read_file", {"path": "mobile/lib/core/theme/aegis_palette.dart"})
        self.assertIn("brand", out)
        self.assertIn(current_brand(), out)

    def test_path_outside_repo_blocked(self):
        with self.assertRaises(ValueError):
            _execute("aegis_read_file", {"path": "/etc/passwd"})

    def test_secret_content_blocked(self):
        with self.assertRaises(ValueError):
            _execute("aegis_write_file", {
                "path": "mobile/lib/core/theme/aegis_palette.dart",
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
            "mobile/lib/core/theme/aegis_palette.dart. No compiles.",
            ollama_url="http://127.0.0.1:11434",
            model="qwen2.5:7b",
            max_steps=5,
        ))
        tools = [t for t in result["trace"] if t.get("tool")]
        self.assertTrue(tools, f"el modelo no pidió ninguna tool: {result['trace']}")

        path = "mobile/lib/core/theme/aegis_palette.dart"
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


def _dart_parseable(texto: str) -> bool:
    """¿Este texto Dart parsea? Pregunta a `dart format`, como el guardarraíl.

    No se reimplementa el criterio: el punto es que el test y el guardarraíl
    usen la misma respuesta. Un test con su propio criterio pasa mientras el
    guardarraíl usa otro, que es un test que no mide lo que dice medir.
    """
    from app.mcp_ops import FLUTTER, _run

    with tempfile.NamedTemporaryFile("w", suffix=".dart", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(texto)
        ruta = Path(fh.name)
    try:
        proc = _run([str(FLUTTER + "/dart"), "format", "--output=none", str(ruta)],
                    timeout=60)
        return proc.returncode == 0
    finally:
        ruta.unlink(missing_ok=True)


class TestSyntaxGuard(unittest.TestCase):
    def test_broken_dart_edit_is_rejected_and_reverted(self):
        from app.mcp_ops import _safe_resolve, _syntax_ok

        path = _safe_resolve("mobile/lib/core/theme/aegis_palette.dart")
        antes = path.read_text()
        brand_antes = current_brand()
        # El `old` sale del fichero, no de memoria: si la forma de declarar la
        # constante cambia, un `old` escrito a mano da "no se encontró el
        # fragmento" y el test pasa por el motivo equivocado —no por el rollback
        # de sintaxis que dice estar probando— o falla sin explicar nada.
        declaracion = next(l for l in antes.splitlines() if "brand =" in l)
        # `Color()` **no** sirve: es Dart válido (invocación sin argumentos), así
        # que el guardarraíl de sintaxis lo acepta y lo escribe. La primera
        # versión de este test lo hizo, y dejó `Color()` en la paleta de verdad:
        # un test que rompe el repo mientras corre ya no es un test del guardarraíl.
        # Lo que se rompe de verdad es una llamada sin cerrar.
        nuevo = declaracion.split("=")[0] + "= Color(0xFFFFB020"
        self.assertFalse(
            _dart_parseable(nuevo),
            f"la rotura de prueba sigue siendo Dart valido: {nuevo!r}")
        result = _execute("aegis_patch_file", {
            "path": "mobile/lib/core/theme/aegis_palette.dart",
            "old": declaracion,
            "new": nuevo,
        })
        self.assertIn("RECHAZADO", result, f"la edición no se rechazó: {result}")
        self.assertEqual(current_brand(), brand_antes,
                         "el rechazo no revirtió el cambio de color")
        self.assertEqual(path.read_text(), antes,
                         "el archivo cambió pese al rechazo")
        self.assertTrue(_syntax_ok(path)[0])


class TestElGuardarrailDeLaMarca(unittest.TestCase):
    """La puerta de `build_apk` tiene que seguir mirando, y hay que mirarla.

    ## El fallo que esto previene
    `current_brand()` leía **un solo path**. Ese path era el nombre del fichero
    de la paleta, así que un rebranding lo renombraba — y entonces devolvía
    `<no existe el tema>`, que no es igual que el centinela, con lo que la
    comparación pasaba y `build_apk` compilaba sin que nadie hubiera comprobado
    la marca. Un guardarraíl que deja de mirar cuando le cambian el nombre es
    peor que uno que no existe: parece que sigue ahí.

    ## Por qué el caso bueno importa
    Estos tests usan el fichero de verdad. Un test con un tema inventado en un
    `tmp` probaría el regex contra algo que nadie va a compilar nunca, que es
    justo el error de A-016: pruebas de lo que yo sé, no de lo que hay.
    """

    def test_la_paleta_existe_y_declara_brand(self):
        """Si esto falla, el resto de la puerta está comprobando el vacío."""
        self.assertNotEqual(current_brand(), "<no existe el tema>",
                            f"no encuentro la paleta en {[str(r) for r in RUTAS_PALETA]}")
        self.assertRegex(current_brand(), r"^0x[0-9A-F]{8}$")

    def test_la_app_no_declara_el_centinela(self):
        """Aegis ya no es lo que era al nacer."""
        self.assertNotEqual(current_brand(), LEGACY_BRAND,
                            "la paleta sigue con el tono original: build_apk no "
                            "compilaría y el rebranding no está hecho")

    def test_ninguna_ruta_es_el_mismo_fichero(self):
        """Dos entradas iguales en la lista no vigilan nada dos veces."""
        unicos = {r.resolve() for r in RUTAS_PALETA}
        self.assertEqual(len(unicos), len(RUTAS_PALETA), RUTAS_PALETA)

    def test_el_path_principal_es_el_que_existe(self):
        """El bueno va el primero: si existieran dos, manda el de ahora."""
        self.assertTrue(RUTAS_PALETA[0].exists(), RUTAS_PALETA[0])
        self.assertTrue(str(RUTAS_PALETA[0]).endswith("aegis_palette.dart"))

    def test_el_antiguo_todavia_sirve_para_leer(self):
        """Un repo a medio migrar sigue siendo verificable, no mudo.

        No es hipótesis: durante el rebranding los dos nombres convivieron, y un
        árbol en ese estado tenía que dar una lectura, no `<no existe>`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            viejo = Path(tmp) / "dedsec_colors.dart"
            viejo.write_text("static const Color brand = Color(0xFF123456);",
                             encoding="utf-8")
            original = RUTAS_PALETA
            try:
                import app.mcp_ops as ops
                ops.RUTAS_PALETA = (Path(tmp) / "no-existe.dart", viejo)
                self.assertEqual(ops.current_brand(), "0xFF123456")
            finally:
                import app.mcp_ops as ops
                ops.RUTAS_PALETA = original

    def test_sin_paleta_no_devuelve_un_hex_inventado(self):
        """Falla **diciéndolo**. Un hex plausible sería peor que un fallo."""
        with tempfile.TemporaryDirectory() as tmp:
            import app.mcp_ops as ops
            original = ops.RUTAS_PALETA
            try:
                ops.RUTAS_PALETA = (Path(tmp) / "no-existe.dart",)
                self.assertEqual(ops.current_brand(), "<no existe el tema>")
            finally:
                ops.RUTAS_PALETA = original


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestOnStep(unittest.TestCase):
    """`on_step` es lo que impide que el móvil mire un spinner mudo."""

    def test_el_store_de_runs_se_acota(self):
        from app.main import _AUTOPILOT_RUNS, _AUTOPILOT_RUNS_MAX, _autopilot_trim
        _AUTOPILOT_RUNS.clear()
        for i in range(_AUTOPILOT_RUNS_MAX + 7):
            _AUTOPILOT_RUNS[f"run{i}"] = {"run_id": f"run{i}"}
        _autopilot_trim()
        self.assertEqual(len(_AUTOPILOT_RUNS), _AUTOPILOT_RUNS_MAX)
        # Se van los MAS ANTIGUOS, no los nuevos.
        self.assertNotIn("run0", _AUTOPILOT_RUNS)
        self.assertIn(f"run{_AUTOPILOT_RUNS_MAX + 6}", _AUTOPILOT_RUNS)
        _AUTOPILOT_RUNS.clear()

    def test_existen_las_rutas_de_segundo_plano(self):
        from app.main import app
        pares = {(r.path, tuple(sorted(r.methods))) for r in app.routes
                 if hasattr(r, "methods")}
        self.assertIn(("/autopilot/start", ("POST",)), pares)
        self.assertIn(("/autopilot/{run_id}", ("GET",)), pares)
        # La ruta síncrona se conserva: no se rompe el contrato existente.
        self.assertIn(("/autopilot", ("POST",)), pares)

    def test_run_autopilot_acepta_on_step(self):
        import inspect
        from app.autopilot import run_autopilot
        self.assertIn("on_step", inspect.signature(run_autopilot).parameters)


@unittest.skipUnless(SLOW, "requiere AEGIS_SLOW_TESTS=1 (llama a Ollama)")
class TestOnStepReal(unittest.TestCase):
    def test_cada_paso_se_reporta_antes_de_terminar(self):
        import asyncio

        from app.autopilot import run_autopilot

        vistos = []

        async def on_step(step, entry):
            vistos.append((step, entry.get("tool")))

        result = asyncio.run(run_autopilot(
            "Usa projects_list para listar los proyectos del workspace.",
            ollama_url="http://127.0.0.1:11434",
            model="qwen2.5:7b",
            max_steps=3,
            on_step=on_step,
        ))
        tools_en_traza = [t.get("tool") for t in result["trace"] if t.get("tool")]
        self.assertTrue(tools_en_traza, f"no pidió tools: {result['trace']}")
        self.assertEqual([t for _, t in vistos], tools_en_traza)


class TestControlDeRun(unittest.TestCase):
    """Parar y dirigir un run de autopilot, que era lo que solo sabía hacer Hermes.

    ## Por qué esto se añadió al canal único
    Con un solo motor, la app perdió la única ventaja real que tenía Hermes: no
    se podía parar un run ni decirle nada mientras corría. Un bucle que ejecuta
    tools de verdad en tu disco, sin forma de cortarlo, no es un canal de
    comunicación: es unabove que hay que esperar.

    ## Por qué parar **no** es cancelar la tarea
    `_execute` es síncrono: cortar a mitad deja una escritura sin el paso que la
    explicó, y la traza —que es la evidencia— diría una cosa que no ocurrió. Por
    eso la parada es un `Event` que el bucle consulta **antes de pedirle nada
    más al modelo**: el paso en marcha se termina entero y se registra, y no
    empieza otro.
    """

    def test_el_bucle_acepta_parar_y_extra(self):
        import inspect
        from app.autopilot import run_autopilot
        params = inspect.signature(run_autopilot).parameters
        self.assertIn("parar", params)
        self.assertIn("extra", params)

    def test_las_rutas_de_parar_y_dirigir_existen(self):
        from app.main import app
        pares = {(r.path, tuple(sorted(r.methods))) for r in app.routes
                 if hasattr(r, "methods")}
        self.assertIn(("/autopilot/{run_id}/stop", ("POST",)), pares)
        self.assertIn(("/autopilot/{run_id}/steer", ("POST",)), pares)

    def test_el_trim_no_secome_un_run_vivo(self):
        # Con `parar`, `extra` y `task` dentro del run, podar uno que corre le
        # borra justo lo que lo hace controlable: quien pulsara parar recibiría
        # un 404 y el steer se iría a un queue sin dueño, sin error visible.
        from app.main import _AUTOPILOT_RUNS, _AUTOPILOT_RUNS_MAX, _autopilot_trim
        _AUTOPILOT_RUNS.clear()
        self.addCleanup(_AUTOPILOT_RUNS.clear)

        for i in range(_AUTOPILOT_RUNS_MAX):
            _AUTOPILOT_RUNS[f"v{i}"] = {"run_id": f"v{i}", "status": "running"}
        for i in range(7):
            _AUTOPILOT_RUNS[f"t{i}"] = {"run_id": f"t{i}", "status": "completed"}

        _autopilot_trim()

        for i in range(_AUTOPILOT_RUNS_MAX):
            self.assertIn(f"v{i}", _AUTOPILOT_RUNS,
                          f"el run vivo v{i} se podó: se vuelve incontrolable")
        # Los terminados sí se van: sobraban 7 y había 7 terminados.
        self.assertEqual([r for r in _AUTOPILOT_RUNS if r.startswith("t")], [])

    def test_parar_un_run_terminado_no_da_error(self):
        # Idempotencia: el botón puede quedar pulsado tras terminar el run, y eso
        # no es un fallo que haya que mostrarle a nadie.
        import asyncio
        from app import main as main_mod

        async def caso():
            _AUTOPILOT_RUNS = main_mod._AUTOPILOT_RUNS
            _AUTOPILOT_RUNS.clear()
            try:
                _AUTOPILOT_RUNS["t"] = {"run_id": "t", "status": "completed"}
                return await main_mod.autopilot_stop("t")
            finally:
                _AUTOPILOT_RUNS.clear()

        r = asyncio.run(caso())
        self.assertFalse(r["parado"])
        self.assertIn("ya había terminado", r["detalle"])

    def test_parar_un_run_que_no_existe_explica_por_que(self):
        # Un 404 a secas haría pensar que el id nunca existió. El run ocurrió y su
        # traza está en el JSONL: decirlo es la diferencia entre un error y un
        # dato.
        import asyncio
        from app import main as main_mod
        from fastapi import HTTPException

        async def caso():
            main_mod._AUTOPILOT_RUNS.clear()
            try:
                await main_mod.autopilot_stop("no-existe")
            except HTTPException as exc:
                return exc

        exc = asyncio.run(caso())
        self.assertEqual(exc.status_code, 404)
        self.assertIn("no está vivo", str(exc.detail))

    def test_dirigir_apila_y_el_bucle_lo_drena(self):
        # La cola, no una lista: el endpoint corre en otra tarea y no puede tocar
        # `messages` del bucle mientras este está a mitad de un `await`.
        import asyncio
        from app import main as main_mod

        async def caso():
            store = main_mod._AUTOPILOT_RUNS
            store.clear()
            try:
                store["r"] = {"run_id": "r", "status": "running",
                              "parar": asyncio.Event(), "extra": asyncio.Queue()}
                r = await main_mod.autopilot_steer(
                    "r", main_mod.SteerIn(text="usa el estilo del otro"))
                cola = store["r"]["extra"]
                self.assertTrue(r["aplicada"])
                self.assertFalse(cola.empty())
                return cola.get_nowait()
            finally:
                store.clear()

        self.assertEqual(asyncio.run(caso()), "usa el estilo del otro")

    def test_dirigir_un_run_terminado_no_promete(self):
        import asyncio
        from app import main as main_mod

        async def caso():
            store = main_mod._AUTOPILOT_RUNS
            store.clear()
            try:
                store["t"] = {"run_id": "t", "status": "completed"}
                return await main_mod.autopilot_steer("t", main_mod.SteerIn(text="otra"))
            finally:
                store.clear()

        r = asyncio.run(caso())
        self.assertFalse(r["aplicada"])

    def test_el_estado_no_trieda_serializar_los_objetos_vivos(self):
        # El dict del run guarda `parar`, `extra` y `task`, que son objetos de
        # asyncio y no son JSON. Un `AutopilotStatus(**run)` depende de que
        # pydantic los ignore por defecto; nombrar los campos que salen es lo que
        # hace que este endpoint no se pueda romper al añadir control de un run.
        import asyncio
        from app import main as main_mod

        async def caso():
            store = main_mod._AUTOPILOT_RUNS
            store.clear()
            try:
                store["r"] = {"run_id": "r", "status": "running", "steps": 2,
                              "trace": [{"step": 1, "tool": "projects_list"}],
                              "answer": None, "fin": None, "error": None,
                              "parar": asyncio.Event(), "extra": asyncio.Queue(),
                              "task": None}
                st = await main_mod.autopilot_status("r")
                st.model_dump_json()   # si se colara un Event, esto revienta
                return st
            finally:
                store.clear()

        st = asyncio.run(caso())
        self.assertEqual(st.run_id, "r")
        self.assertEqual(st.steps, 2)
        self.assertEqual(st.status, "running")

    def test_el_prefijo_reconoce_un_run_propio(self):
        # Reconocer un run de autopilot por el prefijo, y no preguntando al buffer:
        # un run ya podado sigue siendo reconocible, y un id de Hermes nunca
        # empieza por aquí.
        from app.main import _AUTOPILOT_PREFIX
        self.assertEqual(_AUTOPILOT_PREFIX, "autopilot-")
        self.assertTrue("autopilot-abc123".startswith(_AUTOPILOT_PREFIX))
        self.assertFalse("run_abc123".startswith(_AUTOPILOT_PREFIX))
