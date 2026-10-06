"""La cola de aprobaciones: que no crezca y que lo viejo no se quede.

## Por qué estos dos tests existen
Porque el móvil acabó enseñando **31 tarjetas idénticas** de `ficha_write`, la
misma llamada 31 veces, sin que hubiera nada que decidir 31 veces. Y esa vez la
causa fue un test mío; pero el mecanismo que lo permitió es de producto y estaba
ahí antes:

`pedir()` inserta una fila con un uuid nuevo en cada llamada. Lo primero que hace
un agente al recibir un «no» es **reintentar lo mismo**, así que cada reintento
era una tarjeta más. La cola no tenía techo.

Un reintento se reconoce porque vuelve a ser **la misma decisión**: el mismo run,
la misma tool, los mismos argumentos. Eso es lo que se deduplica.

## Y lo otro: lo viejo caduca
Un OK que nadie contestó **es un «no»**. Y un «no» de hace tres días deja de ser
información: la situación que querías aprobar ya no existe. Se marca `caducada` en
vez de borrarse, porque el rastro importa.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.autonomy import _Almacen  # noqa: E402

ARGS = {"path": "ficha"}


class _AlmacenTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self.a = _Almacen(Path(tempfile.mkdtemp()) / "autonomia.sqlite3")

    def _envejecer(self, horas: float) -> None:
        """Adelanta el reloj de la base sin tocar el del proceso.

        Se escribe la fila con una `creado` antigua en vez de esperar: el test
        tarda segundos y la caducidad necesita días.
        """
        viejo = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.localtime(time.time() - horas * 3600))
        self.a._c.execute("UPDATE aprobaciones SET creado=?", (viejo,))
        self.a._c.commit()


class TestNoSeAcumulan(_AlmacenTemporal):
    def test_el_mismo_run_reintentando_no_duplica(self) -> None:
        """El caso real: 31 reintentos, 31 tarjetas.

        Lo primero que hace un agente al recibir un «no» es reintentar lo mismo.
        """
        ids = {self.a.pedir(run_id="r", paso=p, tool="ficha_write",
                           args=dict(ARGS), motivo="x") for p in range(1, 32)}
        self.assertEqual(1, len(ids), "31 reintentos produjeron 31 peticiones distintas")
        self.assertEqual(1, len(self.a.pendientes()))

    def test_el_paso_no_rompe_la_deduplicacion(self) -> None:
        """El paso cambia entre reintentos, y por eso no entra en la clave.

        Meterlo haría fallar la deduplicación justo en el caso que viene a
        arreglar, que es el que la sufre.
        """
        primero = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="")
        segundo = self.a.pedir(run_id="r", paso=7, tool="t", args=dict(ARGS), motivo="")
        self.assertEqual(primero, segundo)

    def test_el_orden_de_los_argumentos_no_cuenta(self) -> None:
        """`{"a":1,"b":2}` y `{"b":2,"a":1}` son la misma llamada.

        Sin `sort_keys`, un modelo que reordena las claves produce una fila más
        por reintento, y la deduplicación no se notice nunca.
        """
        p1 = self.a.pedir(run_id="r", paso=1, tool="t",
                          args={"a": 1, "b": 2}, motivo="")
        p2 = self.a.pedir(run_id="r", paso=1, tool="t",
                          args={"b": 2, "a": 1}, motivo="")
        self.assertEqual(p1, p2)

    def test_otros_runs_son_otra_decision(self) -> None:
        """Aprobar uno no debe aprobar el otro sin que te enteres.

        Dos runs pidiendo lo mismo se parecen, pero uno puede ser un reintento y
        otro un trabajo nuevo que quieres ver por separado. Deduplicar entre runs
        sería concesión de autoridad.
        """
        p1 = self.a.pedir(run_id="r1", paso=1, tool="t", args=dict(ARGS), motivo="")
        p2 = self.a.pedir(run_id="r2", paso=1, tool="t", args=dict(ARGS), motivo="")
        self.assertNotEqual(p1, p2)
        self.assertEqual(2, len(self.a.pendientes()))

    def test_una_denegada_no_se_reutiliza(self) -> None:
        """Denegar deja poder volver a preguntar.

        El motivo de una denegación se inyecta en el prompt del run siguiente
        para que Aegis corrija. Si la petición se reutilizara, después de un «no»
        no habría forma de volver a preguntar, y el motivo se volvería una
        prohibición permanente en vez de una corrección.
        """
        pid = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self.a.resolver(pid, "denegar")
        otra = self.a.pedir(run_id="r", paso=2, tool="t", args=dict(ARGS), motivo="x")
        self.assertNotEqual(pid, otra, "una denegada se está reutilizando")
        self.assertEqual(1, len(self.a.pendientes()))

    def test_una_caducada_no_se_reutiliza(self) -> None:
        pid = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(48)
        self.assertEqual([], self.a.pendientes())
        otra = self.a.pedir(run_id="r", paso=2, tool="t", args=dict(ARGS), motivo="x")
        self.assertNotEqual(pid, otra, "una caducada no es la misma decisión")

    def test_una_aprobada_no_se_reutiliza(self) -> None:
        """Una aprobación ya gastada es un permiso consumido, no una decisión
        pendiente. Reutilizarla firmaría un segundo permiso con una aprobación
        que ya se usó."""
        pid = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self.a.resolver(pid, "aprobar")
        otra = self.a.pedir(run_id="r", paso=2, tool="t", args=dict(ARGS), motivo="x")
        self.assertNotEqual(pid, otra)


class TestLoViejoCaduca(_AlmacenTemporal):
    def test_una_peticion_de_ayer_sigue_visible(self) -> None:
        self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(20)
        self.assertEqual(1, len(self.a.pendientes()),
                         "20 h no es «viejo»: la ventana es de 24")

    def test_una_peticion_de_hace_25_horas_caduca(self) -> None:
        """El límite son 24 h, y una hora de más cae.

        Se prueba justo al otro lado de la frontera porque una ventana de
        caducidad sin ese test es una ventana que nadie sabe si son 24 o 25.
        """
        self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(25)
        self.assertEqual([], self.a.pendientes())

    def test_a_la_vez_que_caduca_desaparece_de_la_lista(self) -> None:
        pid = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(48)
        self.assertEqual([], self.a.pendientes())

    def test_caducar_marca_y_no_borra(self) -> None:
        """El rastro se conserva: «se puede auditar» también vale para lo que no
        se hizo.

        Borrarlas sería más limpio de leer y perdería la respuesta a «¿por qué
        nunca instalaste esto?».
        """
        self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(48)
        self.a.caducar()
        filas = self.a._c.execute(
            "SELECT estado FROM aprobaciones").fetchall()
        self.assertEqual([("caducada",)], filas)

    def test_leer_es_lo_que_limpia(self) -> None:
        """No hay temporizador, y es a propósito.

        Un proceso que limpia cada hora es un proceso más que se puede parar mal.
        El retraso solo afecta a lo que **se ve**, que es justo lo que caduca.
        """
        self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self._envejecer(48)
        self.a.pendientes()
        # La segunda lectura ya está limpia aunque no se haya caducado a mano.
        self._envejecer(48)
        self.assertEqual([], self.a.pendientes())

    def test_caducar_no_toca_las_gastadas_ni_aprobadas(self) -> None:
        pid = self.a.pedir(run_id="r", paso=1, tool="t", args=dict(ARGS), motivo="x")
        self.a.resolver(pid, "aprobar")
        self._envejecer(48)
        self.a.caducar()
        estados = dict(self.a._c.execute(
            "SELECT estado, COUNT(*) FROM aprobaciones GROUP BY estado").fetchall())
        self.assertNotIn("caducada", estados,
                         "una aprobación consumida no es una decisión caducada")
        self.assertIn("aprobada", estados)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()