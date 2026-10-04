"""Contrato de `/memoria`: lo que la app ve de lo que Aegis recuerda.

La superficie de este endpoint son dos ramas muy distintas: el listado
recente, que sale del grafo, y la búsqueda por texto, que sale del recall.
La segunda estuvo rota durante semanas sin que nada lo delatara.
"""
import unittest




class TestLaBusquedaDevuelveAlgo(unittest.TestCase):
    """`GET /memoria?consulta=…` devolvía siempre vacío, con HTTP 200.

    ## Por qué no lo vio nadie
    La rama pedía la clave `episodios` y `recall` devuelve `episodes`. El `.get`
    devolvía `None`, la lista quedaba `[]`, y la respuesta era un 200 con «no hay
    nada». La app nunca manda `consulta`, así que la ruta se ejercitaba sin ese
    parámetro, que es la otra rama y sí funcionaba.

    Es el mismo patrón que A-083 (un fichero que carga cero no falla) aplicado al
    contrato entre dos módulos: **un `[]` es una respuesta válida**, así que nada
    delata el desajuste. Solo un test que mande la consulta lo encuentra.
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app import main as main_mod
        self.original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = ""
        self.addCleanup(self.restaurar)
        self.c = TestClient(app)

    def cabeceras(self) -> dict:
        """`/memoria` pide token porque devuelve tu trabajo, no el estado del sistema."""
        from app.main import settings
        return {"X-Aegis-Token": settings.aegis_api_key} if settings.aegis_api_key else {}

    def restaurar(self):
        from app import main as main_mod
        main_mod.settings.aegis_api_key = self.original

    def test_la_ruta_de_busqueda_responde_200(self):
        r = self.c.get("/memoria", params={"consulta": "escribir un archivo"},
                       headers=self.cabeceras())
        self.assertEqual(200, r.status_code)
        self.assertIn("episodios", r.json())

    def test_el_relleno_usa_la_que_devuelve_recall(self):
        """La clave del contrato se fija en el test, no en un comentario.

        Si `recall` cambia una clave, este test falla diciendo cuál; sin él, la
        ruta sigue contestando 200 y nadie se entera hasta que alguien busca algo
        y ve que Aegis no recuerda nada.
        """
        import asyncio
        from app.memory import get_memory
        mem = get_memory()
        if mem is None:
            self.skipTest("la memoria no está inicializada en este proceso")
        claves = asyncio.run(mem.recall("escribir un archivo", k=1))
        self.assertIn("episodes", claves)
        self.assertNotIn("episodios", claves)
