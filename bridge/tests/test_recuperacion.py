"""Lo que estaba en marcha cuando el proceso murió.

## El hueco que esto tapa

`_AUTOPILOT_RUNS` es un `dict` en memoria y `aegis-bridge.service` está en
`Restart=always`. Antes de esto, reiniciar el bridge **borraba todos los runs en
vuelo** sin dejar rastro: no había error, ni motivo, ni punto de corte. Y como el
JSONL se escribía entero **al terminar** con `open("w")`, un corte a mitad no
dejaba ni siquiera fichero.

La primera versión del arreglo fue «leer los JSONL al arrancar». Y es verdad que
la traza estaba en disco. Lo que no estaba —o no parecía— es el **estado**: si
aquel run estaba corriendo, y hasta dónde llegó. Un historial no sabe si su
último evento fue el final o una interrupción.

Por eso el escritor pasó a ser **append-only**: `task.created` al arrancar, cada
paso cuando termina, y el terminal al final. Un corte deja exactamente lo que se
alcanzó a hacer, y eso **es** el estado.

## Lo que estos tests comprueban

1. **Que el rastro sobrevive**, que es lo que hace el escritor.
2. **Que un run cortado se distingue de uno terminado**, y de uno que nunca
   existió. Sin eso no hay forma de decir que se perdió trabajo.
3. **Que nadie diga `running` después del reinicio.** La tarea no existe, y un
   cliente que espere a un `running` que no va a llegar espera para siempre.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.recuperacion import (FIN_INTERRUMPIDO, interrumpidos, recuperar)


def _jsonl(d: Path, nombre: str, *eventos) -> Path:
    ruta = d / nombre
    ruta.write_text("\n".join(json.dumps(e, ensure_ascii=False)
                              for e in eventos) + "\n", encoding="utf-8")
    return ruta


def _creado(run_id):
    return {"at": "x", "run_id": run_id, "event": "task.created",
            "agent": "autopilot", "payload": {"vivo": True}}


def _paso(run_id, tool, ok=True, step=1):
    return {"at": "x", "run_id": run_id, "event": "tool.completed",
            "agent": "autopilot", "payload": {"tool": tool, "ok": ok,
                                               "step": step}}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())


class TestUnRunCortado(Base):
    def setUp(self):
        super().setUp()
        _jsonl(self.d, "autopilot-cut.jsonl",
               _creado("autopilot-cut"),
               _paso("autopilot-cut", "repo_verify", step=1),
               _paso("autopilot-cut", "aegis_write_file", step=2))

    def test_se_recupera(self):
        r = recuperar(self.d)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["run_id"], "autopilot-cut")

    def test_no_dice_running(self):
        """La tarea de asyncio no existe tras el reinicio.

        Decir `running` haría que un cliente espere indefinidamente algo que ya
        no va a llegar: el peor modo de fallo posible en un endpoint de
        progreso, porque no da error.
        """
        self.assertEqual(recuperar(self.d)[0]["status"], "interrumpido")

    def test_sabe_hasta_donde_llego(self):
        r = recuperar(self.d)[0]
        self.assertEqual(r["steps"], 2)
        self.assertEqual([t["tool"] for t in r["trace"]],
                         ["repo_verify", "aegis_write_file"])

    def test_trae_veredicto_y_resumen(self):
        """Un `interrumpido` sin explicación es un estado que no dice nada."""
        r = recuperar(self.d)[0]
        self.assertEqual(r["estado"], "interrumpido")
        self.assertIn("2 paso(s)", r["resumen"])
        self.assertFalse(r["completado"])

    def test_esta_en_la_lista_de_interrumpidos(self):
        self.assertEqual(interrumpidos(recuperar(self.d)), ["autopilot-cut"])


class TestElSellado(Base):
    """El fichero se cierra en disco, o el histórico queda con runs huérfanos."""

    def test_un_run_sin_terminal_se_sella(self):
        _jsonl(self.d, "autopilot-cut.jsonl", _creado("autopilot-cut"),
               _paso("autopilot-cut", "repo_verify"))
        recuperar(self.d)
        lineas = (self.d / "autopilot-cut.jsonl").read_text(
            encoding="utf-8").strip().split("\n")
        eventos = [json.loads(l)["event"] for l in lineas]
        self.assertIn("task.failed", eventos)

    def test_el_sellado_dice_por_que(self):
        """Sin motivo, «interrumpido» y «reventado» son la misma palabra."""
        _jsonl(self.d, "autopilot-cut.jsonl", _creado("autopilot-cut"))
        recuperar(self.d)
        crudo = (self.d / "autopilot-cut.jsonl").read_text(encoding="utf-8")
        self.assertIn(FIN_INTERRUMPIDO, crudo)
        self.assertIn("reinició", crudo)

    def test_es_idempotente(self):
        """Recuperar dos veces no sella dos veces.

        Sin esto, cada arranque añadiría una línea de más y el run acabaría con
        cinco terminales, que es un historial que miente sobre su propia
        historia.
        """
        _jsonl(self.d, "autopilot-cut.jsonl", _creado("autopilot-cut"))
        recuperar(self.d)
        n1 = len((self.d / "autopilot-cut.jsonl").read_text(
            encoding="utf-8").strip().split("\n"))
        recuperar(self.d)
        recuperar(self.d)
        n2 = len((self.d / "autopilot-cut.jsonl").read_text(
            encoding="utf-8").strip().split("\n"))
        self.assertEqual(n1, n2)

    def test_se_puede_no_sellar(self):
        """`sellar=False` es el modo lectura, para tests e inspección."""
        _jsonl(self.d, "autopilot-cut.jsonl", _creado("autopilot-cut"))
        recuperar(self.d, sellar=False)
        crudo = (self.d / "autopilot-cut.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(FIN_INTERRUMPIDO, crudo)


class TestUnRunTerminado(Base):
    def setUp(self):
        super().setUp()
        _jsonl(self.d, "autopilot-ok.jsonl",
               _creado("autopilot-ok"),
               _paso("autopilot-ok", "repo_verify"),
               {"at": "x", "run_id": "autopilot-ok", "event": "task.done",
                "agent": "autopilot",
                "payload": {"fin": "sin_tools", "answer": "listo",
                            "estado": "completado", "completado": True}})

    def test_recupera_su_veredicto(self):
        r = recuperar(self.d)[0]
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["fin"], "sin_tools")
        self.assertEqual(r["estado"], "completado")
        self.assertTrue(r["completado"])
        self.assertEqual(r["answer"], "listo")

    def test_no_lo_cuenta_como_interrumpido(self):
        self.assertEqual(interrumpidos(recuperar(self.d)), [])

    def test_no_lo_resella(self):
        crudo = (self.d / "autopilot-ok.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(FIN_INTERRUMPIDO, crudo)

    def test_el_veredicto_del_terminal_manda(self):
        """Lo calculó el run real con la traza entera; recalcularlo daría otro.

        El terminal se respeta aunque no cuadre con lo que saldría de la traza
        recortada, porque un run que terminó bien se cuenta como terminó.
        """
        _jsonl(self.d, "autopilot-x.jsonl",
               _creado("autopilot-x"),
               _paso("autopilot-x", "repo_verify"),
               {"at": "x", "run_id": "autopilot-x", "event": "task.done",
                "agent": "autopilot",
                "payload": {"fin": "sin_tools", "answer": "listo",
                            "estado": "completado", "completado": True,
                            "resumen": "el de verdad"}})
        r = [x for x in recuperar(self.d) if x["run_id"] == "autopilot-x"][0]
        self.assertEqual(r["resumen"], "el de verdad")


class TestRobustez(Base):
    def test_una_linea_corrupta_no_impide_recuperar(self):
        ruta = self.d / "autopilot-cut.jsonl"
        ruta.write_text(
            json.dumps(_creado("autopilot-cut")) + "\n"
            "{esto no es json\n"
            + json.dumps(_paso("autopilot-cut", "repo_verify")) + "\n",
            encoding="utf-8")
        r = recuperar(self.d)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["steps"], 1)

    def test_un_fichero_vacio_no_devuelve_nada(self):
        (self.d / "autopilot-vacio.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(recuperar(self.d), [])

    def test_un_directorio_que_no_existe(self):
        self.assertEqual(recuperar(self.d / "nada"), [])

    def test_ignora_los_runs_de_hermes(self):
        """Son de otro motor y su `steps` es otra cosa.

        Si se mezclaran, el `status` mentiría sobre runs que nadie escribió con
        este formato.
        """
        _jsonl(self.d, "run-hermes.jsonl",
               {"event": "task.done", "payload": {"fin": "sin_tools"}})
        self.assertEqual(recuperar(self.d), [])
        self.assertEqual(len(recuperar(self.d, solo_autopilot=False)), 1)

    def test_el_mas_reciente_gana(self):
        """Si hay más de los que caben, se conservan los últimos.

        La mejor forma de no perder trabajo es empezar por el más reciente: un
        run de hace tres meses no se va a retomar, y uno de hace diez segundos
        puede que sí.
        """
        import os
        import time
        for i in range(5):
            ruta = _jsonl(self.d, f"autopilot-{i}.jsonl",
                          _creado(f"autopilot-{i}"))
            t = time.time() - (5 - i) * 60
            os.utime(ruta, (t, t))
        r = recuperar(self.d, maximo=2)
        self.assertEqual([x["run_id"] for x in r], ["autopilot-4", "autopilot-3"])


if __name__ == "__main__":
    unittest.main()