"""`quien-eres.md`: lo que Aegis sabe de ti, y lo que no entra en cada run.

## Las tres reglas que este fichero protege

**1. Lo siempre-activo es pequeño, y con tope.** La sección «Cómo hablo contigo»
va en el prompt de todos los runs. El resto del fichero no va nunca. Si el
resumen no tuviera tope, escribir en el perfil sería la forma más fácil de
engordar el prompt del sistema sin que nadie lo decidiera — y el prompt se
re-evalúa en cada paso (A-080), así que eso se multiplica.

**2. Recortar avisa.** Un bloque de instrucciones cortado a la mitad es peor que
uno corto: la instrucción que se pierde es la que no se cumple, y no hay forma de
saber cuál era. Por eso el recorte lleva su propio marcador visible.

**3. Escribir es nivel 3.** El fichero entra en el prompt de todo el sistema, así
que reescribirlo cambia el comportamiento entero de golpe. Preguntar no es
prudencia abstracta: es que la diferencia entre editar tu perfil y que lo edite
un tercero sin que lo sepas es la diferencia entre una decisión y un ataque.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import quien


class TestElResumen(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.real = quien.QUIEN_PATH
        quien.QUIEN_PATH = self.tmp / "quien-eres.md"
        quien.limpiar_cache()
        self.addCleanup(self.restaurar)

    def restaurar(self):
        quien.QUIEN_PATH = self.real
        quien.limpiar_cache()

    def escribir(self, texto: str) -> None:
        quien.QUIEN_PATH.write_text(texto, encoding="utf-8")

    def test_sin_fichero_no_revienta(self):
        """Un fichero ausente no puede tumbar un run."""
        self.assertEqual("", quien.contexto())
        self.assertEqual("", quien.resumen())
        self.assertEqual("", quien.por_tema(""))

    def test_solo_entra_la_seccion_marcada(self):
        """El resto del fichero no se inyecta, aunque el fichero sea enorme."""
        self.escribir("---\nkind: perfil\n---\n\n"
                      + f"## {quien.RESUMEN}\n\nHablas español.\n"
                      + "\n## Biografía\n\n" + ("x" * 20_000))
        ctx = quien.contexto()
        self.assertIn("Hablas español.", ctx)
        self.assertNotIn("Biografía", ctx)
        self.assertNotIn("xxxx", ctx)

    def test_el_tope_recorta_y_avisa(self):
        """Encima del tope: se recorta, y el recorte se dice."""
        largo = "\n\n".join(f"- punto número {i}" for i in range(200))
        self.escribir(f"## {quien.RESUMEN}\n\n{largo}")
        resumen = quien.resumen()
        self.assertLessEqual(len(resumen.split("[…truncado")[0].strip()),
                             quien.MAX_RESUMEN)
        self.assertIn("[…truncado", resumen)
        self.assertIn(quien.QUIEN_PATH.name, resumen)
        self.assertIn("aegis_read_file", resumen)

    def test_el_tope_no_deja_media_linea(self):
        """Recortar por un salto de línea, no por un carácter: media instrucción
        es peor que ninguna, porque parece que se cumple."""
        self.escribir(f"## {quien.RESUMEN}\n\n" + "\n".join(["a" * 70] * 12))
        primera = quien.resumen().splitlines()[0]
        self.assertLessEqual(len(primera), 70)

    def test_los_comentarios_no_llegan_al_prompt(self):
        """Quien rellena esto deja preguntas en un `<!-- -->`.

        Una pregunta sin responder no puede acabar en el prompt de un modelo como
        si fuera una instrucción, y además son 300 caracteres de presupuesto.
        """
        self.escribir(f"## {quien.RESUMEN}\n\nHablas español.\n"
                      "<!-- ¿qué hora te viene bien? -->")
        self.assertNotIn("qué hora", quien.contexto())
        self.assertLess(len(quien.contexto()), 200)

    def test_el_frontmatter_no_es_una_seccion(self):
        self.escribir("---\nkind: perfil\n---\n\n## Otra\n\ncuerpo\n")
        self.assertNotIn("kind", " ".join(quien.secciones()))


class TestPorTema(unittest.TestCase):
    def setUp(self):
        self.real = quien.QUIEN_PATH
        quien.QUIEN_PATH = Path(tempfile.mkdtemp()) / "quien-eres.md"
        quien.limpiar_cache()
        quien.QUIEN_PATH.write_text(
            f"## {quien.RESUMEN}\n\nResumen.\n\n"
            "## Clientes\n\nPII: no va aquí.\n\n"
            "## Emulador\n\nLa app se prueba en el emulador, no en el teléfono.\n",
            encoding="utf-8")
        self.addCleanup(self.restaurar)

    def restaurar(self):
        shutil.rmtree(quien.QUIEN_PATH.parent, ignore_errors=True)
        quien.QUIEN_PATH = self.real
        quien.limpiar_cache()

    def test_sin_tema_devuelve_el_fichero(self):
        self.assertIn("Emulador", quien.por_tema(""))

    def test_con_tema_devuelve_la_seccion_que_encaja(self):
        self.assertIn("emulador", quien.por_tema("pruebo en el emulador o en el móvil").lower())

    def test_no_repite_el_resumen(self):
        """El resumen ya va siempre: repetirlo bajo demanda es pagar dos veces."""
        self.assertNotIn("Resumen.", quien.por_tema(""))

    def test_un_tema_que_no_encaja_no_inventa(self):
        """Preferible «nada» a un perfil inventado que encaje a la fuerza."""
        self.assertEqual("", quien.por_tema("zxqwv"))


class TestActualizar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.real = quien.QUIEN_PATH
        quien.QUIEN_PATH = self.tmp / "quien-eres.md"
        quien.QUIEN_PATH.write_text(
            "---\nkind: perfil\n---\n\n"
            f"## {quien.RESUMEN}\n\nHablas español.\n\n"
            "## Emulador\n\nViejo.\n",
            encoding="utf-8")
        quien.limpiar_cache()
        self.addCleanup(self.restaurar)

    def restaurar(self):
        quien.QUIEN_PATH = self.real
        quien.limpiar_cache()

    def test_reemplaza_solo_la_seccion_pedida(self):
        quien.actualizar("Emulador", "El teléfono solo con la puerta entera.")
        self.assertEqual("El teléfono solo con la puerta entera.",
                         quien.secciones()["Emulador"])
        self.assertEqual("Hablas español.", quien.secciones()[quien.RESUMEN])

    def test_anade_una_seccion_nueva(self):
        quien.actualizar("Clientes", "Los datos viven en Postgres.")
        self.assertIn("Clientes", quien.secciones())
        self.assertIn("Emulador", quien.secciones())

    def test_no_toca_el_fichero_si_el_texto_tiene_encabezados(self):
        """Un `## ` en el texto partiría la sección en dos, y el prompt recibiría
        medio bloque. Mejor un error y el fichero intacto."""
        antes = quien.QUIEN_PATH.read_text(encoding="utf-8")
        r = quien.actualizar("Emulador", "Viejo.\n\n## Colada")
        self.assertIn("no puede contener encabezados", r)
        self.assertEqual(antes, quien.QUIEN_PATH.read_text(encoding="utf-8"))

    def test_dos_ediciones_no_dejan_duplicados(self):
        """Se reescribe el fichero entero desde las secciones, así que la segunda
        edición no repite lo de la primera."""
        quien.actualizar("Emulador", "Uno.")
        quien.actualizar("Emulador", "Dos.")
        texto = quien.QUIEN_PATH.read_text(encoding="utf-8")
        self.assertEqual(1, texto.count("## Emulador"))
        self.assertNotIn("Uno.", texto)
        self.assertIn("Dos.", texto)

    def test_conserva_los_comentarios_del_que_lo_rellena(self):
        """Son notas para la persona; el parseo se los come, pero el fichero es
        suyo y no debe perderlos por una edición vía tool."""
        quien.QUIEN_PATH.write_text(
            f"## {quien.RESUMEN}\n\nHablas español.\n"
            "<!-- PENDIENTE: el huso horario -->\n\n"
            "## Emulador\n\nViejo.\n", encoding="utf-8")
        quien.limpiar_cache()
        quien.actualizar("Emulador", "Nuevo.")
        self.assertIn("PENDIENTE", quien.QUIEN_PATH.read_text(encoding="utf-8"))

    def test_devuelve_lo_que_vale_a_partir_de_ahora_en_el_prompt(self):
        """No basta con decir que se escribió: hay que decir lo que cuesta, porque
        esta sección se paga en cada paso de cada run."""
        quien.actualizar("Emulador", "z" * 50)
        self.assertIn("chars de este fichero", quien.actualizar("Otro", "texto"))
        self.assertIn(str(len(quien.resumen())), quien.actualizar("Otro2", "texto"))


class TestNivelDeAutonomia(unittest.TestCase):
    """Escribir el perfil es de nivel 3, y leerlo es libre.

    No es una preferencia: el fichero entra en el prompt de todos los runs, así que
    reescribirlo cambia el sistema entero de golpe. `lecciones` está en `LIBRES`
    por el mismo motivo — leer no cambia nada.
    """

    def test_leer_el_perfil_es_una_tool_que_ya_existia(self):
        """No hay tool de lectura propia, y es deliberado.

        Leer el perfil se hace con `aegis_read_file`, que ya está en el schema y
        es de nivel libre. Añadir `quien_eres` habría sido duplicar una capacidad
        existente a cambio de ~1 500 caracteres de schema **en cada paso de cada
        run**, y el schema se paga aunque la tool no llegue a usarse (A-081: 8,7 KB
        de menos fueron un 37 % de latencia).

        El riesgo de esta decisión es el obvio: el modelo no sabe que ese fichero
        existe salvo que el bloque inyectado se lo diga. Por eso el bloque lo dice
        en una línea, y eso sí es barato.
        """
        from app.autopilot import allowed_tools
        from app.autonomy import LIBRES, nivel_de
        self.assertIn("aegis_read_file", allowed_tools())
        self.assertEqual("libre", nivel_de("aegis_read_file"))
        self.assertNotIn("quien_eres", allowed_tools())
        # La plantilla del repo, no `quien-eres.md`: ese fichero es de quien lo
        # instala y está en `.gitignore`, así que en un clon recién hecho no
        # existe. Un test que necesita el fichero personal de otra persona no
        # mide el código: mide quién lo escribió (A-057).
        with tempfile.TemporaryDirectory() as d:
            perfil = Path(d) / "quien-eres.md"
            shutil.copy(quien.PLANTILLA_PATH, perfil)
            with mock.patch.object(quien, "QUIEN_PATH", perfil):
                quien.limpiar_cache()
                self.assertIn("aegis_read_file", quien.contexto())

    def test_escribir_pide_ok(self):
        from app.autonomy import REQUIERE_OK, nivel_de
        self.assertIn("quien_eres_actualiza", REQUIERE_OK)
        self.assertEqual("requiere_ok", nivel_de("quien_eres_actualiza"))


class TestElPromptLoLleva(unittest.TestCase):
    """El bloque entra en el prompt **si hay perfil**.

    Con `quien-eres.md` ausente —que es el estado de un clon recién hecho— Aegis
    sigue arrancando sin el bloque, y eso es lo que se comprueba en
    `TestSinPerfil`. Aquí se comprueba que, cuando existe, entra y no revienta
    el presupuesto: por eso se usa la plantilla del repo y no el fichero real.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        perfil = Path(self._tmp.name) / "quien-eres.md"
        shutil.copy(quien.PLANTILLA_PATH, perfil)
        self._parche = mock.patch.object(quien, "QUIEN_PATH", perfil)
        self._parche.start()
        quien.limpiar_cache()

    def tearDown(self):
        self._parche.stop()
        quien.limpiar_cache()
        self._tmp.cleanup()

    def test_el_bloque_va_en_el_system_prompt(self):
        from app.autopilot import build_system_prompt
        p = build_system_prompt("", "aegis", "", encargo="una tarea cualquiera")
        self.assertIn("CONTIGO", p)
        self.assertLess(len(p), 30_000,
                        f"el prompt sigue siendo enorme: {len(p)}")

    def test_un_run_sin_proyecto_tambien_lo_lleva(self):
        """Hablar contigo no depende de que haya un proyecto: un encargo
        cotidiano es justamente cuando más lo necesitas."""
        from app.autopilot import build_system_prompt
        self.assertIn("CONTIGO", build_system_prompt())


class TestSinPerfil(unittest.TestCase):
    """Un clon recién hecho no tiene `quien-eres.md`. Eso no puede ser un error."""

    def test_sin_perfil_el_prompt_construye_igual(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(quien, "QUIEN_PATH", Path(d) / "no-existe.md"):
                quien.limpiar_cache()
                self.assertEqual("", quien.resumen())
                self.assertEqual("", quien.contexto())
                from app.autopilot import build_system_prompt
                prompt = build_system_prompt("", "aegis", "", encargo="x")
        self.assertNotIn("CONTIGO", prompt)
        self.assertIn("CÓMO TRABAJO", prompt)

    def test_plantilla_viene_con_el_repo(self):
        self.assertTrue(quien.PLANTILLA_PATH.is_file(),
                        "sin la plantilla, nadie sabe cómo escribir su perfil")
