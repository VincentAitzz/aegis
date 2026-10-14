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


class TestLasLeccionesYaNoVanAlPrompt(unittest.TestCase):
    """Lo que sustituye a la puerta anterior, y por qué está escrita al revés.

    ## Antes
    Esta clase comprobaba que el índice de lecciones estaba en el prompt y que la
    lección más relevante iba entera. Se quitó el 2026-10-14, así que el test se
    **invirtió**: ahora comprueba que el bloque **no** está y que el prompt se ha
    encogido de verdad.

    Invertir un test en vez de borrarlo es lo que hace que esto no se repita. Un
    mecanismo que ya se gastó 9 200 caracteres por run y no cambió ningún
    comportamiento volvería si alguien reintrodujera la línea, y lo más fácil es
    que lo haga creyendo que mejora algo. Este test dice lo contrario, con un
    número.
    """

    def test_el_prompt_no_trae_lecciones(self):
        from app.autopilot import build_system_prompt
        p = build_system_prompt("", "aegis", "",
                                encargo="repite la llamada que ya falló dos veces")
        self.assertNotIn("LECCIONES DE ESTE PROYECTO", p)
        self.assertNotIn("La que más aplica a este encargo", p)
        # Y ninguna lección suelta: ni una referencia suelta a «A-0NN», que es
        # como se colaría una reintroducción parcial.
        self.assertNotRegex(p, r"### A-\d+")

    def test_el_prompt_se_encogio_de_verdad(self):
        """El número, no la impresión.

        `bin/medir-prompt.py` dio 17 155 antes y 7 953 después; las lecciones eran
        9 200 de eso. Se exige una banda alta y holgada —10 000— para que este
        test no se rompa con un cambio legítimo, y una baja que sigue siendo
        mucho más pequeña que la de antes.
        """
        from app.autopilot import build_system_prompt
        p = build_system_prompt("", "aegis", "",
                                encargo="repite la llamada que ya falló dos veces")
        self.assertLess(len(p), 10_000,
                        f"el prompt volvió a crecer: {len(p)} chars")
        # Y no basta con estar por debajo del tope: el cambio tiene que notarse.
        self.assertGreater(len(p), 5_000,
                           f"el prompt está sospechosamente corto: {len(p)} chars")

    def test_load_lessons_devuelve_vacio_pero_sigue_existiendo(self):
        """La función no se borra, y devuelve siempre `""`.

        Se queda a propósito: `bin/medir-prompt.py` la llama para reportar el
        bloque, y el número es lo que permite comprobar que se quitó. Una función
        borrada delata menos el sitio donde algo se apagó.
        """
        from app.autopilot import load_lessons
        self.assertEqual("", load_lessons("aegis", "cualquier cosa"))
        self.assertEqual("", load_lessons("", ""))

    def test_la_tool_lecciones_no_esta_en_el_schema(self):
        """Sacarla del prompt pero dejarla en el schema sería la mitad del gasto.

        El schema se paga en cada paso de cada run aunque la tool no se use. La
        tool tuvo 0 llamadas en los 857 run logs del repo.
        """
        from app.autopilot import allowed_tools
        self.assertNotIn("lecciones", allowed_tools())

    def test_nadie_la_declara_nivel_de_autonomia(self):
        """Una tool que ya no existe no puede seguir clasificada.

        Hay un test en otro fichero que exige que todo nombre clasificado exista
        como tool real; este comprueba el otro lado — que el nombre retirado no
        quede en ninguna de las tres listas.
        """
        from app.autonomy import CON_PERMISO, LIBRES, REQUIERE_OK
        from app.autonomy import NIVELES_CAMINO_RAPIDO
        for nivel in (LIBRES, CON_PERMISO, REQUIERE_OK, NIVELES_CAMINO_RAPIDO):
            self.assertNotIn("lecciones", nivel)

    def test_el_fichero_de_lecciones_sigue_en_el_repo(self):
        """El fichero no se borró: es documentación, y eso no ha cambiado.

        Lo que cambió es quién lo lee. Si alguien lo borra por confundirlo con
        «lo que se quitó del prompt», este test lo dice.
        """
        from app import lecciones
        self.assertTrue(lecciones.ruta("aegis").is_file(),
                        "lessons/aegis.md es documentación y no va al prompt, "
                        "pero sigue siendo el registro de por qué el código es "
                        "como es")
        self.assertTrue(lecciones.cargar("aegis"),
                        "y tiene que seguir siendo legible")


class TestNingunFicheroSeQuedaFuera(unittest.TestCase):
    """Un fichero de lecciones que no se lee no avisa: carga cero.

    ## Qué se rompió
    `lessons/portafolio.md` titula sus 14 lecciones `### R-001 · …`, y el patrón
    de encabezado exigía `(A-[0-9]+)`. Resultado: `cargar('portafolio')` devolvía
    una tupla vacía, `indice('portafolio')` devolvía cadena vacía, y el prompt de
    cada run del portafolio salía **sin lecciones**. Sin error, sin aviso, y sin
    forma de notarlo salvo llevando la cuenta a mano.

    Es la clase de bug que solo se ve con un test que itere los ficheros: el
    patrón funciona para `aegis`, así que ninguna prueba de `aegis` falla.
    """

    def test_cada_fichero_de_lecciones_aporta_al_menos_una(self):
        vacios = []
        for p in sorted(mod.LESSONS_DIR.glob("*.md")):
            if p.name.startswith("_"):
                continue
            alias = p.stem
            if not mod.cargar(alias):
                vacios.append(alias)
        self.assertEqual([], vacios,
                         "estos ficheros de lecciones no aportan ninguna al "
                         "prompt: " + ", ".join(vacios))

    def test_el_prefijo_no_descarta_lecciones(self):
        """El título es lo que el autor escribió; el prefijo no lo invalida.

        Solo comprueba `aegis`: las lecciones de un proyecto son suyas, y en un
        clon público `lessons/` solo trae las de Aegis (`.gitignore` excluye las
        demás). Un test que recorre «los proyectos que connuece quien lo escribió»
        falla en la máquina de cualquiera que contribuya (A-057).
        """
        self.assertTrue(mod.cargar("aegis"), "aegis no carga ninguna lección")

    def test_un_alias_sin_lecciones_da_vacio_y_no_excepcion(self):
        """Un proyecto sin `lessons/{alias}.md` carga vacío, no revienta.

        Es el caso de todo proyecto nuevo, así que tiene que ser la ruta normal
        y no un error: Aegis no puede negarse a trabajar porque falte un fichero
        opcional.
        """
        self.assertEqual((), mod.cargar("no-existe-este"))
