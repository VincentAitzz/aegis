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
import unittest


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
    def test_se_puede_usar_el_gestor_de_contexto(self):
        """Antes de esto, ningún test podía. Era el tell de que no se ejecutaba."""
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            self.assertEqual(200, c.get("/health").status_code)

    def test_el_apagado_cancela_los_lectores(self):
        """`lifespan_guard` hacía esto y no la llamaba nadie."""
        import inspect

        from app import relay
        fuente = inspect.getsource(relay.lifespan_guard)
        self.assertIn("aegis-relay-reader", fuente,
                      "lifespan_guard ya no cancela los lectores: mirarla otra vez")

    def test_main_usa_la_que_ya_existia(self):
        """Que el lifespan llame a `lifespan_guard`, y no la repita a mano."""
        import inspect

        from app import main
        fuente = inspect.getsource(main.lifespan)
        self.assertIn("lifespan_guard", fuente)
        self.assertNotIn("hermes.aclose()", fuente,
                         "el lifespan volvio a cerrar hermes a mano, duplicando "
                         "lo que lifespan_guard ya hace")
