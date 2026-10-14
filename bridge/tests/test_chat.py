"""`POST /chat`: hablar con Aegis.

## Qué se decide aquí y por qué importa

El 2026-10-14, con este endpoint recién hecho y el 3B sin identidad en el prompt:

    «cuéntame qué puedes hacer»
      → «Puedo ayudarte con una amplia variedad de tareas relacionadas con la
         seguridad de la información y la protección de sistemas.»

    «revisa el repositorio aegis y dime si el verificador está en verde»
      → «Sigo revisando el repositorio de Aegis. Verificando… Está en verde.»

La segunda es **A-016 con otro traje**: afirmar un trabajo que no se ha hecho. En
el autopilot lo delata la traza, porque el veredicto se calcula de los pasos
realmente ejecutados. En una conversación **no hay traza**, así que el único sitio
donde se puede atajar es antes: que el modelo no tenga con qué mentir.

Y hay una segunda cosa que se midió y que este módulo fija:

| | primer token | total | ¿llamó a una tool? |
|---|---|---|---|
| 3B **sin** schema | 0,02 s | 0,17 s | no |
| 3B **con** el schema de 21 tools | — | 0,39 s | **siempre** |

Con el schema delante, un «hola, ¿qué tal?» produce una llamada a
`quien_eres_actualiza`. **El modelo no sabe cuándo no usar una herramienta**, así
que `/chat` no se lo pone delante y escala a T2 solo cuando T1 no dijo nada.

## Lo que estos tests NO comprueban
Que el modelo dé una respuesta buena. Eso no es un test: es una medición, y
cambia con el modelo. Aquí se comprueba lo que sí es una regla: que la
respuesta venga del código cuando tiene que, que no haya schema, y que la
escalada no se improvise.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main as main_mod  # noqa: E402


class _Cliente(unittest.TestCase):
    def setUp(self) -> None:
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        self.addCleanup(setattr, main_mod.settings, "aegis_api_key", original)
        self.c = TestClient(main_mod.app)
        self.cab = {"X-Aegis-Token": "clave-de-prueba"}

    def chat(self, texto: str, **extra) -> dict:
        r = self.c.post("/chat", json={"texto": texto, **extra}, headers=self.cab)
        self.assertEqual(200, r.status_code, r.text)
        return r.json()


class TestLosTresDestinos(_Cliente):
    def test_lo_que_casa_con_un_intent_no_gasta_modelo(self) -> None:
        """T0 no es «rápido»: es **cero**.

        Si este test falla porque `que_hora_es` tarda 200 ms, el camino rápido ha
        dejado de existir, y todo lo demás se ha ido con él.
        """
        with mock.patch.object(httpx, "AsyncClient",
                               side_effect=AssertionError("T0 no debe tocar el modelo")):
            d = self.chat("qué hora es")
        self.assertEqual("T0", d["clase"])
        self.assertTrue(d["respuesta"].strip())
        self.assertEqual("", d["modelo"])

    def test_una_charla_va_a_t1_sin_esquema_de_tools(self) -> None:
        """El schema NO va al chat, y es una decisión medida.

        Con el schema delante el modelo llama a una tool aunque no haga falta, y
        una tool que se llama sin querer se ejecuta o, peor, **se pide permiso**
        por algo que nadie pidió.
        """
        capturado = {}

        class _Stream:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                yield ('data: {"choices":[{"delta":{"content":"hola"}}]}')
                yield "data: [DONE]"
            def raise_for_status(self): return None

        class _Client:
            # `async with httpx.AsyncClient(...) as c` necesita que el cliente
            # tenga su propio __aenter__: sin él el test falla en el `async with`
            # y no llega a comprobar nada de lo que importa.
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            def stream(self, *a, **kw):
                capturado["json"] = kw.get("json") or {}
                return _Stream()

        with mock.patch.object(httpx, "AsyncClient", return_value=_Client()):
            d = self.chat("hola, ¿qué tal?")
        self.assertEqual("T1", d["clase"])
        self.assertNotIn("tools", capturado["json"],
                         "el chat manda el schema de tools: es lo que hace que "
                         "el modelo llame tools sin que haga falta")

    def test_que_puedes_hacer_no_gasta_modelo(self) -> None:
        """La frase más natural de todas.

        Antes de arreglar el patrón, «cuéntame qué puedes hacer» **no cogía**:
        el verbo de cortesía delante de la pregunta directa no estaba en el
        patrón, y la frase acababa en el modelo —que es justo el caso que este
        intent viene a resolver—. Cuesta 0,01 s en vez de un turno entero.
        """
        with mock.patch.object(httpx, "AsyncClient",
                               side_effect=AssertionError("debe contestar desde el código")):
            d = self.chat("cuéntame qué puedes hacer")
        self.assertEqual("T0", d["clase"])
        self.assertIn("Aegis", d["respuesta"])
        self.assertIn("herramienta", d["respuesta"].lower())


class TestLaIdentidadNoEsDelModelo(_Cliente):
    def test_el_prompt_lleva_la_identidad_y_la_lista_real(self) -> None:
        """El prompt se compone de piezas del código, todas.

        Es lo que impide lo medido: sin la lista real, el 3B contesta de memoria
        y se inventa tanto lo que sabe hacer como lo que ha hecho.
        """
        import inspect
        fuente = inspect.getsource(main_mod.chat)
        for pieza in ("identidad_para_el_prompt", "como_texto()",
                      "no has hecho nada"):
            self.assertIn(pieza, fuente, f"el prompt de chat no incluye {pieza}")

    def test_lo_que_puede_hacer_no_lo_dice_el_modelo(self) -> None:
        """La respuesta a «qué puedes hacer» se compara con el schema.

        Cada tool del schema tiene que aparecer en lo que Aegis contesta. Si
        aparece una que ya no existe, o falta una que sí, la lista está vieja y
        eso es peor que no tenerla.
        """
        from app.autopilot import allowed_tools
        d = self.chat("qué puedes hacer")
        for nombre in allowed_tools():
            with self.subTest(tool=nombre):
                self.assertIn(nombre, d["respuesta"])


class TestLaEscaladaNoSeImprovisa(_Cliente):
    def test_t1_que_no_dice_nada_escala_a_t2(self) -> None:
        """Silencio del modelo = trabajo, no = nada.

        Es el único caso en que `/chat` escala. Y escala **por silencio**, que es
        observable, no porque el modelo diga «déjame consultar X»: un modelo que
        decide por su cuenta que lo que oyó fue una orden es el fallo que ya se
        midió cuando pidió crear un proyecto que nadie le pidió.
        """
        class _Vacio:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                return
                yield  # pragma: no cover — hace la función un generador
            def raise_for_status(self): return None

        class _Client:
            def stream(self, *a, **kw): return _Vacio()

        with mock.patch.object(httpx, "AsyncClient", return_value=_Client()):
            d = self.chat("algo rarísimo que no se parece a nada")
        self.assertEqual("T2", d["clase"])
        self.assertTrue(d["escalado"])
        self.assertTrue(d["run_id"])

    def test_t0_nunca_escala(self) -> None:
        """Un intent que casa tiene su respuesta cerrada; no hay nada que escalar."""
        with mock.patch.object(httpx, "AsyncClient",
                               side_effect=AssertionError("T0 no toca el modelo")):
            d = self.chat("qué día es hoy")
        self.assertFalse(d["escalado"])
        self.assertEqual("", d["run_id"])


class TestElChatNoEscribe(unittest.TestCase):
    """`/chat` es una conversación. Si escribe, deja de serlo.

    No se prueba «no escribe» en general —eso lo prueba la puerta de
    `autonomy.decide`—, sino lo específico: que **este** endpoint no tiene
    ningún camino que escriba, ni siquiera un intent de escritura disfrazado.
    """

    def setUp(self) -> None:
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        self.addCleanup(setattr, main_mod.settings, "aegis_api_key", original)
        self.c = TestClient(main_mod.app)
        self.cab = {"X-Aegis-Token": "clave-de-prueba"}

    def test_un_intent_que_escribe_cae_al_modelo_no_se_ejecuta(self) -> None:
        """«pon una alarma» casa con un intent que escribe, y aquí no se ejecuta.

        `intents.preparar()` no distingue si escribe. Si `/chat` ejecutara eso,
        sería el único endpoint del repo que salta la puerta. La diferencia es
        que aquí **abstiene**: cae al modelo, que sí la tiene.
        """
        from app import notas
        with mock.patch.object(notas.Agenda, "tarea_crear") as crear:
            r = self.c.post("/chat", json={"texto": "pon una alarma mañana"},
                            headers=self.cab)
            self.assertEqual(200, r.status_code, r.text)
            # Con el modelo caído, T1 no dice nada y escala; lo que no puede pasar
            # es que la alarma se haya creado.
            if r.json().get("clase") == "T2":
                crear.assert_not_called()


if __name__ == "__main__":
    unittest.main()