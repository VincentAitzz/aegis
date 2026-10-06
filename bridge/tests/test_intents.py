"""El camino rápido: qué casa, qué se abstiene, y que no toca el modelo.

## Los tres tests que importan
1. **La abstención**: un casi-fallo tiene que abstain. «no me digas qué hora es»
   contiene las palabras de «qué hora es»: si eso ejecutara, el router haría
   justo lo contrario de lo pedido.
2. **Cero tokens**: con Ollama patched para que **reviente**, un T0 completo
   sigue funcionando. Es la prueba de que el presupuesto de 300 ms con 0 tokens
   no es una frase del plan: es un hecho.
3. **Latencia**: medida dentro del test, contra el presupuesto de `vision.md`.

## Por qué hay una prueba de tildes
Porque `re.IGNORECASE` **no** pliega acentos: convierte mayúsculas, no quitar tildes.
Los patrones se escriben sin tilde a propósito y `_sin_acentos` pliega las dos
formas. Ese bug existió: `qué hora es` no casaba con `que hora es` y el módulo
parecía funcionar porque `dime la hora` —sin tilde— sí pasaba.
"""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import intents  # noqa: E402


class TestLoQueTieneQueCasa(unittest.TestCase):
    """Cada intent, en las formas en que alguien lo dice de verdad."""

    CASAN = [
        # (frase, intent esperado)
        ("¿qué hora es?", "que_hora_es"),
        ("qué hora es", "que_hora_es"),
        ("que hora es", "que_hora_es"),                 # sin tilde
        ("dime la hora", "que_hora_es"),
        ("la hora", "que_hora_es"),
        ("hora", "que_hora_es"),
        ("oye aegis qué hora es", "que_hora_es"),      # vocativo dentro
        ("aegis, dime la hora", "que_hora_es"),
        ("¿qué día es hoy?", "que_dia_es"),
        ("que dia es", "que_dia_es"),                  # sin tilde
        ("¿qué proyectos hay?", "lista_proyectos"),
        ("que proyectos hay", "lista_proyectos"),
        ("lista mis proyectos", "lista_proyectos"),
        ("mis tareas", "lista_tareas"),
        ("¿qué me toca?", "lista_tareas"),
        ("qué pendientes tengo", "lista_tareas"),
        ("oye, lista mis tareas", "lista_tareas"),
        ("listar tareas", "lista_tareas"),
    ]

    def test_cada_forma_casa_con_su_intent(self) -> None:
        fallos = []
        for frase, esperado in self.CASAN:
            intent = intents.resolver(frase)
            got = intent.nombre if intent else None
            if got != esperado:
                fallos.append(f"{frase!r}: esperaba {esperado}, dio {got}")
        self.assertEqual([], fallos, "\n".join(fallos))

    def test_hora_devuelve_una_hora_real(self) -> None:
        """No basta con que case: tiene que devolver la hora de verdad.

        Un test que solo comprueba que el patrón casa pasa aunque el ejecutor
        devuelva cadena vacía. Y este texto lo va a leer un TTS: si no tiene
        formato de hora, se oye basura.
        """
        import datetime as _dt
        import re as _re
        r = intents.ejecutar("¿qué hora es?")
        self.assertTrue(r.clase, "no ejecutó")
        # Formato: un TTS lee esto, y "son las 0:59" o "son las 00h59" no vale.
        casa = _re.search(r"\b(\d{1,2}):(\d{2})\b", r.texto)
        self.assertIsNotNone(casa, f"no parece una hora: {r.texto!r}")
        # Y tiene que ser la de ahora, no una fija: si el ejecutor devolviera
        # "son las 00:00" hardcodeado, el formato anterior lo aprobaría.
        esperado = _dt.datetime.now().strftime("%H:%M")
        self.assertIn(esperado, r.texto,
                      f"la hora no es la de ahora (esperaba ~{esperado}, dio {r.texto!r})")


class TestLoQueTieneQueAbstenerse(unittest.TestCase):
    """La regla de oro: lo dudoso cae al modelo.

    Una petición malinterpretada es peor que una lenta. Aquí la consecuencia de
    equivocarse sería que Aegis haga algo que nadie pidió.
    """

    ABSTIENEN = [
        # Una hora aborta. Las tres formas, y el caso que ya pasó una vez:
        # la comprobación pedía la palabra «hora», así que «a las 7» colaba y
        # creaba la alarma para el día equivocado. Es justo el fallo que el
        # abstain existe para evitar.
        "pon una alarma hoy a las 7",
        "pon una alarma a las 19:30",
        "pon una alarma para las 8",
        "pon una alarma a las 7 y media",
        # El casi-fallo canónico: mismas palabras, sentido contrario.
        "no me digas qué hora es",
        "¿sabes la hora?",
        "explica qué hora es y por qué el reloj va atrasado",
        # Una pregunta con más de un tema: el router no razona.
        "qué proyectos hay y cuál está roto",
        "qué hora marca el reloj atómico",
        "qué hora es en Tokio",
        # Trabajo de verdad: esto es T1/T2, no T0.
        "añade un test a autopilot",
        "arregla el error de la puerta",
        "crea el módulo de facturación",
        "quién es Ana",
        "cuánto cuesta el Hosting",
        # La confianza se nota.
        "hola",
        "",
        "   ",
        # Una alarma con hora no cabe en el modelo de datos.
        "pon una alarma a las 7",
        "dentro de 20 minutos avísame",
    ]

    def test_ninguno_ejecuta(self) -> None:
        ejecutados = []
        for frase in self.ABSTIENEN:
            r = intents.ejecutar(frase)
            if r.clase:
                ejecutados.append(f"{frase!r} ejecutó como {r.clase} ({r.intent})")
        self.assertEqual([], ejecutados, "\n".join(ejecutados))

    def test_vacio_abstiene_sin_romperse(self) -> None:
        """Una petición vacía es el caso normal de un cliente que manda de más."""
        self.assertIsNone(intents.resolver(""))
        self.assertEqual("", intents.ejecutar("").clase)


class TestUnIntentQueEscribeNoEjecutaSinFecha(unittest.TestCase):
    """El caso raro: el patrón casa pero la operación no se puede hacer."""

    def test_alarma_con_hora_abstiene_en_vez_de_guardar_media_cosa(self) -> None:
        """El patrón casa, pero calcular aborta: no hay campo de hora."""
        self.assertIsNotNone(intents.resolver("pon una alarma a las 7"),
                             "el patrón debería casar")
        self.assertIsNone(intents.preparar("pon una alarma a las 7"),
                          "pero calcular tiene que abortar: `para` es solo fecha")

    def test_la_comprobacion_de_hora_no_depende_de_la_palabra_hora(self) -> None:
        """Regresión del bug: exigía «hora» y «a las 7» no la traía.

        Con el bug, «pon una alarma hoy a las 7» creaba la alarma **para hoy**.
        Y devolvía un 200 y un texto de éxito, así que ningún test de «devuelve
        bien» lo habría visto: hay que mirar `para`.
        """
        for frase in ("pon una alarma hoy a las 7", "pon una alarma para las 8",
                      "pon una alarma a las 19:30"):
            self.assertIsNone(intents.preparar(frase), f"{frase!r} no abortó")

    def test_el_titulo_no_es_relleno(self) -> None:
        """El título es lo que oye el TTS. «una mañana» no dice nada."""
        plan = intents.preparar("pon una alarma mañana")
        self.assertIsNotNone(plan)
        self.assertEqual("Alarma", plan.args["titulo"],
                         "el título salió como relleno")
        # Y cuando sí hay contenido, se conserva lo que sí dice algo.
        plan2 = intents.preparar("pon una alarma para revisar el presupuesto mañana")
        self.assertIsNotNone(plan2)
        self.assertIn("presupuesto", plan2.args["titulo"])

    def test_no_crea_ninguna_tarea(self) -> None:
        """Lo que hay que comprobar de verdad: que no escribiera nada.

        Si aceptara la hora y guardara solo la fecha, habría creado una alarma
        **diciendo que la creó** y estaría tres horas antes de lo pedido. Verificar
        el texto de respuesta no lo caza: hay que mirar la base.
        """
        from app.notas import agenda
        antes = len(agenda().tareas(limite=200))
        intents.preparar("pon una alarma a las 7")
        intents.preparar("pon una alarma el martes")
        despues = len(agenda().tareas(limite=200))
        self.assertEqual(antes, despues,
                         "preparar() escribió: tiene que ser puro")


class TestCeroTokens(unittest.TestCase):
    """La prueba de que T0 no toca el modelo. Es la que sostiene el presupuesto.

    La forma es deliberada: **no** se comprueba que la llamada fuera rápida, sino
    que el camino funciona con Ollama sustituido por algo que revienta. Si
    anything del camino rápido tocara el modelo, esto falla.
    """

    def test_una_hora_funciona_con_ollama_roto(self) -> None:
        class _Revienta:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            def post(self, *a, **k):
                raise AssertionError("¡el camino rápido ha llamado al modelo!")

        with mock.patch("app.llm.httpx.AsyncClient", _Revienta):
            r = intents.ejecutar("¿qué hora es?")
        self.assertTrue(r.clase)
        self.assertTrue(r.sin_modelo)

    def test_listar_proyectos_funciona_con_ollama_roto(self) -> None:
        class _Revienta:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            def get(self, *a, **k):
                raise AssertionError("¡el camino rápido ha llamado al modelo!")

        with mock.patch("app.llm.httpx.AsyncClient", _Revienta):
            r = intents.ejecutar("¿qué proyectos hay?")
        self.assertTrue(r.clase)
        self.assertIn("proyectos", r.texto)


class TestPresupuestoDeLatencia(unittest.TestCase):
    """300 ms es lo que dice `docs/vision.md` §5 para T0. Se comprueba aquí.

    ## Por qué el presupuesto está en un test y no solo en el documento
    Porque un presupuesto que no se mide se convierte en un deseo. Y este es
    barato: leer la hora son nanosegundos, y los intents con SQLite van a
    fracciones de milisegundo. Si algún día esto falla, el culpable es alguien que
    metió un `sleep` o una llamada a red en el camino rápido.
    """

    #: El presupuesto de `docs/vision.md`, copiado aquí a propósito. Si cambia el
    #: documento, este número tiene que cambiar con él, y que se note en el diff.
    PRESUPUESTO_MS = 300

    def test_los_intents_de_lectura_caben(self) -> None:
        lentos = []
        for frase in ("¿qué hora es?", "¿qué día es hoy?", "¿qué proyectos hay?",
                      "mis tareas", "¿qué me toca?"):
            t0 = time.perf_counter()
            r = intents.ejecutar(frase)
            ms = (time.perf_counter() - t0) * 1000
            if not r.clase:
                continue                       # si no ejecuta, no hay coste que medir
            if ms > self.PRESUPUESTO_MS:
                lentos.append(f"{frase!r} tardó {ms:.1f} ms")
        self.assertEqual([], lentos,
                         "un intent de lectura se pasó del presupuesto de "
                         f"{self.PRESUPUESTO_MS} ms:\n  " + "\n  ".join(lentos))

    def test_el_intent_reporta_su_propio_coste(self) -> None:
        """Que el resultado diga cuánto tardó. Sin esto no hay presupuesto posible:
        la decisión de T0/T1 se toma con número, no con impresión."""
        r = intents.ejecutar("¿qué hora es?")
        self.assertIsInstance(r.ms, float)
        self.assertGreater(r.ms, 0.0)
        self.assertLess(r.ms, self.PRESUPUESTO_MS)


class TestLaAcentuacion(unittest.TestCase):
    """La forma con tilde y sin tilde tienen que dar lo mismo.

    El TTS no las pone y el teclado a veces. Y `re.IGNORECASE` no pliega acentos:
    convierte mayúsculas, no quita diacríticos.
    """

    def test_con_y_sin_tilde_casan_igual(self) -> None:
        for con, sin in (("qué hora es", "que hora es"),
                         ("qué día es hoy", "que dia es hoy"),
                         ("qué proyectos hay", "que proyectos hay"),
                         ("qué me toca", "que me toca")):
            a = intents.resolver(con)
            b = intents.resolver(sin)
            self.assertIsNotNone(a, f"{con!r} no casó")
            self.assertEqual(a.nombre, b.nombre if b else None,
                             f"{con!r} y {sin!r} dieron intents distintos")

    def test_sin_acentos_plega_la_enie(self) -> None:
        self.assertEqual("manana", intents._sin_acentos("mañana"))


class TestLaPuertaEstaAntesDeEscribir(unittest.TestCase):
    """`ejecutar` **no puede** escribir. Es la propiedad que hace que `main.py`
    tenga que pasar por `decide`, y no sea una convención."""

    def test_ejecutar_se_niega_a_escribir(self) -> None:
        plan = intents.preparar("pon una alarma mañana")
        self.assertIsNotNone(plan)
        self.assertTrue(plan.escribe)
        with self.assertRaises(RuntimeError):
            intents.ejecutar("pon una alarma mañana")

    def test_preparar_no_escribe(self) -> None:
        """La que de verdad importa: `preparar` es puro, aunque el intent escriba.

        Si `preparar` escribiera, el orden preparar → decide → aplicar ya no
        salvaría nada: el efecto ya estaría hecho antes de preguntar.
        """
        from app.notas import agenda
        antes = len(agenda().tareas(limite=200))
        intents.preparar("pon una alarma mañana")
        intents.preparar("anota comprar café")
        self.assertEqual(antes, len(agenda().tareas(limite=200)),
                         "preparar() escribió algo")

    def test_aplicar_es_el_unico_que_escribe(self) -> None:
        plan = intents.preparar("pon una alarma mañana")
        self.assertIsNotNone(plan)
        antes = len(__import__("app.notas", fromlist=["x"]).agenda().tareas(limite=200))
        intents.aplicar(plan)
        despues = len(__import__("app.notas", fromlist=["x"]).agenda().tareas(limite=200))
        self.assertEqual(antes + 1, despues, "aplicar no escribió la alarma")


class TestDisenoDelModulo(unittest.TestCase):
    """Las propiedades que hacen que el router sea auditable."""

    def test_los_patrones_no_cuentan_el_orden_del_diccionario(self) -> None:
        """Ningún texto puede casar con dos intents.

        Si dos casaran, cuál gana lo decidiría el orden de la lista — que es un
        detalle de implementación, no una regla— y nadie podría explicar por qué
        un texto fue a un intent y no al otro.
        """
        from itertools import combinations
        for a, b in combinations(intents.INTENTS, 2):
            self.assertNotEqual(a.patron.pattern, b.patron.pattern,
                                f"'{a.nombre}' y '{b.nombre}' comparten patrón: "
                                "cuál gana dependería del orden")

    def test_los_intents_que_escriben_declaran_que_escriben(self) -> None:
        """Un intent que escribe sin `escribe=True` saltaría la puerta.

        El atributo es lo que hace que `/voces` lo pase por `autonomy.decide()`. Un
        intent de lectura con `escribe=True` es ruido; uno de escritura sin él es
        un agujero.
        """
        for intent in intents.INTENTS:
            if intent.escribe and not intent.tool:
                self.fail(f"'{intent.nombre}' escribe y no declara tool: "
                          "no se puede registrar en la traza ni en la puerta")
            if not intent.escribe and intent.clase != "T0":
                self.fail(f"'{intent.nombre}' no escribe pero no es T0: "
                          "una lectura que necesita modelo va por el modelo")

    def test_los_motivos_de_abstencion_no_son_errores_de_usuario(self) -> None:
        """Abstenerse es la respuesta correcta; no es un fallo que haya que avisar.

        Si `POST /voces` tratara una abstención como error, el móvil diría «error»
        cada vez que alguien preguntara algo que no reconoce, que es casi siempre.
        """
        r = intents.ejecutar("añade un test a autopilot")
        self.assertEqual("", r.clase)
        self.assertEqual("", r.texto, "una abstención no debe traer texto de error")

    def test_todos_los_intents_tienen_ayuda(self) -> None:
        """Cada intent declara para qué sirve. Es lo que se le dice al usuario."""
        for intent in intents.INTENTS:
            self.assertTrue(intent.ayuda, f"'{intent.nombre}' no explica su ayuda")


if __name__ == "__main__":
    unittest.main()

class TestElEndpointVoces(unittest.TestCase):
    """`POST /voces`: lo que el móvil y el portátil van a llamar.

    Lo que importa aquí es el **orden**: la puerta se consulta antes de que
    exista efecto. Eso no se puede comprobar mirando el resultado —el resultado
    es el mismo—, hay que mirar **si se escribió**.

    ## Dos decisiones de aislamiento
    - La llave va en la cabecera, como en `tests/test_autonomy.py`: la de `.env`
      está puesta, y un 401 no dice nada de `/voces`.
    - La agenda se apunta a un SQLite temporal. Estos tests **escriben** de
      verdad, y los que no escriben en la base real son los que un día rompen
      la agenda de alguien sin que nadie se entere.
    """

    def setUp(self) -> None:
        import tempfile
        from app import notas as notas_mod
        self.tmp_db = Path(tempfile.mkdtemp(prefix="aegis-voces-")) / "notas.sqlite3"
        real = notas_mod._AGENDA

        def _restaurar() -> None:
            notas_mod._AGENDA = real

        notas_mod._AGENDA = notas_mod.Agenda(self.tmp_db)
        self.addCleanup(_restaurar)

    def _client(self):
        from fastapi.testclient import TestClient
        from app import main as main_mod
        return TestClient(main_mod.app), {
            "X-Aegis-Token": main_mod.settings.aegis_api_key}

    def _tareas(self) -> int:
        from app.notas import agenda
        return len(agenda().tareas(limite=500))

    def test_una_hora_responde_y_dice_que_no_hubo_modelo(self) -> None:
        c, cab = self._client()
        r = c.post("/voces", json={"texto": "¿qué hora es?"}, headers=cab)
        self.assertEqual(200, r.status_code)
        d = r.json()
        self.assertEqual("T0", d["clase"])
        self.assertTrue(d["sin_modelo"])
        self.assertEqual("que_hora_es", d["intent"])
        self.assertEqual("", d["cae_a"])

    def test_lo_desconocido_cae_a_t1_y_no_es_error(self) -> None:
        """Abstenerse **no** es un error: es lo que pasa casi siempre."""
        c, cab = self._client()
        r = c.post("/voces", json={"texto": "añade un test a autopilot"}, headers=cab)
        self.assertEqual(200, r.status_code)
        d = r.json()
        self.assertEqual("", d["clase"])
        self.assertEqual("T1", d["cae_a"])

    def test_pide_token(self) -> None:
        """Puede escribir, así que cierra."""
        from fastapi.testclient import TestClient
        from app import main as main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        try:
            r = TestClient(main_mod.app).post("/voces", json={"texto": "qué hora es"})
            self.assertEqual(401, r.status_code)
        finally:
            main_mod.settings.aegis_api_key = original

    def test_la_puerta_se_consulta_ANTES_de_escribir(self) -> None:
        """La prueba del invariante. Con `decide` denegando, **no** se crea tarea.

        Un orden invertido devolvería la misma respuesta y habría creado la
        alarma, y eso es un fallo de seguridad que ningún test de «devuelve 200»
        caza. Por eso se mira la agenda y no la respuesta.
        """
        from unittest import mock
        c, cab = self._client()
        antes = self._tareas()
        denied = mock.Mock(ok=False)
        denied.motivo = "no tengo permiso para esto"
        denied.fin = None
        with mock.patch("app.autonomy.decide", return_value=denied) as decide:
            r = c.post("/voces", json={"texto": "pon una alarma mañana"}, headers=cab)
        self.assertEqual(200, r.status_code)
        d = r.json()
        self.assertTrue(d.get("bloqueado"), f"no avisó de que se bloqueó: {d}")
        self.assertIn("no tengo permiso", d["respuesta"])
        self.assertEqual(antes, self._tareas(),
                         "escribió DESPÉS de que la puerta lo negara")
        self.assertTrue(decide.called, "no consultó la puerta")

    def test_con_permiso_escribe(self) -> None:
        """El otro lado: si la puerta dice que sí, la alarma existe."""
        from unittest import mock
        c, cab = self._client()
        antes = self._tareas()
        allowed = mock.Mock(ok=True)
        allowed.motivo = ""
        allowed.fin = None
        with mock.patch("app.autonomy.decide", return_value=allowed):
            r = c.post("/voces", json={"texto": "pon una alarma mañana"}, headers=cab)
        self.assertEqual(200, r.status_code)
        d = r.json()
        self.assertEqual("T0", d["clase"])
        self.assertIn("Anotado para el", d["respuesta"])
        self.assertTrue(d["sin_modelo"])
        self.assertEqual(antes + 1, self._tareas(), "no creó la tarea")

    def test_el_texto_recibido_vuelve_para_caer_a_t1(self) -> None:
        """Si abstain, el cliente necesita el original para mandárselo al modelo.

        Sin esto cada cliente tiene que guardárselo, y dos clientes haciendo lo
        mismo de dos maneras es como se desincronizan.
        """
        c, cab = self._client()
        original = "añade un test a autopilot"
        d = c.post("/voces", json={"texto": original}, headers=cab).json()
        self.assertEqual(original, d["texto"])


class TestElVeredictoTravelaPorLaApi(unittest.TestCase):
    """El bug que estos tests cazan: el veredicto **no** llegaba al cliente.

    ## Qué había pasado
    `autopilot.run_autopilot` (el envoltorio) añadía `estado`, `completado`,
    `resumen` y `duracion_s` al dict. Funcionaba. En proceso, el test lo veía.

    Pero `POST /autopilot` declara `response_model=AutopilotOut`, y **Pydantic
    descarta lo que no está declarado**. El endpoint se comía los cuatro campos
    en silencio: en proceso el veredicto estaba, por HTTP no.

    Aguantó dos sesiones porque los tests de autopilot llaman a
    `run_autopilot` **directamente**, saltándose el endpoint. El wrapper estaba
    probado; el contrato de API no.

    ## La regla que sale de aquí
    Un `response_model` es una **filtro**. Añadir un campo al dict de dentro no
    lo añade a la respuesta, y ningún test que llame a la función de debajo se
    entera. Si el dato tiene que salir, hay que declararlo, y probarlo **por la
    ruta**.
    """

    def setUp(self) -> None:
        from app import main as main_mod
        self.main = main_mod

    def test_el_modelo_de_salida_declara_el_veredicto(self) -> None:
        """Lo más barato: que los campos estén declarados.

        Falla al añadir un campo al dict y olvidar el modelo, que es como pasó.
        """
        campos = set(self.main.AutopilotOut.model_fields)
        for campo in ("estado", "completado", "resumen", "duracion_s"):
            self.assertIn(campo, campos,
                          f"AutopilotOut no declara '{campo}': Pydantic lo "
                          "descartará de la respuesta aunque el dict lo traiga")

    def test_el_estado_also_declara_el_veredicto(self) -> None:
        """`/autopilot/{id}` es lo que el móvil consulta mientras corre.

        Si el veredicto no está en `AutopilotStatus`, el móvil ve el run
        terminar y no puede decir si terminó — que es lo que el veredicto vino a
        arreglar, y solo valdría por la ruta síncrona.
        """
        campos = set(self.main.AutopilotStatus.model_fields)
        for campo in ("estado", "completado", "resumen", "duracion_s"):
            self.assertIn(campo, campos,
                          f"AutopilotStatus no declara '{campo}'")

    def test_por_http_llega_el_veredicto(self) -> None:
        """Y el que de verdad lo prueba: por la ruta, no por la función."""
        from unittest import mock
        from fastapi.testclient import TestClient
        c = TestClient(self.main.app)
        cab = {"X-Aegis-Token": self.main.settings.aegis_api_key}

        resultado = {
            "model": "m", "answer": "hecho", "steps": 2,
            "trace": [{"step": 1, "tool": "projects_list", "ok": True}],
            "fin": "sin_tools",
            "estado": "completado", "completado": True,
            "resumen": "1 tool(s) en verde", "duracion_s": 12.5,
        }
        with mock.patch.object(self.main, "_run_autopilot_once",
                               mock.AsyncMock(return_value=resultado)):
            d = c.post("/autopilot", json={"prompt": "hola"}, headers=cab).json()
        self.assertEqual("completado", d["estado"])
        self.assertTrue(d["completado"])
        self.assertEqual(12.5, d["duracion_s"])
        self.assertEqual("1 tool(s) en verde", d["resumen"])

    def test_el_buffer_en_vivo_guarda_el_veredicto(self) -> None:
        """Lo quepoll-ea el móvil no puede perderlo.

        Un campo que viaja por la ruta síncrona y no por el buffer deja al
        cliente dependiendo de qué ruta use, y eso es la forma más difícil de
        cazar de una divergencia.
        """
        import inspect
        fuente = inspect.getsource(self.main.autopilot_status)
        for campo in ("estado", "duracion_s"):
            self.assertIn(campo, fuente,
                          f"_autopilot_status no lee '{campo}' del buffer")
        fuente_registro = inspect.getsource(self.main.autopilot_start)
        self.assertIn("estado=result.get", fuente_registro,
                      "el run no guarda el veredicto en _AUTOPILOT_RUNS")
