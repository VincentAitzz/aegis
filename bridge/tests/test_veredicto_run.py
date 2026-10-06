"""El veredicto: qué pasó en un run, dicho con un dato.

Existe porque `fin` no distinguía "terminé" de "me rendí". Medido sobre los 133
runs del histórico: **45,1 % completado**, y 38 de los 59 `sin_tools` eran
ejecuciones reales que el `fin` enterraba como fracasos. Estos tests fijan esa
regla para que no vuelva a derivar sin avisar.

## Lo que un test de esto tiene que mirar
No que `clasificar` devuelva una palabra, sino que **no haya dos reglas
distintas** entre el run en vivo y el fichero de hace una semana. Por eso
`test_las_dos_puertas_dicen_lo_mismo` es el más importante del fichero: es el
que impide que la línea base se mida con un criterio y el código nuevo se juzgue
con otro.
"""
import json
import unittest

from app.veredicto import clasificar, desde_jsonl, resumir


def _paso(tool, ok=True, paso=1):
    return {"step": paso, "tool": tool, "ok": ok}


class TestUnRunConToolYRespuestaEstaCompletado(unittest.TestCase):
    """El caso que el `fin` viejo clasificaba mal."""

    def test_tool_mas_texto_es_completado(self):
        v = clasificar("sin_tools", [_paso("registry_list")], "hay 8 proyectos")
        self.assertEqual(v["estado"], "completado")
        self.assertTrue(v["completado"])

    def test_sin_respuesta_no_esta_completado_aunque_haya_tool(self):
        """La tool fue verde pero el modelo se quedó mudo: no terminó."""
        v = clasificar("sin_tools", [_paso("registry_list")], "")
        self.assertEqual(v["estado"], "incompleto")
        self.assertFalse(v["completado"])

    def test_respuesta_sin_ninguna_tool_no_esta_completado(self):
        """Escribir un texto no es haber hecho nada. Un `final` sin tool es
        un texto (A-016)."""
        v =clasificar("sin_tools", [], "creo que ya está")
        self.assertEqual(v["estado"], "incompleto")

    def test_max_steps_con_tool_y_respuesta_tambien_completa(self):
        """`max_steps` no es fracasó por definición: si alcanzó a responder
        antes de agotar los pasos, terminó lo que tenía que hacer."""
        v = clasificar("max_steps", [_paso("repo_verify")], "listo, todo verde")
        self.assertEqual(v["estado"], "completado")


class TestEsperarNoEsFallar(unittest.TestCase):
    """Un run esperando a una persona no es un run roto. Es otro estado."""

    def test_esperando_ok_no_cuenta_como_completado(self):
        v = clasificar("esperando_ok", [_paso("db_query")], "necesito tu OK")
        self.assertEqual(v["estado"], "esperando_ok")
        self.assertFalse(v["completado"])

    def test_parado_tampoco(self):
        self.assertEqual(clasificar("parado", [_paso("repo_verify")], "")["estado"],
                         "parado")


class TestLosQueNoSonDelRun(unittest.TestCase):
    def test_modelo_caido_es_roto(self):
        self.assertEqual(clasificar("modelo_caido", [], "")["estado"], "roto")

    def test_verificador_rojo_es_rechazado(self):
        """Lo frenó la puerta: no es que no supiera, es que no debía seguir."""
        self.assertEqual(clasificar("verificador_rojo", [_paso("aegis_write_file")], "")["estado"],
                         "rechazado")

    def test_un_fin_desconocido_no_se_da_por_bueno(self):
        """El fallo silencioso del otro extremo: un `fin` nuevo se clasifica
        como `roto` para que alguien lo mire. Darlo por completado seria
        repetir el `task.max_steps` como evento, que fue un bug real (A-091)."""
        self.assertEqual(clasificar("fin_nuevo_del_futuro", [], "x")["estado"], "roto")

    def test_sin_fin_es_incompleto(self):
        self.assertEqual(clasificar("", [], "")["estado"], "incompleto")


class TestLasToolsRojas(unittest.TestCase):
    def test_una_tool_roja_no_impide_completar(self):
        """Leyó mal un archivo y luego contestó bien: el run terminó. La tool
        roja va en su campo, no en el veredicto."""
        v = clasificar("sin_tools", [_paso("aegis_read_file", ok=False),
                                     _paso("registry_list")], "hecho")
        self.assertEqual(v["estado"], "completado")
        self.assertEqual(v["tools_fallidas"], ["aegis_read_file"])

    def test_solo_tools_rojas_no_completan(self):
        v = clasificar("sin_tools", [_paso("aegis_read_file", ok=False)], "hecho")
        self.assertEqual(v["estado"], "incompleto")


class TestLasDosPuertasDicenLoMismo(unittest.TestCase):
    """El test que sostiene la línea base.

    `clasificar` (run en vivo) y `desde_jsonl` (histórico) tienen que aplicar
    **la misma** regla. Si divergen, comparar «antes» y «después» es comparar
    dos cosas distintas y el número miente sin que nadie lo note.
    """

    def _jsonl(self, fin, tools, answer="respuesta"):
        lineas = [json.dumps({"run_id": "r", "event": "task.created",
                              "payload": {"project": "aegis"}})]
        for i, t in enumerate(tools, 1):
            lineas.append(json.dumps({"run_id": "r", "event": "tool.completed",
                                      "payload": {"tool": t, "ok": True, "step": i}}))
        lineas.append(json.dumps({"run_id": "r", "event": "task.done",
                                  "payload": {"fin": fin, "answer": answer,
                                              "error": "", "steps": len(tools)}}))
        return lineas

    def test_mismo_veredicto_por_las_dos_puertas(self):
        for fin, tools, answer in (
            ("sin_tools", ["registry_list"], "8 proyectos"),
            ("sin_tools", [], "creo que ya"),
            ("max_steps", ["repo_verify"], "listo"),
            ("esperando_ok", ["db_query"], "esperando"),
            ("modelo_caido", [], "se Cayó"),
        ):
            memoria = clasificar(fin, [_paso(t) for t in tools], answer)
            disco = desde_jsonl(self._jsonl(fin, tools, answer))
            self.assertEqual(memoria["estado"], disco["estado"],
                             f"{fin}: memoria dice {memoria['estado']}, "
                             f"disco dice {disco['estado']}")

    def test_el_formato_de_hermes_tambien_se_lee(self):
        """Los 84 `run_*.jsonl` del histórico traen la tool en
        `payload.data`, no en `payload`. Sin esa rama quedaban fuera de la
        cuenta y el denominador mentía."""
        lineas = [
            json.dumps({"run_id": "run_x", "event": "tool.completed",
                        "payload": {"data": {"tool": "projects_list", "error": ""}}}),
            json.dumps({"run_id": "run_x", "event": "task.done",
                        "payload": {"fin": "sin_tools", "answer": "mira"}}),
        ]
        self.assertEqual(desde_jsonl(lineas)["estado"], "completado")

    def test_un_fichero_sin_terminal_es_reventado(self):
        """El run se cortó a mitad. No es un cierre limpio y no puede
        contarse como nada bueno."""
        lineas = [json.dumps({"run_id": "x", "event": "task.created", "payload": {}})]
        v = desde_jsonl(lineas)
        self.assertEqual(v["estado"], "roto")
        self.assertEqual(v["fin"], "reventado")

    def test_una_linea_rota_no_tira_el_fichero(self):
        """Un JSONL truncado es lo normal cuando el bridge se apaga en
        mitad de la escritura. Perder el run entero por una linea es perder
        el dato justo cuando más falta hace."""
        lineas = self._jsonl("sin_tools", ["registry_list"], "hecho")
        lineas.insert(2, "{esto no es json")
        self.assertEqual(desde_jsonl(lineas)["estado"], "completado")


class TestElResumenSirve(unittest.TestCase):
    """Un veredicto sin resumen obliga a mirar la traza entera."""

    def test_el_resumen_dice_que_paso(self):
        v = clasificar("sin_tools", [_paso("registry_list"), _paso("lecciones")],
                       "x" * 100)
        self.assertIn("2", v["resumen"])
        self.assertTrue(v["resumen"])

    def test_resumen_en_historico(self):
        lineas = [json.dumps({"run_id": "r", "event": "task.done",
                              "payload": {"fin": "sin_tools", "answer": "hola",
                                          "error": ""}})]
        self.assertTrue(desde_jsonl(lineas)["resumen"])


class TestElResumenGlobal(unittest.TestCase):
    def test_desglose_por_estado_y_por_fin(self):
        """Sin el desglose por `fin`, `incompleto` no dice qué arreglar."""
        runs = [
            ("r1", [json.dumps({"event": "tool.completed",
                                "payload": {"tool": "a", "ok": True}}),
                    json.dumps({"event": "task.done",
                                "payload": {"fin": "sin_tools", "answer": "x"}})]),
            ("r2", [json.dumps({"event": "task.done",
                                "payload": {"fin": "max_steps", "answer": ""}})]),
            ("r3", [json.dumps({"event": "task.done",
                                "payload": {"fin": "esperando_ok", "answer": ""}})]),
        ]
        r = resumir(runs)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["estados"]["completado"], 1)
        self.assertEqual(r["estados"]["incompleto"], 1)
        self.assertEqual(r["estados"]["esperando_ok"], 1)
        self.assertEqual(r["fins"]["max_steps"], 1)
        self.assertAlmostEqual(r["pct_completado"], 33.3, places=1)

    def test_vacio_no_divide_por_cero(self):
        r = resumir([])
        self.assertEqual(r["pct_completado"], 0.0)


class TestLaDuracionSeMideDeVerdad(unittest.TestCase):
    """`run_duration_s` valia 0.0 hardcodeado, con la forma del metric ya lista.

    No era un dato que faltara: era un dato **falso** con forma de dato. Un
    informe de duraciones sobre estos ficheros decia "todos los runs duraron 0
    segundos", que es un numero, y por eso no chirriaba. `docs/motores.md` §1.3 lo
    senala como lo que bloquea cualquier presupuesto de latencia, y tenia razon.
    """

    def test_el_jsonl_lleva_la_duracion_del_run(self) -> None:
        import json as _json
        import os
        import tempfile

        from app import main as main_mod
        tmp = tempfile.mkdtemp()
        original = main_mod._runs_dir
        main_mod._runs_dir = lambda: __import__("pathlib").Path(tmp)
        try:
            main_mod._escribir_jsonl_de_autopilot("r_dur", "aegis", {
                "model": "m", "steps": 1, "fin": "sin_tools",
                "estado": "completado", "completado": True,
                "duracion_s": 12.5, "answer": "hecho", "trace": [],
            })
            lineas = [l for l in open(os.path.join(tmp, "r_dur.jsonl"),
                                       encoding="utf-8") if l.strip()]
            metricas = [_json.loads(l) for l in lineas
                        if _json.loads(l).get("metric") == "run_duration_s"]
        finally:
            main_mod._runs_dir = original
        self.assertEqual(1, len(metricas), "no se escribio la metrica de duracion")
        self.assertEqual(12.5, metricas[0]["s"])

    def test_el_veredicto_lleva_duracion(self) -> None:
        """El dato viene en el mismo paquete que el veredicto, no suelto.

        Son la misma pregunta sobre el run —que dio lo que pedia y a que
        precio— y separarlos es lo que hace que uno se mida y el otro no."""
        import asyncio
        from unittest import mock

        from app.autopilot import run_autopilot

        class _Fake:
            def post(self, *a, **k):
                raise RuntimeError("sin red")

        with mock.patch("app.autopilot.httpx.AsyncClient") as cliente:
            cliente.return_value.__aenter__.return_value = _Fake()
            r = asyncio.run(run_autopilot("x", ollama_url="http://falso", model="m",
                                          max_steps=1))
        self.assertIn("duracion_s", r)
        self.assertGreaterEqual(r["duracion_s"], 0.0)


if __name__ == "__main__":
    unittest.main()