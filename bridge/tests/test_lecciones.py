"""Las lecciones en el prompt: índice y texto, no las 120 KB.

## El fallo que esto previene
`lessons/aegis.md` se inyectaba entero. Medido el 2026-10-04: mismo encargo,
n=5, 60,2 s por llamada con el fichero entero frente a 10,5 s sin él —5,7×— y el
mismo número de tool_calls. Y el comportamiento que describen tampoco cambiaba:
la lección A-014 dice «no repitas la llamada idéntica que ya falló dos veces» y el
modelo la repitió 3 de 3 **con** las lecciones y 3 de 3 **sin** ellas.

El coste era real y el beneficio, medido, cero. Lo que se conserva es el
registro: el fichero entero sigue ahí, y ahora se pide con una tool.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import lecciones as mod  # noqa: E402


class _LeccionesTemporales(unittest.TestCase):
    """Un `lessons/` de mentira, para no medir contra el fichero de verdad."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()) / "lessons"
        self.tmp.mkdir(parents=True)
        p = mock.patch.object(mod, "LESSONS_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        mod.cargar.cache_clear()

    def escribir(self, alias: str, texto: str) -> None:
        (self.tmp / f"{alias}.md").write_text(texto, encoding="utf-8")
        mod.cargar.cache_clear()


DOS = """
### A-001 · El modelo dijo que había hecho tres cosas

> Aplica cuando: cuando vas a decir que has hecho N cosas

- **Qué pasó**: respondió «listo» sin haber escrito nada.
- **Regla**: el recuento del agente no es evidencia.

### A-002 · Una tool que deniega devuelve texto

> Aplica cuando: cuando pintas un resultado de una tool sin leerlo

- **Qué pasó**: `ok: true` con un resultado que decía RECHAZADO.
- **Regla**: mira el motivo.
"""


class TestParseo(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(mod.cargar.cache_clear)

    def test_una_leccion_tiene_numero_titulo_y_cuerpo(self):
        with mock.patch.object(mod, "LESSONS_DIR",
                               Path(__file__).parent.parent / "lessons"):
            libros = mod.cargar("aegis")
        self.assertGreater(len(libros), 50, "las lecciones de aegis deben estar")
        l = libros[0]
        self.assertTrue(l.numero.startswith("A-"))
        self.assertTrue(l.titulo)
        self.assertTrue(l.cuerpo or l._cuerpo)

    def test_un_alias_invalido_no_lee_nada(self):
        """Un alias se convierte en ruta: no puede salir de `lessons/`."""
        self.assertEqual(mod.cargar("../metodo"), ())
        self.assertEqual(mod.cargar("/etc/passwd"), ())
        self.assertEqual(mod.cargar(""), ())

    def test_proyecto_sin_lecciones_no_es_error(self):
        with mock.patch.object(mod, "LESSONS_DIR",
                               Path(__file__).parent.parent / "lessons"):
            self.assertEqual(mod.cargar("no-existe"), ())
            self.assertEqual(mod.indice("no-existe"), "")


class TestIndice(_LeccionesTemporales):
    def test_una_linea_por_leccion_con_cuando_aplica(self):
        self.escribir("x", DOS)
        idx = mod.indice("x")
        self.assertIn("- A-001 · El modelo dijo", idx)
        self.assertIn("cuando vas a decir que has hecho N cosas", idx)
        self.assertEqual(len(idx.splitlines()), 2)

    def test_sin_disparador_usa_la_frase_del_que_paso(self):
        """No inventar el criterio: se extrae de lo que el propio cuerpo dice."""
        self.escribir("x", """
### A-003 · Sin criterio propio

- **Qué pasó**: el agente repitió siete veces la misma escritura fallida.
- **Regla**: cambia de estrategia.
""")
        idx = mod.indice("x")
        self.assertIn("repitió siete veces la misma escritura fallida", idx)
        self.assertNotIn("sin criterio", idx)

    def test_una_leccion_sin_cue_dice_que_no_lo_tiene(self):
        self.escribir("x", """
### A-004 · Título solo

- **Regla**: algo.
""")
        self.assertIn("sin criterio declarado", mod.indice("x"))

    def test_el_tope_recorta_y_lo_dice(self):
        muchas = "\n".join(
            f"### A-{i:03d} · Lección número {i} con un título bastante largo\n\n"
            f"- **Qué pasó**: un incidente {i} que ocupa esta línea y sigue.\n"
            for i in range(1, 40))
        self.escribir("x", muchas)
        idx = mod.indice("x", presupuesto=800)
        self.assertLessEqual(len(idx), 1000)
        self.assertIn("no caben", idx)

    def test_la_frase_se_corta_sin_fingir_que_acaba(self):
        self.escribir("x", """
### A-005 · Título

- **Qué pasado**: " + ("una frase larguísima que se sigue y sigue " * 8)
        """)
        linea = mod.indice("x").splitlines()[0]
        self.assertLess(len(linea), 220)
        self.assertNotIn("...", linea)


class TestRelevancia(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(mod.cargar.cache_clear)
        self.tmp = Path(tempfile.mkdtemp()) / "lessons"
        self.tmp.mkdir(parents=True)
        p = mock.patch.object(mod, "LESSONS_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        (self.tmp / "x.md").write_text(DOS, encoding="utf-8")
        mod.cargar.cache_clear()

    def test_elige_por_palabras_compartidas(self):
        """Es parecido burdo a propósito: un modelo de 6 GB no merece más."""
        halladas = mod.relevantes("x", "voy a decir que he creado tres enums", k=1)
        self.assertEqual([h.numero for h in halladas], ["A-001"])

    def test_sin_palabras_comunes_no_inventa(self):
        self.assertEqual(mod.relevantes("x", "xyzzy plugh", k=1), [])

    def test_el_tema_pide_varias(self):
        halladas = mod.por_tema("x", "tool que deniega y recuento", limite=5)
        self.assertGreaterEqual(len(halladas), 1)


class TestCuerpo(_LeccionesTemporales):
    def test_devuelve_el_texto_entero_de_lo_pedido(self):
        self.escribir("x", DOS)
        texto = mod.cuerpo("x", ["A-002"])
        self.assertIn("### A-002", texto)
        self.assertIn("ok: true", texto)
        self.assertNotIn("A-001 ·", texto)

    def test_acepta_el_numero_sin_la_letra(self):
        self.escribir("x", DOS)
        self.assertIn("### A-001", mod.cuerpo("x", ["1"]))

    def test_una_leccion_inexistente_no_inventa_texto(self):
        self.escribir("x", DOS)
        fuera = mod.cuerpo("x", ["A-999"])
        self.assertIn("No hay ninguna lección", fuera)
        self.assertIn("A-001", fuera, "y dice cuáles hay")

    def test_sin_numeros_explica_lo_que_hace_falta(self):
        self.escribir("x", DOS)
        self.assertIn("números", mod.cuerpo("x", []))


class TestElPromptYaNoSeCompeLasLecciones(unittest.TestCase):
    def test_el_prompt_del_proyecto_aegis_cabe_en_una_fraccion(self):
        """La puerta del bloque: si esto falla, el arreglo no sirve."""
        from app.autopilot import build_system_prompt
        completo = build_system_prompt(
            "", "aegis", "",
            encargo="repite la llamada que ya falló dos veces")
        sin = build_system_prompt("", "otro-sin-lecciones", "")
        # Antes eran 125 489 chars. El presupuesto acordado es 8 000 para el
        # índice; el resto del prompt son unos 8 000. Se exige que no lo reviente.
        self.assertLess(len(completo), 30_000,
                        f"el prompt sigue siendo enorme: {len(completo)}")
        self.assertGreater(len(completo), len(sin))
        self.assertIn("LECCIONES DE ESTE PROYECTO (índice", completo)
        self.assertIn("A-001", completo)

    def test_la_leccion_mas_relevante_va_entera(self):
        """«voy a decir que he creado tres enums» tiene que traer el recuento.

        Y si no lo trae, el índice es decorativo: es justo el caso que el índice
        promete cubrir.
        """
        from app.autopilot import build_system_prompt
        p = build_system_prompt("", "aegis", "",
                                encargo="voy a decir que he creado tres enums")
        self.assertIn("La que más aplica a este encargo", p)
        self.assertIn("### A-002", p)
        self.assertNotIn("### A-001", p.split("La que más aplica")[1])
