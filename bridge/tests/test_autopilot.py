"""Regresión del autopilot: parser, whitelist de tools y ciclo real.

    .venv/bin/python -m unittest tests.test_autopilot -v
    AEGIS_SLOW_TESTS=1 .venv/bin/python -m unittest tests.test_autopilot -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    from app import entorno
    from app.mcp_ops import _run

    dart = f"{entorno.flutter_dir()}/dart" if entorno.flutter_dir() else ""
    if not dart or not Path(dart).is_file():
        raise unittest.SkipTest(
            "sin `dart`: este test **necesita** el comprobador. No se salta el "
            "guardarraíl y se dice «ok» —eso sería probar que no hace nada—. "
            "Sin Flutter, la comprobación de que el guardarraíl atrapa un Dart "
            "roto no se puede hacer, y se dice en voz alta.")
    with tempfile.NamedTemporaryFile("w", suffix=".dart", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(texto)
        ruta = Path(fh.name)
    try:
        proc = _run([dart, "format", "--output=none", str(ruta)], timeout=60)
        return proc.returncode == 0
    finally:
        ruta.unlink(missing_ok=True)


class TestSyntaxGuard(unittest.TestCase):
    def test_broken_dart_edit_is_rejected_and_reverted(self):
        """El guardarraíl atrapa un Dart roto y **revierte**, y no toca el repo.

        ## Por qué se salta en vez de degradar
        La otra mitad de este comportamiento —«sin `dart`, `_syntax_ok` dice que
        está bien»— sí se prueba en todas partes, porque es lo que tiene que
        pasar en una máquina sin toolchain. Aquí lo que se prueba es lo
        contrario: que **con** comprobador el rollback ocurre. Sin comprobador
        no hay nada que probar, y un test que pasara porque no hizo nada sería
        peor que uno que se salta y lo dice.
        """
        from app.mcp_ops import _safe_resolve, _syntax_ok
        _dart_parseable("void main() {}")   # salta aquí si no hay Dart

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


# =============================================================================
# P0 · El run nunca se muere sin decir por qué
# =============================================================================

class _FalsoOllama:
    """Un Ollama que responde lo que le pongas, sin llamar a ningún modelo.

    Los tests de estos casos usan **esto** y no `qwen2.5:7b`: lo que se comprueba
    es la reacción del bucle, no la capacidad del modelo. Un test que depende del
    modelo pasa un día y falla otro sin que haya cambiado nada.
    """

    def __init__(self, respuestas, fallo=None):
        self.respuestas = list(respuestas)
        self.fallo = fallo
        self.llamadas = 0

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **k):
        self.llamadas += 1
        if self.fallo is not None:
            raise self.fallo
        i = min(self.llamadas - 1, len(self.respuestas) - 1)
        cuerpo = self.respuestas[i]
        return _Respuesta(cuerpo)


class _Respuesta:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {
            "content": self._cuerpo.get("texto", ""),
            "tool_calls": [{"function": {"name": c["name"], "arguments": c["args"]}}
                           for c in self._cuerpo.get("calls", [])]}}]}


def _verdict_rojo(problemas: int):
    """El veredicto que devuelve el verificador cuando el rojo no se mueve."""
    from app import verifier
    texto = "\n".join(f"error: algo roto {i}" for i in range(problemas))
    return verifier.Verdict(
        ok=False, what="check", proyecto="aegis", exit_code=1,
        resumen=texto, firmas=verifier.firmas_de(texto), ms=1, error="")


def _arrancar_con_cliente(client, **kw):
    import asyncio
    from unittest import mock
    from app.autopilot import run_autopilot
    with mock.patch("app.autopilot.httpx.AsyncClient", return_value=client):
        return asyncio.run(run_autopilot(
            kw.pop("prompt", "encargo"), ollama_url="http://falso", model="m",
            max_steps=kw.pop("max_steps", 4), **kw))


class TestElRunSiempreDicePorqueTermino(unittest.TestCase):
    """Cada salida del bucle tiene que traer su `fin`.

    ## El fallo que esto previene
    La parada por verificador devolvía un dict **sin `fin`**, y quien lo consume
    hacía `result["fin"]`: `KeyError`. El run se guardaba como `failed` con el
    error `'fin'`, que no le dice nada a nadie. O sea: la puerta del verificador,
    que es lo que existe para explicarle las cosas al agente, le impedía
    explicarle nada.
    """

    def test_la_puerta_del_verificador_devuelve_fin(self):
        async def gate(step, tool, args, resultado):
            return {"ok": False, "stop": True, "delta": 0, "problemas": 1}

        cliente = _FalsoOllama([{"texto": "", "calls": [
            {"name": "projects_list", "args": {}}]}])
        r = _arrancar_con_cliente(cliente, gate=gate)
        self.assertEqual(r["fin"], "verificador_rojo")
        self.assertTrue(r.get("stopped_by_gate"))

    def test_una_base_roja_para_el_run_en_el_primer_write(self):
        """Antes quemaba los 16 pasos denegando la misma escritura.

        El coste no era solo tiempo: un run que se agota denegando parece que el
        agente no sabe obedecer, cuando lo que ocurre es que nadie le dijo que
        aquello no tenía arreglo.
        """
        import tempfile
        from app import autonomy

        # Un almacén de verdad, en un fichero de verdad: en modo `permiso` y con
        # el proyecto marcado. Un doble que devuelve el veredicto a mano
        # comprobaría el doble, no `decide()`.
        tienda = autonomy._Almacen(Path(tempfile.mkdtemp()) / "a.sqlite3")
        tienda.set_modo("permiso")
        # El alias sale de la **ruta**, no de `estado_base`: una escritura bajo
        # el repo de Aegis pertenece a `aegis`, y por eso hay que marcar ese.
        tienda.marcar("aegis")

        class _AutonomiaReal:
            """Lo justo para que el bucle llame a `decide()` del módulo real."""

            def __init__(self, almacen):
                self.almacen = almacen

            def decide(self, *a, **k):
                return autonomy.decide(*a, almacen_=self.almacen, **k)

        cliente = _FalsoOllama([{"texto": "", "calls": [
            {"name": "aegis_write_file", "args": {"path": "bridge/x.txt", "content": "y"}}]},
            {"texto": "", "calls": [{"name": "aegis_write_file",
                                      "args": {"path": "bridge/x.txt", "content": "z"}}]},
            {"texto": "", "calls": [{"name": "aegis_write_file",
                                      "args": {"path": "bridge/x.txt", "content": "w"}}]}])
        rojo = {"alias": "aegis", "rojo": True, "problemas": 3, "detalle": "3 errores"}
        r = _arrancar_con_cliente(cliente, autonomy=_AutonomiaReal(tienda),
                                  estado_base=rojo, max_steps=3)
        self.assertEqual(r["fin"], "verificador_rojo")
        # Ni llega a preguntar tres veces: para en la primera.
        self.assertEqual(cliente.llamadas, 1)

    def test_una_tool_que_reventa_no_mata_el_run(self):
        """Una tool puede lanzar cualquier cosa, y eso es un paso rojo.

        Antes solo se atrapaban `ToolNotAllowed`, `ValueError` y `TypeError`; un
        `OSError` de una tool se llevaba el run entero **sin traza**, y el modelo
        no tenía ocasión de leer el error ni de intentar otra cosa.
        """
        from unittest import mock
        cliente = _FalsoOllama([
            {"texto": "", "calls": [{"name": "repo_verify", "args": {"what": "check"}}]},
            {"texto": "hecho", "calls": []},
        ])
        with mock.patch("app.autopilot._execute", side_effect=OSError("adb: no such device")):
            r = _arrancar_con_cliente(cliente)
        paso = next((t for t in r["trace"] if t.get("tool")), None)
        self.assertIsNotNone(paso)
        self.assertFalse(paso["ok"])
        self.assertIn("OSError", paso["result"])
        self.assertEqual(r["fin"], "sin_tools",
                         "el run debe poder terminar con su respuesta de verdad")

    def test_sin_modelo_es_un_fin_con_nombre(self):
        import httpx
        cliente = _FalsoOllama([], fallo=httpx.ConnectError("connection refused"))
        r = _arrancar_con_cliente(cliente)
        self.assertEqual(r["fin"], "modelo_caido")
        self.assertIn("ConnectError", r["answer"])
        self.assertTrue(any(t.get("action") == "modelo_caido" for t in r["trace"]))

    def test_sin_modelo_tambien_deja_el_razon_de_lo_que_hizo(self):
        """Ollama no contesta en el paso 2: lo del paso 1 sigue en la traza."""
        import httpx
        from unittest import mock

        class _AVeces:
            def __init__(self):
                self.n = 0

            def __call__(self, *a, **k):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

            async def post(self, url, json=None, **k):
                self.n += 1
                if self.n == 1:
                    return _Respuesta({"texto": "", "calls": [
                        {"name": "projects_list", "args": {}}]})
                raise httpx.ReadTimeout("timeout")

        cliente = _AVeces()
        with mock.patch("app.autopilot.httpx.AsyncClient", return_value=cliente), \
                mock.patch("app.autopilot._execute", return_value="ok"):
            import asyncio
            from app.autopilot import run_autopilot
            r = asyncio.run(run_autopilot("x", ollama_url="http://falso", model="m",
                                          max_steps=4))
        self.assertEqual(r["fin"], "modelo_caido")
        self.assertTrue(any(t.get("tool") == "projects_list" for t in r["trace"]))


class TestTodoRunDejaRastroEnDisco(unittest.TestCase):
    """Un run que falla tiene que poder falla*r otra vez mañana.

    ## Por qué esto importa más que el mensaje
    `_escribir_jsonl_de_autopilot` y `remember()` estaban **después** del run, sin
    ningún `try` alrededor. Cualquier excepción se los comía: el run no existía
    ni en el disco ni en la memoria. Lo que se perdía no era un dato, era el
    aprendizaje —sin episodio, esa forma de fallo no se vuelve a reconocer—.
    """

    def _con_runs_temporales(self):
        import tempfile
        from unittest import mock
        from app import main as main_mod
        tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(main_mod, "_runs_dir", lambda: tmp / "runs")
        patcher.start()
        self.addCleanup(patcher.stop)
        return tmp / "runs"

    def test_un_run_roto_deja_jsonl(self):
        import asyncio
        from unittest import mock
        from app import main as main_mod
        runs = self._con_runs_temporales()
        cuerpo = main_mod.AutopilotIn(prompt="x", max_steps=1)

        async def revienta(*a, **k):
            raise RuntimeError("se rompió el bucle")

        with mock.patch.object(main_mod, "run_autopilot", revienta):
            r = asyncio.run(main_mod._run_autopilot_once(cuerpo, "", None, "run-roto"))

        self.assertEqual(r["fin"], "reventado")
        self.assertIn("RuntimeError", r["error"])
        self.assertTrue((runs / "run-roto.jsonl").exists(),
                        "un run que revienta tiene que dejar fichero")

    def test_el_jsonl_de_un_run_roto_dice_que_revento(self):
        import json
        import asyncio
        from unittest import mock
        from app import main as main_mod
        runs = self._con_runs_temporales()
        cuerpo = main_mod.AutopilotIn(prompt="x", max_steps=1)

        async def revienta(*a, **k):
            raise RuntimeError("se rompió el bucle")

        with mock.patch.object(main_mod, "run_autopilot", revienta):
            asyncio.run(main_mod._run_autopilot_once(cuerpo, "", None, "run-roto"))

        lineas = [json.loads(x) for x in
                  (runs / "run-roto.jsonl").read_text(encoding="utf-8").splitlines()]
        eventos = [x["event"] for x in lineas if "event" in x]
        self.assertIn("task.failed", eventos)
        fallo = next(x for x in lineas if x.get("event") == "task.failed")
        self.assertIn("RuntimeError", fallo["payload"].get("error", ""))


class TestLaEscaladaEstaMontada(unittest.TestCase):
    """La escalada: dejar de insistir, y decir si la base empeoró."""

    """Las dos funciones que la lección daba por puestas, montadas de verdad.

    `verifier.es_repetido` y `autonomy.empeora` llevaban tiempo escritas, con su
    docstring prometiendo lo que hacen, y **sin una sola llamada** en `app/`. La
    lección A-014 llegó a decir «el antidoto ya está: `verifier.es_repetido`
    cuenta la llamada idéntica que falló dos veces». No era verdad, y esa clase de
    mentira —documentar un mecanismo que no existe— es la que hace que luego
    nadie mire si el mecanismo funciona.
    """

    def test_una_escritura_que_se_repite_para_el_run(self):
        # Nota sobre el primer veredicto: para **sí**, porque con el verificador
        # en rojo y sin corrida anterior contra la que comparar, `delta` sale
        # negativo y la puerta para. Es lo prudente y no se cambia aquí; lo que
        # se comprueba aquí es el distinguishing extra de la escalada.

        import asyncio
        from unittest import mock
        from app import verifier

        with mock.patch.object(verifier, "ejecutar") as ejecutar:
            ejecutar.return_value = _verdict_rojo(3)
            puerta = verifier.gate("aegis")
            args = {"path": "bridge/x.txt", "content": "y"}

            # Solo se llama a la puerta: aquí no hay run, y por lo tanto no hay
            # `_execute` que pueda escribir nada en el repo.
            async def _pide(paso):
                return await puerta(paso, "aegis_write_file", args, "escrito")

            v1, v2, v3 = asyncio.run(_pide(1)), asyncio.run(_pide(2)), asyncio.run(_pide(3))

        self.assertFalse(v1.get("repetida"), "la primera no es una repetición")
        self.assertTrue(v3["stop"])
        self.assertTrue(v3.get("repetida"), "y la tercera ya es la misma llamada")
        self.assertIn("ya ha fallado dos veces", v3["motivo"])

    def test_una_escritura_distinta_no_es_repetida(self):
        import asyncio
        from unittest import mock
        from app import verifier

        with mock.patch.object(verifier, "ejecutar") as ejecutar:
            ejecutar.return_value = _verdict_rojo(3)
            puerta = verifier.gate("aegis")

            async def _pide(paso, path):
                return await puerta(paso, "aegis_write_file",
                                    {"path": path, "content": "y"}, "escrito")

            for paso in range(1, 4):
                v = asyncio.run(_pide(paso, f"bridge/{paso}.txt"))
        self.assertFalse(v.get("repetida"), "rutas distintas no son la misma llamada")

    def test_el_resultado_dice_si_la_base_empeoro(self):
        import asyncio
        from unittest import mock
        from app import autopilot as ap

        base = {"alias": "aegis", "problemas": 10, "detalle": "10"}
        # Un gate que dice que ahora hay más problemas de los que había.
        async def gate(step, tool, args, res):
            return {"ok": False, "stop": False, "problemas": 14, "delta": 4,
                    "mismo_error": False}

        cliente = _FalsoOllama([
            {"texto": "", "calls": [{"name": "aegis_write_file",
                                      "args": {"path": "bridge/x.txt",
                                               "content": "y"}}]},
            {"texto": "listo", "calls": []},
        ])
        # `_execute` falseado siempre. Sin esto el test **escribe en el repo de
        # verdad**: no se pasa `autonomy`, así que nada impide la escritura y la
        # tool real se ejecuta. Pasó, y dejó un `bridge/x.txt` en el árbol.
        # Un test que toca el disco real no es un test: es una escritura sin
        # querer (A-057, la misma clase de fallo cometida al revés).
        with mock.patch("app.autopilot._execute", return_value="escrito"):
            r = _arrancar_con_cliente(cliente, gate=gate, estado_base=base)
        self.assertTrue(r["empeorada"])
        self.assertIn("10 problema", r["answer"])
        self.assertIn("14", r["answer"])

    def test_si_no_empeora_no_dice_nada(self):
        """Decir «empeoró» sin que empeore es ruido que entrena a ignorar avisos."""
        from app.autopilot import _con_empeora
        r = _con_empeora({"answer": "hecho", "trace": []},
                         {"alias": "aegis", "problemas": 10}, [])
        self.assertNotIn("empeorada", r)
        trace = [{"gate": {"problemas": 9}}]
        r2 = _con_empeora({"answer": "hecho", "trace": trace},
                          {"alias": "aegis", "problemas": 10}, trace)
        self.assertFalse(r2["empeorada"])
        self.assertEqual(r2["answer"], "hecho")


class TestElIdDeRunNoSeRepite(unittest.TestCase):
    """Dos `POST /autopilot` seguidos no pueden compartir `run_id`.

    ## Por qué importa más de lo que parece
    El JSONL del run se abre en `"w"` (`_escribir_jsonl_de_autopilot`), o sea que
    escribir es **truncar**. Con `f"autopilot-{int(time.time())}"`, dos missions
    lanzadas en el mismo segundo producían el mismo identificador y la segunda
    borraba el historial de la primera. No había error: un run simplemente
    desaparecía del registro, y el principio que este repo dice defender es que la
    caída a disco no puede ser una promesa.

    La ruta asíncrona ya usaba uuid desde antes. Este test mira las dos, porque
    eran dos formatos conviviendo y el peor de los dos estaba en la ruta síncrona.

    ## Cómo se comprueba sin lanzar trabajo de verdad
    Se sustituye `_run_autopilot_once` por un capturador: lo que se quiere ver es
    **qué id se le pasa**, y el resto del run no importa. Se fija el reloj para que
    los dos id caiGAN en el mismo segundo, porque si no la prueba pasaría también
    con un timestamp y no mediría nada.
    """

    def test_dos_missions_no_comparten_id_aunque_caigan_en_el_mismo_segundo(self):
        from fastapi.testclient import TestClient
        from app import main as main_mod

        vistos = []

        async def _captura(body, ctx, puerta, run_id, token=None):
            vistos.append(run_id)
            return {"model": "qwen2.5:7b", "answer": "ok", "steps": 1,
                    "trace": [], "fin": "sin_tools"}

        # La cabecera va porque `AEGIS_API_KEY` está puesta y `/autopilot` la pide.
        # Un 401 aquí no sería un fallo del id: sería la puerta funcionando.
        cabeceras = {}
        if main_mod.settings.aegis_api_key:
            cabeceras["X-Aegis-Token"] = main_mod.settings.aegis_api_key

        with mock.patch.object(main_mod, "_run_autopilot_once", _captura), \
             mock.patch.object(main_mod.time, "time", lambda: 1_700_000_000.0):
            c = TestClient(main_mod.app)
            cuerpo = {"prompt": "di hola", "max_steps": 1}
            for _ in range(2):
                r = c.post("/autopilot", json=cuerpo, headers=cabeceras)
                self.assertEqual(200, r.status_code, r.text)

        self.assertEqual(2, len(vistos), "las dos llamadas tendrían que haber pasado")
        self.assertNotEqual(
            vistos[0], vistos[1],
            f"los dos runs comparten id ({vistos[0]}): el segundo trunca el JSONL "
            "del primero y desaparece del historial")
        for run_id in vistos:
            self.assertTrue(run_id.startswith("autopilot-"), run_id)


def _respuesta_con_tool_call() -> dict:
    """Una respuesta de Ollama con una tool call, tal cual la devuelve el API."""
    return {"choices": [{"message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "x", "type": "function", "function": {
            "name": "aegis_read_file",
            "arguments": '{"path": "bridge/metodo.md"}'}}],
    }}]}


class TestElBucleNoSeBloquea(unittest.TestCase):
    """Una tool lenta no puede congelar el bridge entero.

    ## El fallo que esto mide
    `_execute` se llamaba **en el event loop**, y varias tools lanzan procesos:
    `repo_verify` es `subprocess.run(timeout=900)`, y `tsc --noEmit` o `vitest run`
    tardan minutos. Con la tool en el loop, durante una verificación no contestaba
    nada: ni `/health`, ni `/actividad`, ni el poll de 3 s del móvil, ni el
    WebSocket, ni el propio `POST /autopilot/{id}/stop`.

    El repo ya lo había notado y lo había arreglado dos veces en el sitio
    equivocado —en `main.py`, en las dos rutas que lanzan hilo para deploy y
    aprobaciones—, que no son las que se usan el 95 % del tiempo.

    ## Por qué este test es determinista y no una carrera
    La tool falsa **no duerme**: se queda esperando un `threading.Event`. El test
    programa en el loop un coroutine que suelta ese evento dentro de un segundo.
    Con la tool en el executor, el loop puede ejecutar ese coroutine y la tool
    termina. Con la tool en el loop, el loop está ocupado esperando el evento que
    solo él puede soltar: el `wait_for` se agota y el test falla con un mensaje que
    dice exactamente qué pasó. No hay ventana de tiempo ni probabilidad.

    La consecuencia que se comprueba de paso: `POST /autopilot/{id}/stop` ya puede
    llegar mientras la verificación corre.
    """

    def test_una_tool_lenta_no_impide_que_el_loop_avance(self):
        import asyncio
        import threading
        from unittest import mock
        from app import autopilot as ap

        listo = threading.Event()
        igualmente = {"llego": False, "la_tool_entro": False}

        def _tool_bloqueante(*_args, **_kwargs):
            igualmente["la_tool_entro"] = True
            listo.wait(timeout=10)
            return "listo"

        async def _escena():
            async def _suelta_el_evento():
                await asyncio.sleep(0.2)
                igualmente["llego"] = True
                listo.set()

            async def _no_hace_nada(step, name, args, result):
                return None

            respuesta = _respuesta_con_tool_call()

            class _ClienteFalso:
                """Contesta siempre lo mismo, sin hablar con Ollama.

                Depender del modelo real en este test sería meter dos fuentes de
                variabilidad: su ánimo para emitir `tool_calls` (que ya se midió
                que depende del prompt) y sus 10-60 s de latencia. Lo que se
                comprueba aquí es el bloqueo del loop, y eso lo decide un
                `threading.Event`.
                """
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

                async def post(self, url, json=None, **kw):
                    class _R:
                        def raise_for_status(self_inner):
                            return None

                        def json(self_inner):
                            return respuesta
                    return _R()

            with mock.patch.object(ap, "_execute", _tool_bloqueante), \
                 mock.patch.object(ap.httpx, "AsyncClient", lambda **kw: _ClienteFalso()):
                tarea = asyncio.create_task(ap.run_autopilot(
                    "usa la tool para probar", ollama_url="http://inutil",
                    model="qwen2.5:7b", on_step=None, gate=_no_hace_nada))
                soltador = asyncio.create_task(_suelta_el_evento())
                try:
                    # Lo que se mide es que el loop atienda al soltador. **No** se
                    # espera a que termine el run: eso hace una llamada real al
                    # modelo y tardaría sus 10-60 s, y su fallo no diría nada del
                    # bloqueo. El run se cancela después.
                    await asyncio.wait_for(asyncio.shield(soltador), timeout=3)
                finally:
                    listo.set()          # por si acaso, para no dejar hilos colgados
                    for t in (tarea, soltador):
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(tarea, soltador, return_exceptions=True)

        asyncio.run(_escena())
        self.assertTrue(igualmente["llego"],
                        "el loop nunca llegó a ejecutar el coroutine: la tool lo "
                        "tenía bloqueado")
        # Que la tool llegara a ejecutarse de verdad: si el modelo no devolvió
        # ninguna llamada, este test pasaría sin comprobar nada. Se registra dentro
        # de la propia tool porque «esperando» solo es cierto **antes** de que el
        # soltador le suelte el evento.
        self.assertTrue(igualmente.get("la_tool_entro"),
                        "la tool nunca llegó a ejecutarse: el modelo no devolvió "
                        "una llamada y el test no comprobó nada")
