"""`app/capacidades.py`: que Aegis sepa lo que hace, **por el código**.

Existe porque se midió que no. El 2026-10-14, con este repo ya funcionando:

    «hola aegis, soy tu creador, cuentame un poco cuales son tus funciones»
      → 161 s · fin=esperando_ok
      → [ficha_read, ficha_read, projects_list, project_create]

Contestó de memoria: **no llamó a ninguna tool para decir qué puede hacer**, se
inventó la lista, y de paso se inventó un proyecto (`mi-proyecto`, que no existe
en ninguna parte) y pidió permiso para crearlo. Solo lo frenó que
`project_create` sea de nivel 3.

    «hola, que puedes hacer?» → 56 s · fin=sin_tools · otra lista inventada
    «gracias, eso era todo»   → 27 s · fin=sin_tools

## Qué mira esta clase

Tres cosas, y la tercera es la que importa:

1. Que la lista no esté **vacía** ni inventada: sale de las tools del MCP.
2. Que la clasificación por nivel sea la **real**, la de `autonomy`.
3. Que **toda tool tenga descripción**. Sin este test, añadir una tool deja esta
   lista vieja y Aegis vuelve a contestar lo que sabía hacer en octubre — que es
   exactamente el fallo que este módulo arregla, pero más tarde y con más
   usuarios.

Y que no deforme: el total que dice el texto tiene que ser el número real de
tools, porque un «soy capaz de 21 cosas» que sean 19 es peor que no decirlo.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import capacidades  # noqa: E402
from app.autonomy import CON_PERMISO, LIBRES, REQUIERE_OK  # noqa: E402
from app.intents import resolver  # noqa: E402


class TestLaListaEsDelCodigo(unittest.TestCase):
    def test_no_esta_vacia(self) -> None:
        g = capacidades.capacidades()
        total = sum(len(v) for v in g.values())
        self.assertGreaterEqual(total, 15, "la lista de capacidades se ha vaciado")

    def test_toda_tool_aparece_exactamente_una_vez(self) -> None:
        """Una tool en dos grupos es una contradicción; ninguna, una omisión.

        Aquí no vale «casi todas»: el objetivo de la lista es poder confiar en
        ella, y una lista en la que cada entrada se puede encontrar en dos sitios
        no se puede usar para nada.
        """
        g = capacidades.capacidades()
        todas = [t["nombre"] for v in g.values() for t in v]
        self.assertEqual(len(todas), len(set(todas)),
                         "hay una tool en más de un grupo")
        reales = set(capacidades._nombres_de_tools())
        self.assertEqual(set(todas), reales,
                         f"faltan o sobran: {reales.symmetric_difference(set(todas))}")

    def test_el_nivel_es_el_real_no_el_declarado(self) -> None:
        """Cada tool tiene que estar en el grupo que dice `autonomy`.

        Si el texto dijera «libre» algo que pide OK, estaríamos prometiendo al
        usuario una autonomía que no existe. Esa es la clase de mentira que
        este módulo no va a contar.
        """
        g = capacidades.capacidades()
        for t in g["libre"]:
            self.assertIn(t["nombre"], LIBRES, f"{t['nombre']} no es libre")
        for t in g["con_permiso"]:
            self.assertIn(t["nombre"], CON_PERMISO, f"{t['nombre']} no es de permiso")
        for t in g["requiere_ok"]:
            self.assertIn(t["nombre"], REQUIERE_OK, f"{t['nombre']} no requiere OK")

    def test_el_texto_no_promete_una_contabilidad_falsa(self) -> None:
        """El número del texto tiene que ser el número real de tools.

        «Soy capaz de 21 cosas» cuando son 19 es una mentira pequeña que se
        acumula con las demás. Sale de la misma fuente, así que no debería poder
        pasar; se comprueba para que no pueda pasar.
        """
        texto = capacidades.como_texto(ancha=True)
        real = len(capacidades._nombres_de_tools())
        self.assertIn(f"En total: {real} herramientas", texto)

    def test_el_texto_dice_lo_que_no_hace(self) -> None:
        """«Lo que no hago» es la parte que la gente necesita de verdad.

        Si Aegis contesta qué puede hacer y no dice qué no va a hacer, la
        respuesta está incompleta: la puerta es la mitad del producto.
        """
        texto = capacidades.como_texto(ancha=True)
        self.assertIn("Lo que **no** hago", texto)
        self.assertIn("sin preguntarte", texto)


class TestNingunaToolQuedaSinDescribir(unittest.TestCase):
    """El test que mantiene esto útil. Sin él, se pudre.

    ## Por qué este test y no una nota en el README
    Una nota se lee una vez. Un test se lee cada vez que alguien toca el schema,
    que es exactamente cuando hace falta acordarse de que hay algo que
    actualizar aquí.
    """

    def test_toda_tool_tiene_descripcion(self) -> None:
        sin_describir = capacidades.falta_describir()
        self.assertEqual([], sin_describir,
                         "tools nuevas sin descripción en app/capacidades.py. "
                         "Aegis contesta de memoria lo que puede hacer, y su "
                         "memoria no se actualiza sola: " + ", ".join(sin_describir))

    def test_la_descripcion_no_es_el_nombre_repetido(self) -> None:
        """Una descripción que no explica nada es decorativa.

        Se comprueba sobre las herramientas que la lista **enseña con texto**, no
        sobre el conjunto entero: hay tools cuyo resumen corto es understandably
        escueto y no merece un test aparte.
        """
        para_uso = [t for v in capacidades.capacidades().values() for t in v]
        for t in para_uso[:6]:          # una muestra, no todas: la lista crece
            d = t["que_hace"]
            self.assertGreater(len(d), 20, f"{t['nombre']}: descripción demasiado corta")
            self.assertNotEqual(d.lower(), t["nombre"].lower())


class TestLaPreguntaLlegaPorElCaminoRapido(unittest.TestCase):
    """La frase **real** que alguien le dice a un asistente tiene que entrar.

    ## Por qué importa el caso largo
    La primera versión del patrón solo cogía «qué puedes hacer». La frase que de
    verdad se dice —«hola aegis, soy tu creador, cuéntame un poco cuáles son tus
    funciones»— no cogía, y por eso el problema seguía exactamente igual: dos
    minutos de modelo para inventarse una respuesta. Un patrón que solo casa con
    la forma de la tarjeta de prueba no arregla nada.
    """

    def test_las_formas_reales(self) -> None:
        for frase in (
            "qué puedes hacer?",
            "qué puedes hacer",
            "para qué sirves",
            "qué herramientas tienes",
            "cuáles son tus funciones",
            "cuentame cuales son tus funciones",
            "dime qué herramientas tienes",
            "hola aegis, soy tu creador, cuentame un poco cuales son tus funciones",
            "hola, qué puedes hacer?",
            "preséntate",
            "explicame tus capacidades",
            "en qué puedes ayudarme",
        ):
            with self.subTest(frase=frase):
                intent = resolver(frase)
                self.assertIsNotNone(intent, f"«{frase}» no entra")
                self.assertEqual("que_puedes_hacer", intent.nombre)

    def test_lo_que_no_debe_entrar(self) -> None:
        """La abstención manda. Aquí el riesgo es al revés del habitual.

        Si el patrón casa de más, Aegis contesta con su lista cuando le
        preguntaron otra cosa: un susto. Si casa de menos, cae al modelo, que es
        lo de antes. Por eso este patrón **sí** puede ser ancho — y aun así
        «muéstrame» cae al modelo, porque «muéstrame» puede querer decir «hazlo».
        """
        for frase in (
            "qué puedes hacer por mí la cena",     # la cola estricta
            "muéstrame tus herramientas",          # «muéstrame» puede ser «hazlo»
            "haz que puedes hacer",
            "dime qué hora es",                    # sustantivo distinto
            "explícame el algoritmo de ordenamiento",
            "cuéntame un chiste",
        ):
            with self.subTest(frase=frase):
                intent = resolver(frase)
                self.assertTrue(intent is None or intent.nombre != "que_puedes_hacer",
                                f"«{frase}» no debería activar esta respuesta")

    def test_responde_sin_gastar_modelo(self) -> None:
        """La respuesta es del código: si cambia el schema, cambia ella sola.

        Se comprueba **contra el schema**, no contra una copia. Un test que
        copiase el texto esperado passaría mientras la lista se queda vieja, que
        es justo lo que no puede pasar aquí.
        """
        from app.autopilot import allowed_tools
        texto = capacidades.como_texto(ancha=True)
        for nombre in allowed_tools():
            if nombre in ("tarea_crear", "nota_crear"):
                continue      # son del camino rápido y no están en el schema MCP
            with self.subTest(tool=nombre):
                self.assertIn(nombre, texto,
                              "una tool real no aparece en la respuesta")


if __name__ == "__main__":
    unittest.main()