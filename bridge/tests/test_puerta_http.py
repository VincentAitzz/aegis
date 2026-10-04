"""La puerta: **ningún** endpoint que muta algo se queda sin token.

## Por qué este test y no una lista de endpoints
Comprobar uno por uno que «`/autopilot` pide token» es una photographía del
momento: el día que alguien añada `POST /algo` sin la dependencia, la photographía
sigue diciendo exactamente lo mismo, y la puerta queda abierta sin que nada lo
note. Lo que se mide aquí es la **propiedad** del app, no un endpoint: si la
propiedad se rompe, el test falla y dice cuál la rompió.

## Qué se rompió de verdad
`POST /autopilot`, `POST /autopilot/start` y el `WS /ws` no llevaban
`exigir_token` mientras `AEGIS_API_KEY` **sí** estaba definida y el bridge
enlazaba a `0.0.0.0`. O sea: la llave existía, el móvil ya la mandaba y el
agujero estaba abierto igualmente. Dos piezas correctas que nunca se juntaron.

Por eso el móvil manda la cabecera en *todas* sus peticiones
(`agent_repository_impl.dart`) y el APK la lleva embebida (`mcp_ops.py`): el
cliente ya estaba preparado y el servidor no lo estaba.
"""
import unittest

from fastapi.testclient import TestClient


class TestNingunMutanteSinPuerta(unittest.TestCase):
    """Toda ruta que crea, borra o lanza trabajo tiene que pedir `X-Aegis-Token`."""

    def setUp(self):
        from app.main import app
        self.app = app

    def _mutantes_sin_puerta(self) -> list[str]:
        sin_puerta = []
        for ruta in self.app.routes:
            metodos = getattr(ruta, "methods", None)
            if not metodos or not ({"POST", "PUT", "PATCH", "DELETE"} & set(metodos)):
                continue
            llamadas = {d.call.__name__ for d in ruta.dependant.dependencies}
            if "exigir_token" not in llamadas:
                sin_puerta.append(", ".join(sorted(metodos)) + " " + ruta.path)
        return sin_puerta

    def test_toda_ruta_mutante_pide_token(self):
        self.assertEqual(
            [], self._mutantes_sin_puerta(),
            "estas rutas cambian algo y no piden X-Aegis-Token:\n  "
            + "\n  ".join(self._mutantes_sin_puerta()))

    def test_el_autopilot_rechaza_sin_token(self):
        """Y no solo por construcción: una llamada de verdad, sin llave, es 401."""
        from app import main as main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        try:
            c = TestClient(self.app)
            for ruta in ("/autopilot", "/autopilot/start", "/tasks"):
                r = c.post(ruta, json={"prompt": "di hola", "max_steps": 1})
                self.assertEqual(401, r.status_code,
                                 f"{ruta} aceptó lanzar trabajo sin token")
        finally:
            main_mod.settings.aegis_api_key = original

    def test_lecturas_no_piden_token(self):
        """Mirar no es hacer. `/proyectos` y `/runs` se quedan abiertos a propósito.

        No es una concesión: son la superficie de diagnóstico, y un 401 en
        `/health` hace que `stack.sh estado` dé el stack por caído cuando lo que
        falla es una llave. Lo que se exige es que no se pueda **actuar**.
        """
        c = TestClient(self.app)
        for ruta in ("/health", "/proyectos"):
            self.assertEqual(200, c.get(ruta).status_code, ruta)


class TestElWsTambienCierra(unittest.TestCase):
    """El handshake del WS se comprueba **antes** del `accept()`.

    Aceptar primero y comprobar después deja el socket abierto durante la
    comprobación, y en un `accept()` no hay forma de «desaceptar»: la única
    puerta es cerrar. Con `AEGIS_API_KEY` puesta, ese socket sin comprobar
    empuja la traza de los runs a cualquiera que se conecte por la tailnet.
    """

    def _abrir_ws(self, query: str):
        """Conecta y sale. No manda nada: el mensaje de goodbye del cliente
        provocaría un error de validación en el servidor y el cierre limpio
        acabaría midiendo el shutdown en vez de la puerta."""
        from app import main as main_mod
        from fastapi.testclient import TestClient
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        try:
            c = TestClient(self.app)
            with c.websocket_connect("/ws" + query):
                pass
        finally:
            main_mod.settings.aegis_api_key = original

    def test_ws_sin_token_no_llega_a_conectarse(self):
        """El handshake se rechaza: `cliente WS conectado` **no** aparece en el log.

        No se comprueba el tipo de excepción que lance el transporte, porque
        depende del cliente de prueba y no de lo que hace el bridge. Lo que se
        comprueba es la consecuencia: el socket no llegó a estar conectado, y eso
        es exactamente lo que evita publicar la traza.
        """
        with self.assertLogs("aegis.bridge", level="INFO") as registro:
            try:
                self._abrir_ws("")
            except Exception:
                pass
        self.assertNotIn("cliente WS conectado",
                         "\n".join(registro.output))

    def test_ws_con_token_correcto_acepta(self):
        """Con la llave, el socket abre. Si esto falla, la puerta está mal puesta."""
        with self.assertLogs("aegis.bridge", level="INFO") as registro:
            self._abrir_ws("?token=clave-de-prueba")
        self.assertIn("cliente WS conectado", "\n".join(registro.output))

    @property
    def app(self):
        from app.main import app
        return app
