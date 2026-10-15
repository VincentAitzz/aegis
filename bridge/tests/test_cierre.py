"""El cierre de un run: cinco apartados, y solo lo que importa.

## Lo que fija estos tests

**1. Que sale de la traza, no del modelo.** Es la tercera vez que se aplica la
misma idea (A-016 para el veredicto, `evidencia.py` para las afirmaciones), y
aquí es donde más importa: el cierre es **lo único que vas a leer cuando Aegis
trabaje en tu ausencia**. Si lo escribiera el modelo, sería el sitio donde un
modelo puede decir cualquier cosa sin que nadie se entere.

**2. Que las recomendaciones no las escribe el modelo.** Es el único apartado
donde eso podría pasar: los otros cuatro describen hechos comprobables, este
describe una opinión. Y hay una asimetría —una opinión generada suena igual de
profesional que un dato—, así que este apartado sale de reglas que están a la
vista.

**3. Que el silencio es una respuesta.** Un run donde no pasó nada **no produce
informe**. Un cierre con cinco títulos y tres líneas dice «no pasó nada» en 200
caracteres, y por eso no se lee.
"""

import unittest

from app.cierre import Cierre, cierre_de


def traza(*tools):
    return [{"tool": n, "ok": ok} for n, ok in tools]


class TestResultadosYErrores(unittest.TestCase):
    def test_lo_que_va_en_verde_y_lo_que_no(self):
        c = cierre_de("hecho", traza(("repo_verify", True),
                                     ("aegis_write_file", False)),
                      fin="sin_tools")
        self.assertEqual(c.resultados, ["repo_verify: en verde"])
        self.assertEqual(c.errores, ["aegis_write_file: en rojo"])

    def test_una_rotura_del_run_es_un_error(self):
        for fin in ("modelo_caido", "reventado"):
            with self.subTest(fin=fin):
                c = cierre_de("", traza(("repo_verify", True)), fin=fin)
                self.assertTrue(any(fin in e for e in c.errores))

    def test_agotar_los_pasos_es_un_error(self):
        """No es un fallo de Aegis, es trabajo a medias. Se dice como tal."""
        c = cierre_de("creo que ya está", traza(("repo_verify", True)),
                      fin="max_steps")
        self.assertTrue(any("agotó los pasos" in e for e in c.errores))

    def test_no_inventa_errores_en_un_run_limpio(self):
        c = cierre_de("listo", traza(("repo_verify", True)), fin="sin_tools")
        self.assertEqual(c.errores, [])


class TestCambiosDrasticos(unittest.TestCase):
    def test_una_reformulacion_es_un_cambio_drastico(self):
        """Abandonar trabajo es lo único que puede hacer daño sin tocar nada
        irreversible. Por eso va en su propio apartado y no en «resultados»."""
        c = cierre_de("hecho", traza(("repo_verify", True)), fin="sin_tools",
                      reformulaciones=[{"antes": "arreglar el verificador",
                                         "despues": "dejar la app arrancando",
                                         "motivo": "prioridad 90"}])
        self.assertEqual(len(c.cambios_drasticos), 1)
        self.assertIn("prioridad 90", c.cambios_drasticos[0])

    def test_cambiar_de_enfoque_es_un_cambio_drastico(self):
        c = cierre_de("hecho",
                      [{"tool": "usar_enfoque",
                        "arguments": {"nombre": "arquitectura"}, "ok": True}],
                      fin="sin_tools")
        self.assertTrue(any("arquitectura" in c for c in c.cambios_drasticos))

    def test_sin_reformulacion_no_hay_que_inventar(self):
        c = cierre_de("hecho", traza(("repo_verify", True)), fin="sin_tools")
        self.assertEqual(c.cambios_drasticos, [])


class TestDecisiones(unittest.TestCase):
    def test_una_afirmacion_sin_respaldo_es_una_decision(self):
        """El caso medido: Aegis dice «está en verde» sin haber ejecutado nada."""
        c = cierre_de("he arreglado app/main.py y el verificador está en verde",
                      traza(("repo_verify", True)), fin="sin_tools")
        self.assertTrue(any("SIN RESPALDO" in d for d in c.decisiones))

    def test_una_afirmacion_respaldada_no_es_una_decision(self):
        # Con la traza **entera**, argumentos incluidos. El helper `traza()` de
        # arriba solo conserva `tool` y `ok`, y entonces `app/main.py` no
        # aparece en ninguna parte — que es exactamente el caso que se quiere
        # probar al revés.
        c = cierre_de("he revisado app/main.py y está en verde",
                      [{"tool": "aegis_read_file",
                        "arguments": {"ruta": "app/main.py"}, "ok": True},
                       {"tool": "repo_verify", "ok": True}],
                      fin="sin_tools")
        self.assertFalse(any("SIN RESPALDO" in d for d in c.decisiones))

    def test_el_helper_de_prueba_no_tira_los_argumentos(self):
        """Documenta el límite del helper, que ya dio un falso positivo arriba."""
        self.assertEqual(traza(("repo_verify", True))[0],
                         {"tool": "repo_verify", "ok": True})
        self.assertNotIn("arguments", traza(("repo_verify", True))[0])

    def test_las_cambios_drasticos_tambien_son_decisiones(self):
        """Lo que Aegis cambió de rumbo es una decisión, por definición."""
        c = cierre_de("hecho", traza(("repo_verify", True)), fin="sin_tools",
                      reformulaciones=[{"antes": "a", "despues": "b",
                                         "motivo": "m"}])
        self.assertEqual(len(c.decisiones), len(c.cambios_drasticos))


class TestRecomendacionesSonReglas(unittest.TestCase):
    def test_no_las_escribe_el_modelo(self):
        """El `answer` no aparece en ninguna recomendación.

        Es la comprobación de que este apartado sale de reglas: si el texto del
        modelo apareciera aquí, se podría «recomendar» cualquier cosa con
        aspecto de consejo.
        """
        answer = ("Deberías migrar la base a Postgres, cambiar el CI a "
                  "Kubernetes y contratar a alguien para que revise esto.")
        c = cierre_de(answer, traja := traza(("repo_verify", True)),
                      fin="sin_tools")
        todo = " ".join(c.recomendaciones)
        for trozo in ("Postgres", "Kubernetes", "contratar"):
            self.assertNotIn(trozo, todo)

    def test_solo_hay_cinco_reglas_y_una_para_un_run_limpio(self):
        """Una recomendación que siempre sale es ruido."""
        c = cierre_de("listo", traza(("repo_verify", True)), fin="sin_tools")
        self.assertEqual(c.recomendaciones, [])

    def test_error_recomienda_mirar_los_errores(self):
        c = cierre_de("x", traza(("aegis_write_file", False)), fin="sin_tools")
        self.assertTrue(any("en rojo" in r or "rojo" in r
                            for r in c.recomendaciones))

    def test_max_steps_recomienda_relanzar(self):
        c = cierre_de("x", traza(("repo_verify", True)), fin="max_steps")
        self.assertTrue(any("relanz" in r or "partirlo" in r
                            for r in c.recomendaciones))

    def test_nunca_mas_de_tres_recomendaciones(self):
        """El tope es lo que las mantiene accionables."""
        c = cierre_de("x",
                      traza(("a", False), ("b", False), ("c", False),
                            ("d", True), ("e", True)),
                      fin="max_steps")
        self.assertLessEqual(len(c.recomendaciones), 3)


class TestElSilencioEsUnaRespuesta(unittest.TestCase):
    """Un run donde no pasó nada no produce informe."""

    def test_un_run_limpio_dice_que_no_pasa_nada(self):
        c = cierre_de("listo", traza(("repo_verify", True),
                                     ("aegis_read_file", True)), fin="sin_tools")
        self.assertTrue(c.vacio)
        self.assertFalse(c.vital)
        self.assertIn("Sin nada que contar", c.como_texto())

    def test_el_texto_no_imprime_apartados_vacios(self):
        """Cinco títulos vacíos dicen «nada» en 200 caracteres."""
        c = cierre_de("listo", traza(("repo_verify", True), ("aegis_write_file", False)),
                      fin="sin_tools")
        texto = c.como_texto()
        self.assertIn("RESULTADOS", texto)
        self.assertIn("ERRORES", texto)
        self.assertNotIn("DECISIONES", texto)
        self.assertLess(len(texto), 300)

    def test_un_run_con_un_error_no_esta_vacio(self):
        c = cierre_de("x", traza(("aegis_write_file", False)), fin="sin_tools")
        self.assertFalse(c.vacio)
        self.assertTrue(c.vital)


class TestSePuedeAuditar(unittest.TestCase):
    """La invariante: siempre se puede saber qué hizo y por qué.

    Un informe que no enseña sus fuentes pide que le crean. Este las enseña, y
    por eso `sostiene` va en la respuesta y no solo por detrás.
    """

    def test_cada_apartado_dice_de_donde_sale(self):
        c = cierre_de("x", traza(("repo_verify", True), ("aegis_write_file", False)),
                      fin="max_steps")
        for apartado in ("resultados", "errores", "decisiones", "recomendaciones"):
            with self.subTest(apartado=apartado):
                self.assertIn(apartado, c.sostiene)

    def test_los_datos_son_comprobables(self):
        """Los `sostiene` nombran la tool, no dicen «algo pasó»."""
        c = cierre_de("x", traza(("repo_verify", True)), fin="sin_tools")
        self.assertIn("tool ok: repo_verify", c.sostiene["resultados"])

    def test_el_cierre_sobrevive_a_ser_un_dict(self):
        c = cierre_de("x", traza(("repo_verify", True)), fin="sin_tools")
        d = c.a_dict()
        self.assertEqual(set(d),
                         {"resultados", "cambios_drasticos", "errores",
                          "decisiones", "recomendaciones", "sostiene",
                          "vital", "vacio"})


class TestDesdeLaTrazaSola(unittest.TestCase):
    """El cierre tiene que poder construirse sin nada del run vivo.

    Es lo que permite reetiquetar el histórico entero con la misma regla, que es
    como un número medido puede volver a mirar un mes después.
    """

    def test_funciona_con_los_tres_formatos_de_traza(self):
        for entrada in (
            {"tool": "repo_verify", "ok": True},
            {"payload": {"tool": "repo_verify", "ok": True}},
            {"payload": {"data": {"tool": "repo_verify", "error": "x"}}},
        ):
            with self.subTest(entrada=entrada):
                c = cierre_de("hecho", [entrada], fin="sin_tools")
                self.assertTrue(c.resultados or c.errores)

    def test_un_run_sin_ninguna_tool_si_se_informa(self):
        """Aquí el criterio es el contrario, y a propósito.

        Un run de autopilot sin una sola tool **no es una conversación**: se le
        pidió trabajar y no se tocó nada. No se puede distinguir de una
        respuesta normal desde la traza, y por eso se informa en vez de asumir
        que estaba bien. Callarse aquí sería el peor sitio para suppressir un
        informe, porque es justo el fallo que no se ve.
        """
        c = cierre_de("creo que ya esta", [], fin="sin_tools")
        self.assertEqual(c.resultados, [])
        self.assertFalse(c.vacio)
        self.assertTrue(any("ninguna herramienta" in r
                            for r in c.recomendaciones))

    def test_el_cierre_vacio_no_esta_vacio(self):
        c = Cierre()
        self.assertTrue(c.vacio)
        self.assertFalse(c.vital)


if __name__ == "__main__":
    unittest.main()