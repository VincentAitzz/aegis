"""El verificador y la puerta por paso.

Lo que se fija aquí no es la salida de un comando concreto, sino las decisiones
que hacen que un run no se queme: comparar dos corridas, reconocer el mismo
error dos veces, y negarse a dejar avanzar a quien no progresa.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.verifier import (  # noqa: E402
    Verdict,
    contar_problemas,
    delta,
    es_repetido,
    ejecutar,
    firmas_de,
    gate,
)


def v(ok=True, resumen="", firmas=(), exit_code=0, what="check"):
    return Verdict(ok=ok, what=what, proyecto="aegis", exit_code=exit_code,
                   resumen=resumen, firmas=tuple(firmas))


class TestContarProblemas(unittest.TestCase):
    def test_cuenta_solo_lineas_con_problema(self):
        texto = "todo bien\nERROR: algo\n  \nFailed to compile\nfin"
        self.assertEqual(contar_problemas(texto), 2)

    def test_texto_vacio_es_cero(self):
        self.assertEqual(contar_problemas(""), 0)

    def test_nunca_none(self):
        self.assertEqual(contar_problemas("nada que ver aquí"), 0)


class TestFirmas(unittest.TestCase):
    def test_el_mismo_error_con_ruido_distinto_da_la_misma_firma(self):
        """Es lo que permite decir "es el mismo error, no progresó"."""
        a = firmas_de("/home/uitz/x.py:42: error: undefined name 'field'")
        b = firmas_de("/home/otro/y.py:98: error: undefined name 'field'")
        self.assertEqual(a, b)

    def test_errores_distintos_dan_firmas_distintas(self):
        a = firmas_de("error: undefined name 'field'")
        b = firmas_de("error: unexpected keyword argument 'what'")
        self.assertNotEqual(a, b)

    def test_sin_errores_no_hay_firmas(self):
        self.assertEqual(firmas_de("15/15 módulos importan"), ())

    def test_no_hay_firmas_repetidas(self):
        texto = "error: x\nerror: x\nerror: x"
        self.assertEqual(len(firmas_de(texto)), 1)


class TestDelta(unittest.TestCase):
    def test_sin_antes_no_hay_mejora_que_presumir(self):
        d = delta(None, v(ok=True))
        self.assertEqual(d["antes"], 0)
        self.assertFalse(d["mismo_error"])

    def test_menos_problemas_es_mejora(self):
        antes = v(ok=False, resumen="ERROR: a\nERROR: b")
        despues = v(ok=True, resumen="ERROR: a")
        d = delta(antes, despues)
        self.assertEqual(d["delta"], 1)
        self.assertTrue(d["mejoro"])

    def test_mismo_error_entre_corridas(self):
        firm = ("error: ?",)
        d = delta(v(ok=False, firmas=firm), v(ok=False, firmas=firm))
        self.assertTrue(d["mismo_error"])
        self.assertFalse(d["mejoro"])

    def test_firmas_vacias_no_son_el_mismo_error(self):
        d = delta(v(ok=False), v(ok=False))
        self.assertFalse(d["mismo_error"])

    def test_sigue_rojo_aunque_baje_no_es_mejora(self):
        antes = v(ok=False, resumen="ERROR: a\nERROR: b")
        despues = v(ok=False, resumen="ERROR: a")
        d = delta(antes, despues)
        self.assertFalse(d["mejoro"], "bajar problemas sin llegar a verde no es mejorar")

    def test_tiene_las_claves_exactas(self):
        for clave in ("ok", "problemas", "antes", "delta", "mismo_error", "mejoro"):
            self.assertIn(clave, delta(None, v()))


class TestEsRepetido(unittest.TestCase):
    def test_dos_fallos_identicos_es_repetido(self):
        h = [{"tool": "t", "arguments": {"a": 1}, "ok": False}] * 2
        self.assertTrue(es_repetido(h, "t", {"a": 1}))

    def test_un_solo_fallo_no_alcanza(self):
        h = [{"tool": "t", "arguments": {"a": 1}, "ok": False}]
        self.assertFalse(es_repetido(h, "t", {"a": 1}))

    def test_el_orden_de_las_claves_no_cuenta(self):
        h = [{"tool": "t", "arguments": {"a": 1, "b": 2}, "ok": False}] * 2
        self.assertTrue(es_repetido(h, "t", {"b": 2, "a": 1}))

    def test_otro_argumento_no_es_repetido(self):
        h = [{"tool": "t", "arguments": {"a": 1}, "ok": False}] * 2
        self.assertFalse(es_repetido(h, "t", {"a": 2}))

    def test_exito_previo_no_es_repetido(self):
        h = [{"tool": "t", "arguments": {"a": 1}, "ok": True}] * 2
        self.assertFalse(es_repetido(h, "t", {"a": 1}))

    def test_historial_vacio(self):
        self.assertFalse(es_repetido([], "t", {}))


class TestEjecutar(unittest.TestCase):
    def test_proyecto_desconocido_no_lanza(self):
        r = ejecutar("nada", "check")
        self.assertFalse(r.ok)
        self.assertIn("proyecto desconocido", r.error)

    def test_verificador_desconocido_no_lanza(self):
        r = ejecutar("aegis", "flake8")
        self.assertFalse(r.ok)
        self.assertIn("verificador desconocido", r.error)

    def test_proyecto_sin_ese_verificador_no_lanza(self):
        r = ejecutar("trazeurs", "build")
        self.assertIn("no declara verificador", r.error)

    def test_binario_local_ausente_no_lanza(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("app.verifier.PROJECTS", {
                "x": mock.Mock(root=Path(tmp), verify={"check": ["./no/existe"]})
            }):
                r = ejecutar("x", "check")
        self.assertFalse(r.ok)
        self.assertIn("falta", r.error)

    def test_raiz_inexistente_no_lanza(self):
        from pathlib import Path
        with mock.patch.dict("app.verifier.PROJECTS", {
            "x": mock.Mock(root=Path("/tmp/raiz-que-no-existe-12345"),
                           verify={"check": ["true"]})
        }):
            r = ejecutar("x", "check")
        self.assertFalse(r.ok)
        self.assertIn("raíz no existe", r.error)

    def test_timeout_no_lanza(self):
        with mock.patch("app.verifier.subprocess.run",
                        side_effect=__import__("subprocess").TimeoutExpired("x", 1)):
            r = ejecutar("aegis", "check", timeout=1)
        self.assertFalse(r.ok)
        self.assertIn("agotó", r.error)

    def test_salida_real_del_proyecto(self):
        r = ejecutar("aegis", "check")
        self.assertTrue(r.ok, r.error or r.resumen[:200])
        self.assertEqual(r.exit_code, 0)
        self.assertGreaterEqual(r.ms, 0)

    def test_veredicto_es_serializable(self):
        import json
        json.dumps(ejecutar("aegis", "check").to_dict())


class TestGate(unittest.TestCase):
    """La puerta: no verifica lecturas, y detiene a quien no progresa."""

    def test_no_verifica_lecturas(self):
        puerta = gate("aegis", "check")
        self.assertIsNone(asyncio_run(puerta(1, "aegis_read_file", {}, "x")))

    def test_verifica_una_escritura(self):
        puerta = gate("aegis", "check")
        v = asyncio_run(puerta(1, "aegis_write_file", {"path": "x"}, "escrito"))
        self.assertIsNotNone(v)
        self.assertIn("verificador", v)
        self.assertIn("ok", v)

    def test_para_cuando_no_mejora(self):
        puerta = gate("aegis", "check")
        primero = asyncio_run(puerta(1, "aegis_write_file", {}, ""))
        segundo = asyncio_run(puerta(2, "aegis_write_file", {}, ""))
        if not primero.get("ok"):
            self.assertTrue(segundo.get("stop"),
                            "siendo rojo dos veces sin mejora, tiene que parar")
            self.assertIn("motivo", segundo)


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main(verbosity=2)
