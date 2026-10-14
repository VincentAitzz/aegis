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
            # `/tasks` se quitó en la Fase 1 (el segundo motor). Lo que queda
            # son las dos formas de lanzar un run, y las dos tienen que Cerrar.
            for ruta in ("/autopilot", "/autopilot/start"):
                r = c.post(ruta, json={"prompt": "di hola", "max_steps": 1})
                self.assertEqual(401, r.status_code,
                                 f"{ruta} aceptó lanzar trabajo sin token")
        finally:
            main_mod.settings.aegis_api_key = original

    def test_lecturas_no_piden_token(self):
        """Las de la lista se quedan abiertas. Y están en la lista, no «por omisión».

        Un 401 en `/health` hace que `stack.sh estado` dé el stack por caído cuando
        lo que falla es una llave, y ese es el trabajo de un watchdog: que verse.
        """
        from app.main import LECTURAS_ABIERTAS
        c = TestClient(self.app)
        for ruta in sorted(LECTURAS_ABIERTAS):
            respuesta = c.get(ruta if "{" not in ruta else ruta.split("{")[0])
            self.assertNotEqual(401, respuesta.status_code, ruta)

    def test_lectura_nueva_nace_cerrada(self):
        """**Toda** ruta ha de tener la dependencia o estar en `LECTURAS_ABIERTAS`.

        Este es el test que hace la lista una puerta y no una sugerencia. La
        versión anterior solo miraba las rutas que mutan, y por eso
        `GET /autopilot/{id}` —que devuelve tu prompt literal y los argumentos de
        cada tool— llevaba semanas abierta con el test de arriba en verde.
        La diferencia entre mutar y leer no era la regla: la regla es si **sale
        algo tuyo** por detrás.
        """
        from app.main import LECTURAS_ABIERTAS
        sin_puerta = []
        for ruta in self.app.routes:
            metodos = getattr(ruta, "methods", None)
            if not metodos:
                continue
            if ruta.path.startswith(("/oauth2",)):
                continue
            tiene = getattr(ruta, "dependant", None) and "exigir_token" in {
                d.call.__name__ for d in ruta.dependant.dependencies}
            if not tiene and ruta.path not in LECTURAS_ABIERTAS:
                sin_puerta.append(", ".join(sorted(metodos)) + " " + ruta.path)
        self.assertEqual([], sin_puerta,
                         "estas rutas no piden token y no están en "
                         "LECTURAS_ABIERTAS, así que nacieron abiertas:\n  "
                         + "\n  ".join(sin_puerta))

    def test_la_superficie_de_la_api_no_se_sirve_sin_llave(self):
        """`/docs`, `/redoc` y `/openapi.json` no son una excepción: son la puerta.

        Este test antes no existía, y el hueco era real: los tres devolvían 200
        sin token y publicaban el mapa entero de la API. Para colarse, el test de
        propiedades de arriba **excluía esas tres rutas a propósito** —no entran en
        `app.routes` como las demás—, así que el guardarraíl estaba escrito y no
        cubría el hueco.

        Ahora el `FastAPI` se construye con las tres en `None` y devuelven 404.
        """
        c = TestClient(self.app)
        for ruta in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(404, c.get(ruta).status_code, ruta)

    def test_un_run_no_se_lee_sin_llave(self):
        """La que se coló: la traza completa, con tus encargos y los argumentos."""
        from app import main as main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        try:
            c = TestClient(self.app)
            r = c.get("/autopilot/run_cualquiera")
            self.assertEqual(401, r.status_code)
        finally:
            main_mod.settings.aegis_api_key = original

    def test_una_ficha_no_se_lee_sin_llave(self):
        """La ficha de un cliente es trabajo tuyo aunque no haya escrito nada."""
        from app import main as main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        try:
            c = TestClient(self.app)
            self.assertEqual(401, c.get("/fichas/recepcion-persa").status_code)
        finally:
            main_mod.settings.aegis_api_key = original


class TestNoQuedaNingunCanalSinPuerta(unittest.TestCase):
    """El WS se quitó en la Fase 1, y con él su test de handshake.

    Antes había dos superficies: HTTP (con `exigir_token`) y el WebSocket, que
    necesitaba su propio camino porque la API de WebSocket del navegador **no
    puede poner cabeceras** en el handshake. Eso obligaba a `_ws_exigir_token`,
    que cerraba el socket **antes** del `accept()` para no dejar la puerta abierta
    ni un instante. Todo eso desaparece con la ruta.

    Este test fija el hecho nuevo, que es el que de verdad importa: **ya no
    existe ninguna superficie que no pase por `exigir_token`**. No es que el WS
    esté cerrado —es que no hay segundo camino, y un segundo camino es
    exactamente donde vive un guardarraíl que nadie recuerda.
    """

    @property
    def app(self):
        from app.main import app
        return app

    def test_no_hay_websocket(self) -> None:
        websockets = [r.path for r in self.app.routes if hasattr(r, "websocket")]
        self.assertEqual([], websockets,
                         "vuelve a haber un canal que no pasa por exigir_token")

    def test_no_hay_ruta_de_hermes(self) -> None:
        """`/tasks*` gobernaba runs en el motor que ya no existe. Si vuelve,
        vuelve un segundo motor con tools (`docs/motores.md` §6)."""
        tasks = [r.path for r in self.app.routes
                 if hasattr(r, "path") and r.path.startswith("/tasks")]
        self.assertEqual([], tasks)

    def test_toda_ruta_solo_por_http(self) -> None:
        """Y para que no quede un `if` sobre el metodo que se cuele: toda ruta
        con metodos tiene que ser HTTP."""
        for r in self.app.routes:
            metodos = getattr(r, "methods", None)
            if metodos:
                self.assertTrue({"GET", "POST", "PUT", "PATCH", "DELETE"} & set(metodos),
                                f"{r.path} no es HTTP")
