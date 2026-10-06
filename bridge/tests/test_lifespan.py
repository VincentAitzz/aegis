"""El apagón de hermes y el lifespan que nunca se ejecutaba.

## Qué estaba roto
`hermes` es un singleton a nivel de módulo y `lifespan` hacía `await
hermes.aclose()` al apagar. Eso lo dejaba muerto para el resto del proceso, y como
el apagón también ocurre en los tests, **ningún test podía usar `with TestClient`**:
el `with` dispara el lifespan, el lifespan mataba el cliente compartido, y la
prueba siguiente fallaba con «the client has been closed» sin relación aparente
con lo que medía.

La consecuencia era más grande que el ruido: **el lifespan no se ejecutaba en
ningún test HTTP**, así que `init_memory`, `init_autonomia`, `init_agenda` y
`relay.on_terminal` no corrían nunca bajo test. Por eso `hooks.py` —que decide el
outcome de cada episodio— estaba esencialmente sin test de integración, y por eso
algunos tests podían pasar sin comprobar nada.

## El arreglo, en dos partes
1. Cerrar dejó de ser irreversible: `HermesClient` rehace su cliente de HTTP si
   se le pide uno después de cerrar. No es un truco para los tests; en producción
   un cliente muerto para siempre también es un bug.
2. El apagado usa `relay.lifespan_guard()`, que **ya existía y nadie llamaba**. El
   lifespan repetía a mano las dos líneas que ella hace, y los lectores SSE
   seguían vivos después de apagar.
"""
import asyncio
import os
import unittest
from unittest import mock


class TestCerrarNoEsIrreversible(unittest.TestCase):
    """Todo lo que toca hermis va en **un** `asyncio.run`, cierre incluido.

    No es estilo: un `httpx.AsyncClient` queda atado al event loop que lo creó, y
    cada `asyncio.run()` abre y cierra el suyo. Con dos, cerrar el cliente desde el
    segundo revienta con «Event loop is closed», y revienta en el `finally`, que
    es el peor sitio para descubrirlo. En producción hay un solo loop; en tests es
    la primera sorpresa, y por eso el helper de abajo lo mete todo dentro.
    """

    @staticmethod
    def _en_un_loop(fn):
        async def _todo():
            try:
                return await fn()
            finally:
                from app.hermes_client import hermes
                await hermes.aclose()
        return asyncio.run(_todo())

    def test_se_puede_usar_despues_de_cerrar(self):
        from app.hermes_client import hermes

        async def _escena():
            await hermes.aclose()
            cerrado = hermes.cerrado
            # Lo que importa no es el resultado: es que no salte «the client has
            # been closed». Antes de arreglarlo, esto reventaba aquí.
            await hermes.health()
            return cerrado, hermes.cerrado

        cerrado, despues = self._en_un_loop(_escena)
        self.assertTrue(cerrado, "aclose() no marcó el cliente como cerrado")
        self.assertFalse(despues, "el cliente no se rehizo al usarlo después")

    def test_cerrar_dos_veces_no_revienta(self):
        async def _dos():
            from app.hermes_client import hermes
            await hermes.aclose()
            await hermes.aclose()   # idempotente

        self._en_un_loop(_dos)


class TestElLifespanSeEjecuta(unittest.TestCase):
    def setUp(self) -> None:
        # El anuncio en la red local se apaga para los tests. No por ruido: sin
        # esto, `register_service` de `zeroconf` puede tardar **90 s** y lanzar
        # `TimeoutError` en un entorno sin red, y este test pasó de 4 s a 94.
        # Un `test` que dependa de que haya red es un test que depende de dónde
        # se ejecuta.
        patcher = mock.patch.dict(os.environ, {"AEGIS_SIN_DESCUBRIMIENTO": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_el_lifespan_no_anuncia_en_los_tests(self) -> None:
        """El descubrimiento no puede colarse en una prueba.

        Enseñar un servicio real en la red durante `unittest` es ruido para todo
        lo que hubiera en la LAN, y un `import` de `zeroconf` en el camino de un
        test que mide otra cosa convierte un fallo de dependencia en un fallo de
        puerta que no dice de qué.
        """
        from fastapi.testclient import TestClient
        from app import main

        with mock.patch.object(main, "_anunciar") as anunciar:
            with TestClient(main.app) as c:
                self.assertEqual(200, c.get("/health").status_code)
        anunciar.assert_not_called()

    def test_se_puede_usar_el_gestor_de_contexto(self):
        """Antes de esto, ningún test podía. Era el tell de que no se ejecutaba."""
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            self.assertEqual(200, c.get("/health").status_code)

    def test_el_apagado_cierra_el_cliente(self) -> None:
        """El lifespan cierra el cliente de Hermes al apagar.

        Antes lo hacía `relay.lifespan_guard()`, que además cancelaba los lectores
        SSE. Se borró en la Fase 1 con el segundo motor: nada creaba un run de
        Hermes desde `2f1fccb`, así que no había lectores que cancelar. Y el test
        que lo vigilaba se fue con ellos, porque un test que sigue vigilando un
        símbolo que no existe no vigila nada: pasa por no importar.
        """
        import ast
        import inspect
        import textwrap

        from app import main

        # Se mira el **cuerpo**, no el fuente entero: el docstring y los
        # comentarios cuentan por que se mencionen, y un test que lee la prosa
        # para decidir si algo se llama no testea nada —mas bien lo contrario:
        # obliga a que el comentario y el codigo no divergan, que es justo lo que
        # un `assertNotIn` sobre el fuente obliga a ser.
        cuerpo = ast.parse(textwrap.dedent(inspect.getsource(main.lifespan)))
        llamadas = {n.func.attr for n in ast.walk(cuerpo)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("aclose", llamadas,
                      "el lifespan dejo de cerrar el cliente de hermes")
        self.assertNotIn("lifespan_guard", llamadas,
                         "vuelve a depender de relay, que se borro en la Fase 1")

    def test_el_lifespan_no_toca_la_memoria_al_apagar(self) -> None:
        """Lo que el lifespan **si** tiene que inicializar al arrancar.

        Este test existe por lo que el bug de arriba tapaba: como el lifespan no
        se ejecutaba en ningun test HTTP, `init_memory`, `init_autonomia` e
        `init_agenda` no corrian nunca bajo test, y algunos tests podian pasar
        sin comprobar nada. Con el lifespan en verde se nota enseguida si alguien
        anade una inicializacion y olvida probarla.
        """
        import inspect

        from app import main
        fuente = inspect.getsource(main.lifespan)
        for inicializador in ("init_memory", "init_autonomia", "init_agenda"):
            self.assertIn(inicializador, fuente,
                          f"{inicializador} no se llama al arrancar")
