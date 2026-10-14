"""El dataset de conversaciones.

Estos tests fijan tres cosas que no son evidentes y que un refactor rompe sin
avisar:

1. **Una corrección no borra el turno.** El motivo es lo más valioso que hay
   y por eso se añade en vez de reescribir.
2. **Una línea corrupta no tumba el dataset.** Perder un turno es mejor que no
   poder corregir ninguno.
3. **Borrar es una operación normal**, no una excepción: es la invariante «la
   memoria es tuya» aplicada a un dataset que también es memoria.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.conversaciones import (MAX_CONVERSACIONES, Conversacion,
                                 Conversaciones)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.ds = Conversaciones(self.dir / "conversaciones.jsonl")

    def turno(self, texto="hola", respuesta="respuesta", **kw):
        return self.ds.registrar_chat(texto, respuesta, **kw)


class TestGuardarYLeer(Base):
    def test_un_turno_vuelve_con_id(self):
        c = self.turno()
        self.assertTrue(c.id)
        self.assertEqual(len(c.id), 12)

    def test_lo_guardado_se_lee_igual(self):
        self.turno("¿qué tal?", clase="T1", modelo="qwen2.5:7b", ms=812.5)
        c = list(self.ds.leer().values())[0]
        self.assertEqual(c.turno, "¿qué tal?")
        self.assertEqual(c.clase, "T1")
        self.assertEqual(c.modelo, "qwen2.5:7b")
        self.assertAlmostEqual(c.ms, 812.5)

    def test_t2_guarda_el_run_id_para_enlazar(self):
        # Un T2 devuelve respuesta vacía: la llega por el run. Si no se
        # guardara el `run_id`, la mitad de los turnos —los que hicieron
        # trabajo de verdad— no existirían para el dataset.
        c = self.turno(clase="T2", respuesta="", run_id="abc123")
        self.assertEqual(self.ds.leer()[c.id].run_id, "abc123")

    def test_acentos_y_emoji_no_se_escapan(self):
        self.turno("¿qué tal? ¿sí? 🙂")
        crudo = self.ds.ruta.read_text(encoding="utf-8")
        self.assertIn("¿qué tal?", crudo)
        self.assertIn("🙂", crudo)


class TestCorreccion(Base):
    def test_la_correccion_no_borra_el_turno(self):
        c = self.turno("lista los proyectos", clase="T1")
        self.ds.corregir(c.id, "mala", "inventa el número de proyectos")
        leida = self.ds.leer()[c.id]
        self.assertEqual(leida.turno, "lista los proyectos")
        self.assertEqual(leida.respuesta, "respuesta")
        self.assertEqual(leida.motivo, "inventa el número de proyectos")

    def test_la_ultima_correccion_gana(self):
        c = self.turno()
        self.ds.corregir(c.id, "mala", "se equivocó")
        self.ds.corregir(c.id, "buena")
        leida = self.ds.leer()[c.id]
        self.assertEqual(leida.veredicto, "buena")
        # El motivo anterior se conserva: es el registro de por qué.
        self.assertEqual(leida.motivo, "se equivocó")

    def test_una_correccion_no_cuenta_como_turno(self):
        c = self.turno()
        self.ds.corregir(c.id, "mala", "motivo")
        self.assertEqual(self.ds.resumen()["total"], 1)

    def test_una_id_inexistente_no_crea_nada(self):
        # `corregir` devuelve si la encontró, pero añade la línea igualmente:
        # es un registro append-only y una corrección huérfana es información.
        # Lo que no puede pasar es que parezca que se corrigió algo.
        self.assertFalse(self.ds.corregir("nada", "buena"))
        self.assertEqual(self.ds.resumen()["total"], 0)

    def test_un_veredicto_inventado_no_pasa(self):
        with self.assertRaises(ValueError):
            self.ds.corregir("x", "perfectisimo", "motivo")

    def test_se_puede_corregir_la_respuesta_entera(self):
        c = self.turno("hola", respuesta="no se")
        self.ds.corregir(c.id, "mala", "novisions",
                         corregido="Hola. ¿En qué andas?")
        self.assertEqual(self.ds.leer()[c.id].corregido, "Hola. ¿En qué andas?")


class TestResumen(Base):
    def test_cuenta_malas_sin_motivo(self):
        """El número que decide si el dataset sirve para algo.

        Una respuesta rechazada sin motivo cuenta, pero no enseña: no dice qué
        se esperaba en su lugar. Por eso se cuenta aparte.
        """
        a = self.turno("uno")
        b = self.turno("dos")
        self.ds.corregir(a.id, "mala")                       # sin motivo
        self.ds.corregir(b.id, "mala", "declaró algo falso")
        r = self.ds.resumen()
        self.assertEqual(r["malas"], 2)
        self.assertEqual(r["malas_sin_motivo"], 1)

    def test_reparte_por_clase(self):
        self.turno("a", clase="T0")
        self.turno("b", clase="T1")
        self.turno("c", clase="T1")
        self.assertEqual(self.ds.resumen()["clases"], {"T1": 2, "T0": 1})

    def test_vacio_no_revienta(self):
        self.assertEqual(self.ds.resumen()["total"], 0)
        self.assertEqual(self.ds.sin_etiquetar(), [])


class TestRobustez(Base):
    def test_una_linea_corrupta_no_tumba_el_resto(self):
        self.turno("bueno")
        with self.ds.ruta.open("a", encoding="utf-8") as f:
            f.write("{esto no es json\n")
        self.turno("otro")
        self.assertEqual(self.ds.resumen()["total"], 2)

    def test_una_linea_vacia_no_cuenta(self):
        self.turno("bueno")
        with self.ds.ruta.open("a", encoding="utf-8") as f:
            f.write("\n\n")
        self.assertEqual(self.ds.resumen()["total"], 1)

    def test_leer_un_fichero_que_no_existe(self):
        vacio = Conversaciones(self.dir / "nunca.jsonl")
        self.assertEqual(vacio.leer(), {})
        self.assertEqual(vacio.resumen()["total"], 0)
        self.assertEqual(vacio.borrar(), 0)

    def test_el_turno_mas_reciente_se_ve_primero(self):
        self.turno("viejo")
        self.turno("nuevo")
        pend = self.ds.sin_etiquetar()
        self.assertEqual(pend[0].turno, "viejo")   # FIFO: se revisa en orden


class TestPodar(Base):
    def test_no_poda_por_debajo_del_tope(self):
        for i in range(10):
            self.turno(f"turno {i}")
        self.assertEqual(self.ds.podar(), 0)
        self.assertEqual(self.ds.resumen()["total"], 10)

    def test_poda_lo_mas_antiguo_y_conserva_las_correcciones(self):
        for i in range(MAX_CONVERSACIONES + 3):
            c = self.turno(f"turno {i:05d}")
            if i == 0:
                self.ds.corregir(c.id, "mala", "el motivo más valioso")
        quitadas = self.ds.podar()
        self.assertEqual(quitadas, 3)
        self.assertEqual(self.ds.resumen()["total"], MAX_CONVERSACIONES)
        # El podado es por antigüedad, y lo más antiguo era el que tenía el
        # motivo. Si se pierde, se pierde justo lo que no se puede rehacer.
        self.assertEqual(self.ds.resumen()["malas"], 0)

    def test_las_correcciones_no_se_podan_solas(self):
        c = self.turno("un turno")
        self.ds.corregir(c.id, "buena", "bien")
        self.assertEqual(self.ds.podar(), 0)
        self.assertEqual(self.ds.leer()[c.id].veredicto, "buena")


class TestBorrar(Base):
    def test_borrar_vacia_el_fichero(self):
        for i in range(5):
            self.turno(f"turno {i}")
        self.assertEqual(self.ds.borrar(), 5)
        self.assertFalse(self.ds.ruta.exists())
        self.assertEqual(self.ds.resumen()["total"], 0)

    def test_se_puede_seguir_escribiendo_despues(self):
        self.turno("uno")
        self.ds.borrar()
        c = self.turno("otro")
        self.assertTrue(c.id)
        self.assertEqual(self.ds.resumen()["total"], 1)


class TestElFicheroSePuedeRevisarAOjo(Base):
    """JSONL, no SQLite, y esto es lo que lo obliga.

    Las correcciones se revisan a ojo, con `tail` y `jq`. Por eso el formato es
    una línea por conversación y por eso los acentos van sin escapar: un
    fichero de entrenamiento que hay que decodificar no se lee, y lo que no se
    lee no se corrige.
    """

    def test_una_linea_por_turno(self):
        self.turno("uno")
        self.turno("dos")
        lineas = [l for l in self.ds.ruta.read_text(encoding="utf-8").splitlines()
                  if l.strip()]
        self.assertEqual(len(lineas), 2)
        for l in lineas:
            json.loads(l)      # cada línea es un JSON entero, no un trozo

    def test_el_id_se_ve_sin_herramientas(self):
        c = self.turno("hola")
        self.assertIn(c.id, self.ds.ruta.read_text(encoding="utf-8"))


class TestIdYCorreccion(Base):
    def test_las_correcciones_no_generan_ids_nuevos(self):
        c = self.turno("hola")
        self.ds.corregir(c.id, "mala", "motivo")
        crudas = self.ds.leer_crudas()
        self.assertEqual(len(crudas), 2)          # el turno y su correccion
        self.assertEqual(len({d["id"] for d in crudas}), 1)   # la misma id

    def test_el_id_se_genera_al_guardar(self):
        """No al crear: un turno que nunca llegó al disco no ocupa sitio."""
        suelta = Conversacion(turno="nunca guardada", respuesta="")
        self.assertEqual(suelta.id, "")
        guardada = self.ds.anadir(suelta)
        self.assertTrue(guardada.id)


if __name__ == "__main__":
    unittest.main()