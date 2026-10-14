"""Las afirmaciones del modelo, comprobadas contra la traza.

El motivo de que este fichero exista está medido en el módulo, pero dos cosas
no se pueden ver leyendo el código y sí se pueden ver aquí:

1. **Que la regla no tiene falsos positivos.** Es la razón por la que la
   afirmación de verificador está restringida a líneas cortas: aplicada entera,
   daba 3 falsos positivos sobre 220 runs y 0 detecciones.
2. **Que la respuesta no se usa como prueba de sí misma.** Ese bug estuvo: la
   respuesta entraba en «lo que el modelo ha visto», y entonces cualquier ruta
   inventada quedaba respaldada por aparecer en la propia respuesta.
"""

import unittest

from app import evidencia, veredicto


TRAZA_OK = [
    {"tool": "aegis_read_file", "args": {"ruta": "app/main.py"}, "ok": True},
    {"tool": "repo_verify", "args": {"what": "test"}, "ok": True},
    {"prompt": "revisa app/main.py y dime si esta verde"},
]


class TestRutas(unittest.TestCase):
    def test_encuentra_rutas_con_barra(self):
        self.assertIn("app/main.py", evidencia.rutas("mira app/main.py"))

    def test_no_confunde_un_numero_con_un_fichero(self):
        self.assertEqual(evidencia.rutas("hace 1.5 segundos"), set())
        self.assertEqual(evidencia.rutas("version v2.0"), set())

    def test_no_confunde_un_identificador_suelto(self):
        self.assertEqual(evidencia.rutas("A-001 y B-002"), set())

    def test_acepta_una_ruta_larga(self):
        self.assertIn("bridge/app/capacidades.py",
                      evidencia.rutas("esta en bridge/app/capacidades.py"))


class TestLaRespuestaNoSePruebaASiMisma(unittest.TestCase):
    """El bug que hacia que esto no comprobara nada."""

    def test_una_ruta_inventada_no_se_respalda_sola(self):
        # La respuesta dice que miró un fichero que no aparece en el encargo
        # ni en ninguna tool. Si la respuesta contase como "visto", esto
        # pasaría por respaldado.
        r = evidencia.sin_respaldo(
            "He revisado app/puerta_http.py.",
            [{"prompt": "revisa app/main.py"},
             {"tool": "aegis_read_file", "args": {"ruta": "app/main.py"}}])
        self.assertEqual([a.valor for a in r], ["app/puerta_http.py"])

    def test_una_ruta_del_encargo_si_se_respalda(self):
        r = evidencia.sin_respaldo(
            "He revisado app/main.py.",
            [{"prompt": "revisa app/main.py"}])
        self.assertEqual(r, [])

    def test_abreviar_el_nombre_no_es_alucinar(self):
        # El modelo leyó bridge/app/main.py y responde de main.py.
        r = evidencia.sin_respaldo("esta claro en main.py",
                                   [{"tool": "aegis_read_file",
                                     "args": {"ruta": "bridge/app/main.py"}}])
        self.assertEqual(r, [])


class TestSoloProsa(unittest.TestCase):
    """Lo que Aegis afirma, no lo que cita o estructura."""

    def test_un_encabezado_no_afirma(self):
        self.assertEqual(evidencia.solo_prosa("## En verde"), "")

    def test_una_cita_no_afirma(self):
        self.assertEqual(evidencia.solo_prosa("> el verificador esta en verde"), "")

    def test_una_lista_no_afirma(self):
        self.assertEqual(evidencia.solo_prosa("- repo_verify: en verde"), "")

    def test_un_bloque_de_codigo_no_afirma(self):
        texto = "```\nverificador: en verde\n```"
        self.assertEqual(evidencia.solo_prosa(texto), "")

    def test_la_prosa_se_queda(self):
        self.assertIn("Esta en verde",
                      evidencia.solo_prosa("# Titulo\nEsta en verde."))


class TestVerde(unittest.TestCase):
    def test_una_afirmacion_suelta_cuenta(self):
        self.assertTrue(evidencia.afirma_verde("El verificador esta en verde."))
        self.assertTrue(evidencia.afirma_verde("Ya esta todo en verde."))
        self.assertTrue(evidencia.afirma_verde("0 issues."))

    def test_la_conversacion_normal_no_cuenta(self):
        for texto in ("Hola. ¿Que andas?", "A ver si me explico."):
            with self.subTest(texto=texto):
                self.assertFalse(evidencia.afirma_verde(texto))

    def test_la_leccion_citada_no_cuenta(self):
        """El caso medido: A-001 dice que una verificación en verde NO es
        una entrega completa. La regla leía lo contrario de lo que dice."""
        self.assertFalse(evidencia.afirma_verde(
            "### A-001 · Una verificacion en verde NO es una entrega completa"))

    def test_el_falso_positivo_que_queda_y_esta_a_saber(self):
        """El residuo, escrito para que no se puncha sin querer.

        Sobre los 220 runs del histórico queda **1 falso positivo** (0,5 %): la
        respuesta reproducía el índice de las lecciones del repo y la regla leyó
        «en verde» como una afirmación suya. No lo era —la frase citada dice
        justo lo contrario— pero venía dentro de una enumeración y dentro de las
        dos primeras frases.

        Se probaron dos criterios más para quitarlo y **se paró ahí**: los dos
       hajían de elegir un número, y ajustar un número hasta que un artefacto
        concreto deja de colarse es sobreajustar. Un solo run del histórico, con
        una salida del modelo que era un texto mal formado, no justifica una
        cuarta heurística que no generaliza.

        El coste se asume y se escribe: 1 de 220. A cambio, el camino que de
        verdad importa —la conversación, en vivo— tiene **cero** falsos
        positivos en las pruebas.
        """
        indice = (
            "El modelo agoto los pasos; traza real de lo ejecutado: Dime el "
            "tema de lo que vas a hacer, o los numeros. El indice es: - A-001 "
            "· Una verificacion en verde NO es una entrega completa · se "
            "pidieron cinco entregables; el agente escribio uno, el resto no.")
        # today falls (documented cost); the guard that fixes it is structural
        self.assertTrue(evidencia.afirma_verde(indice))

    def test_una_frase_larga_sigue_siendo_una_afirmacion(self):
        """El corte es por **posición**, no por tamaño.

        La primera versión limitaba la longitud de la línea a 100 caracteres y
        fallaba en los dos sentidos: se saltaba esto —que son 102 caracteres y
        es una afirmación de las dos que importan— y solo agarraba el índice de
        lecciones por medir 330.
        """
        self.assertTrue(evidencia.afirma_verde(
            "No necesito tools para confirmar eso. El verificador esta en "
            "verde. ¿Necesitas que verifique algo mas?"))

    def test_se_reconoce_en_los_tres_formatos(self):
        for entrada in (
            {"tool": "repo_verify", "ok": True},
            {"payload": {"tool": "repo_verify", "ok": True}},
            {"payload": {"data": {"tool": "repo_verify", "error": None}}},
        ):
            with self.subTest(entrada=entrada):
                self.assertTrue(evidencia.corrrio_verificador([entrada]))

    def test_una_tool_que_no_verifica_no_cuenta(self):
        self.assertFalse(evidencia.corrrio_verificador(
            [{"tool": "aegis_read_file", "ok": True}]))


class TestResumen(unittest.TestCase):
    def test_todo_respaldado(self):
        r = evidencia.resumen("He revisado app/main.py, esta en verde.", TRAZA_OK)
        self.assertTrue(r["respaldada"])
        self.assertEqual(r["sin_respaldo"], 0)
        self.assertEqual(r["afirmaciones"], 2)

    def test_nada_respaldado(self):
        r = evidencia.resumen(
            "He revisado app/puerta_http.py y esta en verde.",
            [{"prompt": "revisa app/main.py"}])
        self.assertFalse(r["respaldada"])
        self.assertEqual(r["sin_respaldo"], 2)

    def test_el_detalle_explica_cada_caida(self):
        r = evidencia.resumen("esta en verde", [{"prompt": "hola"}])
        self.assertTrue(any("verificador" in d for d in r["detalle"]))


class TestVeredictoConEvidencia(unittest.TestCase):
    """El estado nuevo, y la regla de que solo puede bajar."""

    def test_verde_y_afirmacion_sin_respaldo_es_sin_evidencia(self):
        v = veredicto.clasificar(
            "sin_tools",
            [{"tool": "aegis_read_file", "args": {"ruta": "app/main.py"},
              "ok": True}],
            "He revisado app/main.py y esta en verde.")
        self.assertEqual(v["estado"], "sin_evidencia")
        self.assertFalse(v["completado"])
        self.assertIn("sin respaldo", v["resumen"])

    def test_verde_y_afirmacion_respaldada_es_completado(self):
        v = veredicto.clasificar("sin_tools", TRAZA_OK,
                                 "He revisado app/main.py, esta en verde.")
        self.assertEqual(v["estado"], "completado")

    def test_sin_afirmaciones_no_cambia_nada(self):
        v = veredicto.clasificar(
            "sin_tools", [{"tool": "lista_tareas", "ok": True}],
            "Tienes 3 tareas para hoy.")
        self.assertEqual(v["estado"], "completado")

    def test_la_evidencia_no_puede_resucitar_un_run_roto(self):
        """Solo baja el estado. Un run roto no se arregla con evidencia."""
        v = veredicto.clasificar("modelo_caido", [], "esta en verde")
        self.assertEqual(v["estado"], "roto")

    def test_el_campo_evidencia_siempre_viene(self):
        v = veredicto.clasificar("sin_tools", [{"tool": "x", "ok": True}], "hola")
        self.assertIn("evidencia", v)
        self.assertTrue(v["evidencia"]["respaldada"])


class TestSobreElHistorico(unittest.TestCase):
    """Lo que la comprobación hace y no hace, sobre datos de verdad.

    No es un test que pueda fallar en CI —lee `data/logs/runs/`, que no viaja—,
    sino la forma de dejar la medición a la vista. Si algún día los runs se
    borran, esto dice lo que se sabía, no lo que queda.
    """

    def test_lo_que_se_odio(self):
        import glob
        import json
        import os

        if not glob.glob("data/logs/runs/autopilot-*.jsonl"):
            self.skipTest("sin historial en este clon")
        con_ruta = con_verde = ninguno = 0
        for f in glob.glob("data/logs/runs/autopilot-*.jsonl"):
            lineas = open(f, encoding="utf-8").read().splitlines()
            v = veredicto.desde_jsonl(lineas)
            if v["estado"] not in ("completado", "sin_evidencia"):
                continue
            ans = ""
            for l in lineas:
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                p = e.get("payload") or {}
                if e.get("event") in ("task.done", "task.failed"):
                    ans = p.get("answer") or ""
            r = bool(evidencia.rutas(evidencia.solo_prosa(ans)))
            g = evidencia.afirma_verde(ans)
            con_ruta += r
            con_verde += g
            ninguno += not (r or g)
        total = con_ruta + con_verde + ninguno
        # La cobertura es baja, y ese es el dato: la mayoría de las respuestas
        # que "completaron" no afirman nada comprobable, así que no hay nada
        # que comprobar. El fallo que esta regla previene no está en los runs
        # de agente —donde el modelo llama al verificador cuando lo necesita—,
        # sino en la conversación, donde no hay verificador.
        self.assertGreater(total, 0)
        print(f"\n  cobertura de la comprobación: "
              f"{con_ruta + con_verde}/{total} respuestas "
              f"({(con_ruta + con_verde) * 100 // max(total, 1)} %) "
              f"afirman algo comprobable")


if __name__ == "__main__":
    unittest.main()