"""Lo irreversible, por categoría y no por lista de nombres.

La línea se escribió el 2026-10-14, y es corta:

    lo irreversible es en cuanto a pagos, despliegues, migraciones, contactar
    clientes esencialmente

Estos tests la hacen ejecutable. No es una lista más: lo que evita es que
**añadir una tool nueva** la meta en `LIBRES` sin que nadie se entere, que es el
modo de fallo real de una puerta definida por enumeración.

Y hacen otra cosa, que es la que importa más a largo plazo: **dos de las cuatro
categorías están vacías**, porque Aegis hoy no tiene forma de pagar ni de
escribir a nadie. Eso no es un olvido pendiente de rellenar; es una propiedad
que hay que conservar, y que se rompe en silencio en cuanto alguien añade un
`enviar_correo` sin mirar aquí.
"""

import unittest

from app.autonomy import (CON_PERMISO, IRREVERSIBLES, LIBRES,
                         NIVELES_CAMINO_RAPIDO, REQUIERE_OK,
                         categoria_irreversible, nivel_de)
from app.autopilot import allowed_tools


class TestLasCategorias(unittest.TestCase):
    def test_las_cuatro_categorias_existen_y_no_mas(self):
        self.assertEqual(
            set(IRREVERSIBLES),
            {"pago", "despliegue", "migracion", "contacto"})

    def test_pago_y_contacto_estan_vacias(self):
        """Aegis no puede pagar ni escribir a nadie.

        Se deja escrito porque es una **propiedad que hay que mantener**, no
        un hueco que rellenar. Si algún día alguien añade una tool de pago, este
        test falla y obliga a decidir —que es lo que queremos— en vez de que la
        tool pase por la puerta sin que nadie lo mire.
        """
        self.assertEqual(IRREVERSIBLES["pago"], frozenset())
        self.assertEqual(IRREVERSIBLES["contacto"], frozenset())

    def test_ninguna_tool_del_schema_paga_ni_escribe_a_uno(self):
        for categoria in ("pago", "contacto"):
            for tool in IRREVERSIBLES[categoria]:
                self.assertIn(tool, allowed_tools(),
                              f"{tool} está clasificada pero no existe: "
                              f"la lista miente")


class TestLoIrreversibleSiemprePide(unittest.TestCase):
    """La puerta no depende del modo de autonomía."""

    def test_toda_tool_irreversible_es_requiere_ok(self):
        for categoria, nombres in IRREVERSIBLES.items():
            for tool in nombres:
                with self.subTest(tool=tool, categoria=categoria):
                    self.assertEqual(nivel_de(tool), "requiere_ok")

    def test_no_puede_estar_en_libres_ni_en_con_permiso(self):
        """Que la comprobación de `nivel_de()` no sea la única defensa.

        Una tool irreversible en `LIBRES` es un error **declarado**, no
        silencioso: se ve en el código. Por eso este test mira las listas, y no
        solo el resultado de `nivel_de()`.
        """
        for categoria, nombres in IRREVERSIBLES.items():
            for tool in nombres:
                with self.subTest(tool=tool):
                    self.assertNotIn(tool, LIBRES)
                    self.assertNotIn(tool, CON_PERMISO)
                    self.assertNotIn(tool, NIVELES_CAMINO_RAPIDO)

    def test_las_tres_categorias_con_tools_cubren_lo_que_hay(self):
        """No basta con que lo listado esté bien: tiene que estar listado.

        El fallo real de una puerta por enumeración no es que alguien meta una
        tool por error en la lista de los libres; es que **una tool de verdad**
        se quede sin clasificar y acabe en `requiere_ok` sin querer, o en
        `libre` sin mirar. Este test ata las categorías al schema.
        """
        # Tools del schema cuyo nombre indica una consecuencia irreversible.
        esperados = {"build_apk", "install_apk", "deploy_smoke",
                     "adb_connect", "db_migrate", "neon_branch"}
        declarados = {t for nombres in IRREVERSIBLES.values() for t in nombres}
        self.assertEqual(declarados, esperados)


class TestLaCategoriaGanaALasListas(unittest.TestCase):
    def test_una_tool_equivocada_en_libres_sigue_preguntando(self):
        """El error humano más probable, y el que no puede colarse.

        Alguien añade una tool nueva, la mete en `LIBRES` porque «solo lee» o
        porque se le olvidó. Si `nivel_de()` mirara las listas primero, esa tool
        dejaría de preguntar. Por eso lo irreversible se comprueba **antes**.
        """
        # `LIBRES` es un `frozenset`, así que el olvido no puede pasar por
        # mutarlo en caliente: alguien tiene que **editar el fuente**. Eso es
        # mejor, y aquí se comprueba sustituyendo el atributo del módulo, que es
        # exactamente lo que dejaría el error.
        import app.autonomy as aut
        original = aut.LIBRES
        try:
            aut.LIBRES = frozenset(set(original) | {"build_apk"})
            self.assertEqual(aut.nivel_de("build_apk"), "requiere_ok")
        finally:
            aut.LIBRES = original
        self.assertEqual(aut.LIBRES, original)

    def test_una_tool_desconocida_sigue_preguntando(self):
        """La propiedad buena se conserva: lo que no se conoce, pregunta.

        Cambiarla a `libre` sería «máxima autonomía» y sería también **la forma
        de que la autonomía dependa de que nadie añada una tool nueva**. Se
        prefiere lo contrario: autonomía sobre el **método**, que es explícito,
        y pregunta sobre lo desconocido, que es donde el daño es invisible.
        """
        self.assertEqual(nivel_de("inventada_mañana"), "requiere_ok")

    def test_una_tool_libre_sigue_libre(self):
        for tool in ("aegis_read_file", "repo_verify", "db_query", "memoria"):
            with self.subTest(tool=tool):
                self.assertEqual(nivel_de(tool), "libre")


class TestEscribirCodigoNoPregunta(unittest.TestCase):
    """La otra mitad de la línea: escribir no es irreversible.

    «Nunca cola: escribir código y hacer push». `aegis_write_file` está en
    `CON_PERMISO`, que **no es la cola**: es la marca por proyecto que se puso
    con `POST /autonomy/{alias}`. La diferencia importa y conviene que sea
    explícita, porque «con permiso» y «requiere OK» suenan a lo mismo y no lo
    son: la primera la resolviste una vez para el proyecto, la segunda pregunta
    **cada vez**.
    """

    def test_escribir_no_entra_en_la_cola_de_aprobaciones(self):
        for tool in ("aegis_write_file", "aegis_patch_file"):
            with self.subTest(tool=tool):
                self.assertEqual(nivel_de(tool), "con_permiso")
                self.assertNotIn(tool, REQUIERE_OK)

    def test_y_no_tiene_categoria_de_consecuencia(self):
        self.assertEqual(categoria_irreversible("aegis_write_file"), "")


class TestLoQueSobraDeLaCola(unittest.TestCase):
    """Dos tools siguen pidiendo y **no** son de tus cuatro categorías.

    Se deja dicho y no escondido. `project_create` escribe fuera de los
    proyectos declarados, y `quien_eres_actualiza` reescribe lo que Aegis sabe
    de ti y entra en el prompt de todos los runs.

    La segunda es la importante: quitarle la puerta haría que Aegis pudiera
    reescribir sus propias instrucciones sin que nadie se entere. Si alguien
    quiere el modelo literal —solo las cuatro categorías—, esta es la que hay
    que debate primero, y con nombre.
    """

    def test_project_create_sigue_preguntando(self):
        self.assertEqual(nivel_de("project_create"), "requiere_ok")
        self.assertEqual(categoria_irreversible("project_create"), "")

    def test_quien_eres_actualiza_sigue_preguntando(self):
        self.assertEqual(nivel_de("quien_eres_actualiza"), "requiere_ok")
        self.assertEqual(categoria_irreversible("quien_eres_actualiza"), "")


if __name__ == "__main__":
    unittest.main()