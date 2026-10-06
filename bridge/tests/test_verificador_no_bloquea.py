"""La puerta de verificación no puede congelar el bridge.

## Qué pasó
`verifier.gate` es una corrutina `async def`, pero dentro llamaba a `ejecutar(...)`
—que es `subprocess.run` con `timeout=900`— **directamente**. El comando declarado
de `portafolio` es `tsc --noEmit` / `vitest run`, o sea minutos. En el event loop,
eso congela el bridge entero: `/health` no responde, el poll del móvil se queda
colgado, y `POST /autopilot/{run_id}/stop` no se atiende hasta que la verificación
termina.

Es decir: **parar un run durante su propia verificación era imposible**. Y no por
una decisión de diseño, sino por una línea sin envolver —justo el tipo de cosa que
`autopilot._bucle` ya había resuelto para las tools (con un comentario que
explica el porqué) y que aquí se quedó sin hacer.

## Cómo se comprueba que no vuelve a pasar
No midiendo el subprocess: midiendo **el loop**. Se pone un comando lento de
verdad y, mientras corre, se intenta responder otra cosa en la misma vuelta del
event loop. Si la puerta bloquea, esa otra cosa no se atiende y el test falla.
Es la forma de probar un congelamiento: no su ausencia, sino su presencia
detectada.
"""
import asyncio
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import verifier  # noqa: E402


def _veridicto_que_mira_si_el_loop_vivia(al_final):
    """Un `ejecutar` lento que **anota si el event loop estaba vivo** mientras él.

    Se planta un canario: una tarea del loop que duerme un poco y levanta un
    `threading.Event`. Si la puerta ejecuta el verificador en un hilo, el loop
    queda libre, el canario corre y el evento está levantado cuando el
    verificador termina. Si lo ejecuta en el loop, **el canario no puede correr
    hasta que todo haya acabado**, y el evento sigue sin levantar.

    Por eso el canario usa `threading.Event` y no una lista: es un dato que se
    puede leer desde otro hilo, que es justo desde donde lo lee el verificador.
    """
    import threading
    evento = threading.Event()

    def _f(proyecto, what):
        for _ in range(20):
            time.sleep(0.01)
        al_final.append(evento.is_set())
        return verifier.Verdict(ok=True, what=what, proyecto=proyecto,
                                exit_code=0, resumen="tarde", ms=200)

    _f._evento = evento
    return _f


class TestLaPuertaNoBloqueaElLoop(unittest.TestCase):
    def _gate_con_verificador(self, lento, alias="aegis"):
        with mock.patch.object(verifier, "ejecutar", lento):
            return verifier.gate(alias, "check")

    def test_el_loop_vivia_mientras_verifica(self):
        """La prueba del congelamiento, y es determinista.

        Un test que solo mira si "el loop respondió antes de tiempo" no vale:
        aunque el loop esté congelado, el orden de las marcas sale igual, porque
        todo se ejecuta en fila. Lo que sí distingue los dos casos es **si el
        canario pudo correr mientras el verificador esperaba**.
        """
        visto: list[bool] = []
        lento = _veridicto_que_mira_si_el_loop_vivia(visto)

        async def _escena():
            with mock.patch.object(verifier, "ejecutar", lento):
                gate = verifier.gate("aegis", "check")
                tarea = asyncio.create_task(
                    gate(1, "aegis_write_file", {"path": "x"}, "escrito"))

                async def _canario():
                    await asyncio.sleep(0.03)
                    lento._evento.set()

                asyncio.create_task(_canario())
                return await tarea

        veredicto = asyncio.run(_escena())
        self.assertEqual([True], visto,
                         "el event loop estaba bloqueado mientras corria el "
                         "verificador: /health, /actividad y /autopilot/{id}/stop "
                         "no se atendian")
        self.assertIsNotNone(veredicto, "la puerta no devolvio veredicto")
        self.assertTrue(veredicto.get("ok"))

    def test_una_tool_que_no_escribe_no_verifica(self):
        """Solo las herramientas que escriben pasan por la puerta. Una lectura no
        puede costing un `tsc` entero."""
        gate = self._gate_con_verificador(
            mock.Mock(side_effect=AssertionError("no deberia verificar")))
        r = asyncio.run(gate(1, "aegis_read_file", {"path": "x"}, "leido"))
        self.assertIsNone(r)

    def test_el_shell_va_a_un_hilo(self):
        """Guardarraíl estructural, para que no dependa del timing del test.

        Un test de temporización puede pasar por suerte si el reloj va rápido. Este
        no puede: mira **dónde** se llama `ejecutar`, que es la pregunta real.
        """
        import ast
        import inspect
        import textwrap

        cuerpo = ast.parse(textwrap.dedent(inspect.getsource(verifier.gate)))
        llamadas_directas = [
            n for n in ast.walk(cuerpo)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "ejecutar"
        ]
        self.assertEqual([], llamadas_directas,
                         "gate() volvio a llamar a ejecutar() en el event loop: "
                         "eso congela el bridge entero durante la verificacion")


if __name__ == "__main__":
    unittest.main()