"""¿Está Aegis hablando? Un reloj, y hay que probarlo como reloj."""

import time
import unittest

from app import actividad


class TestActividad(unittest.TestCase):
    def setUp(self) -> None:
        actividad.limpiar()

    def tearDown(self) -> None:
        actividad.limpiar()

    def test_reposo_si_nunca_habló(self) -> None:
        self.assertFalse(actividad.estado()["hablando"])

    def test_habla_despues_de_una_frase(self) -> None:
        actividad.marcar("hermes", "run-1")
        e = actividad.estado()
        self.assertTrue(e["hablando"])
        self.assertEqual(e["que"], "hermes")
        self.assertEqual(e["run"], "run-1")

    def test_se_apaga_al_callar(self) -> None:
        """El caso que hace que esto valga: la ventana es corta a propósito."""
        actividad.marcar("hermes")
        with mock_edad(actividad.VENTANA_S + 0.1):
            self.assertFalse(actividad.estado()["hablando"])

    def test_justo_antes_de_apagarse_sigue_hablando(self) -> None:
        """La ventana es un umbral, no un salto."""
        actividad.marcar("hermes")
        with mock_edad(actividad.VENTANA_S - 0.1):
            self.assertTrue(actividad.estado()["hablando"])

    def test_al_apagarse_olvida_quien_hablaba(self) -> None:
        """Cuando ya no habla, `que` y `run` se vacían.

        Si no, la app puede seguir enseñando «hablando: autopilot» con el
        semáforo apagado, y eso es un indicador que se contradice.
        """
        actividad.marcar("autopilot", "run-9")
        with mock_edad(actividad.VENTANA_S + 0.1):
            e = actividad.estado()
        self.assertEqual(e["que"], "")
        self.assertEqual(e["run"], "")

    def test_una_frase_nueva_reinicia_el_reloj(self) -> None:
        """Dos deltas separados siguen siendo una frase, no dos hubs."""
        actividad.marcar("hermes")
        with mock_edad(actividad.VENTANA_S - 0.5):
            actividad.marcar("hermes")   # llega otro delta
        self.assertTrue(actividad.estado()["hablando"])

    def test_no_parte_de_cero_al_reiniciar_el_bridge(self) -> None:
        """La señal es de este momento: si el bridge no vive, nadie habla."""
        self.assertEqual(actividad.estado()["hace_s"], -1)


class mock_edad:
    """Envejece el reloj del módulo sin dormir de verdad.

    `time.sleep` en un test son 2,5 segundos reales por caso, y lo que se prueba
    es una comparación, no una espera.
    """

    def __init__(self, segundos: float) -> None:
        self.segundos = segundos

    def __enter__(self):
        self._real = time.time
        # El reloj avanza, no retrocede. `estado()` resta `ahora - ts`, así que
        # para que la frase parezca vieja hay que mover `ahora` hacia delante.
        # Con el signo al revés, la edad sale negativa y el módulo decide que
        # acaba de hablar: el test pasa por lo contrario de lo que dice.
        self._offset = self.segundos
        actividad.time.time = lambda: self._real() + self._offset
        return self

    def __exit__(self, *_):
        actividad.time.time = self._real
        return False
