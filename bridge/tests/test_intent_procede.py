"""«Procede» — el 19 % de los prompts que no llegaban a ningún sitio.

## El número que justifica el fichero

Medido el 2026-10-14 sobre **500 prompts reales** del usuario (4 semanas, 6
proyectos; se descartaron 45 que son el prompt del propio arnés):

| patrón | % |
|---|---|
| continuar — `procede`, `continua`, `dale` | **19 %** |

Y antes de este intent, en la máquina:

    'procede'   -> (no casa con ningún intent)
    'continua'  -> (no casa con ningún intent)

Caían a T1 —el modelo sin herramientas—, y el modelo no tenía con qué continuar
porque no existía el objeto «lo que Aegis está trabajando». Eso ya existe
(`app/plan.py`) y estos tests son el otro extremo: que la frase llegue.

## La mitad que trae requisitos

De 88 «procede / continua / dale» reales, **44 llevan algo detrás**: «Procede,
los sin numero tambien incluyelos para manejarlos manualmente pero haz la
separacion de los otros».

Eso no es un procede, es un cambio de requisitos, y tratarlo como un procede
seco sería ejecutar un plan que el usuario acaba de cambiar.
"""

import tempfile
import unittest
from pathlib import Path

import unicodedata

from app.intents import _calcula_procede, aplicar, preparar, resolver


def _sin_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if not unicodedata.combining(c))
from app.plan import Planes


class TestElGestoSolo(unittest.TestCase):
    """«Procede» a secas, y sus variantes reales."""

    def test_las_formas_medidas(self):
        for frase in ("procede", "continua", "dale", "listo", "hecho",
                      "sigue", "adelante", "siguiente", "procede por favor",
                      "continua ya", "dale porfavor"):
            with self.subTest(frase=frase):
                r = resolver(frase)
                self.assertIsNotNone(r, f"«{frase}» no casó con nada")
                self.assertEqual(r.nombre, "procede")

    def test_sin_tildes_y_con_tildes_casan_igual(self):
        """El 94 % de los prompts reales van sin tildes."""
        for frase in ("continua", "continúa", "que hora es", "qué hora es"):
            with self.subTest(frase=frase):
                self.assertIsNotNone(resolver(frase))

    def test_no_toca_lo_que_ya_funcionaba(self):
        for frase, esperado in (("que hora es", "que_hora_es"),
                                ("que dia es", "que_dia_es"),
                                ("lista los proyectos", "lista_proyectos"),
                                ("que puedes hacer", "que_puedes_hacer")):
            with self.subTest(frase=frase):
                r = resolver(frase)
                self.assertIsNotNone(r)
                self.assertEqual(r.nombre, esperado)

    def test_el_gesto_no_es_un_cambio(self):
        for frase in ("procede", "continua", "listo", "procede porfavor"):
            with self.subTest(frase=frase):
                self.assertFalse(_calcula_procede(frase)["cambia"])


class TestElRequisitoPegado(unittest.TestCase):
    """La mitad de las reales. Y la que decide si Aegis hace la gilipollas."""

    def test_detecta_el_requisito(self):
        for frase, esperado in (
            ("procede, inclúyelos pero sepáralos", "incluyelos pero separalos"),
            ("sigue con el móvil", "con el movil"),
            ("continua, y deja las notas en el movil", "y deja las notas en el movil"),
        ):
            with self.subTest(frase=frase):
                a = _calcula_procede(frase)
                self.assertTrue(a["cambia"])
                self.assertEqual(a["resto"], esperado)

    def test_el_relleno_no_cuenta_como_requisito(self):
        """«procede porfavor» es un gesto, no un requisito llamado «porfavor»."""
        a = _calcula_procede("procede porfavor ahora por favor")
        self.assertFalse(a["cambia"])
        self.assertEqual(a["resto"], "")

    def test_no_se_traga_una_pregunta(self):
        """Una pregunta no es un «procede» con requisitos."""
        for frase in ("lista los proyectos", "qué puedes hacer",
                      "qué hora es"):
            with self.subTest(frase=frase):
                r = resolver(frase)
                # O no casa con nada, o casa con **otro** intent. Lo que no
                # puede pasar es que case con «procede» y se coma la frase.
                if r is not None:
                    self.assertNotEqual(r.nombre, "procede")


class TestLoQueHace(unittest.TestCase):
    """Y lo que hace cuando casa. Con almacén de verdad, en una tmp."""

    def setUp(self):
        import app.plan as plan
        self._orig = plan._INSTANCIA
        self.ps = Planes(Path(tempfile.mkdtemp()) / "planes.sqlite3")
        plan._INSTANCIA = self.ps

    def tearDown(self):
        import app.plan as plan
        plan._INSTANCIA = self._orig

    def texto(self, frase):
        p = preparar(frase)
        self.assertIsNotNone(p, f"«{frase}» no llegó a calcular")
        return aplicar(p)

    def test_sin_plan_dice_que_no_hay_nada_que_continuar(self):
        """No inventar que se continúa es parte del contrato."""
        self.assertIn("no hay nada que continuar", self.texto("procede").lower())

    def test_con_plan_en_curso_lo_dice(self):
        p = self.ps.crear("dejar que la app arranque sola", prioridad=90)
        self.ps.tomar(p["id"])
        self.assertIn("dejar que la app arranque sola", self.texto("procede"))

    def test_con_plan_en_la_cola_lo_dice_en_la_cola(self):
        """La diferencia entre «sigue» y «lo tienes en cola»."""
        self.ps.crear("otra cosa", prioridad=80)
        self.assertIn("en la cola", self.texto("procede"))

    def test_el_requisito_reformula_el_plan_en_curso(self):
        """Lo que se pidió: encajar el requisito sobre lo que ya se hacía."""
        p = self.ps.crear("dejar que la app arranque sola", prioridad=90)
        self.ps.tomar(p["id"])
        salida = self.texto("procede, y deja también las notas en el móvil")
        self.assertIn("reformulado", salida.lower())
        actual = self.ps.en_curso()
        self.assertIsNotNone(actual, "el plan dejó de estar en curso: eso es "
                                     "una interrupción disfrazada")
        self.assertEqual(actual["id"], p["id"])
        self.assertIn("ademas:", _sin_acentos(actual["objetivo"]).lower())

    def test_reformular_no_interrumpe(self):
        """El bug real: `reformulado` sacaba de `en_curso` y paraba el plan."""
        p = self.ps.crear("lo de antes")
        self.ps.tomar(p["id"])
        self.texto("procede, y además X")
        self.assertIsNotNone(self.ps.en_curso())

    def test_la_reformulacion_deja_motivo(self):
        """Sin motivo, «reformuló» no se distingue de «cambió de opinión»."""
        p = self.ps.crear("lo de antes")
        self.ps.tomar(p["id"])
        self.texto("procede, y además X")
        self.assertTrue(self.ps.en_curso()["reformula_motivo"].strip())

    def test_sin_plan_en_curso_el_requisito_se_encola(self):
        """«procede, quiero X» con nada corriendo: X entra en la cola."""
        self.texto("procede, quiero que el móvil avise de los fallos")
        self.assertIsNotNone(self.ps.siguiente())
        self.assertIn("movil", _sin_acentos(self.ps.siguiente()["objetivo"]).lower())


class TestLaPuertaSigueEstando(unittest.TestCase):
    """`procede` es un intent de lectura, y eso no puede cambiar solo."""

    def test_no_escribe_por_si_mismo(self):
        r = resolver("procede")
        self.assertIsNotNone(r)
        self.assertFalse(r.escribe)


if __name__ == "__main__":
    unittest.main()