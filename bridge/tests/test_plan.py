"""El objeto que hoy no existía: lo que Aegis está trabajando.

## El por qué, que es un número

Sobre 500 prompts reales del usuario, medidos el 2026-10-14:

    'procede'   -> (no casa con ningún intent)
    'continua'  -> (no casa con ningún intent)

**El 19 % de los prompts reales no llegaba a ningún sitio.** Caía a T1 —el
modelo sin herramientas— y el modelo no tenía con qué continuar, porque no
existía el objeto «lo que Aegis está trabajando ahora». No estaba en `intents`, no
estaba en la cola de aprobaciones, que es por *tool*, y no estaba en `tareas`,
que tiene estado pero **no tiene prioridad**.

Estos tests fijan ese objeto. Y fijan sobre todo sus portes, porque un plan sin
puertas es un plan del que se puede decir cualquier cosa.
"""

import tempfile
import unittest
from pathlib import Path

from app.plan import (OCUPAN, PRIORIDAD_POR_DEFECTO, Planes, PlanError)


class Base(unittest.TestCase):
    def setUp(self):
        self.ps = Planes(Path(tempfile.mkdtemp()) / "planes.sqlite3")

    def plan(self, objetivo="arreglar el verificador", **kw):
        return self.ps.crear(objetivo, **kw)


class TestCrear(Base):
    def test_un_plan_nace_en_cola_y_no_se_toca(self):
        p = self.plan()
        self.assertEqual(p["estado"], "en_cola")
        self.assertEqual(p["run_id"], "")
        self.assertEqual(p["cierre"], "")
        self.assertIsNone(self.ps.en_curso())

    def test_la_prioridad_por_defecto_no_desplaza_a_nadie(self):
        """El 50 es neutro a propósito.

        Un plan nuevo sin prioridad **no** saca al que está corriendo. Si lo
        sacara, cualquier plan nuevo interrumpiría el trabajo en curso, y el
        efecto sería Aegis nunca terminando nada.
        """
        self.assertEqual(PRIORIDAD_POR_DEFECTO, 50)
        en_curso = self.plan(prioridad=50)
        self.ps.tomar(en_curso["id"])
        nuevo = self.plan()
        self.assertFalse(self.ps.prioritario_sobre(nuevo["id"]))

    def test_un_plan_sin_objetivo_no_se_crea(self):
        with self.assertRaises(PlanError):
            self.plan("   ")

    def test_una_prioridad_fuera_de_rango_no_se_crea(self):
        for mala in (-1, 101, 999):
            with self.subTest(prioridad=mala):
                with self.assertRaises(PlanError):
                    self.plan(prioridad=mala)

    def test_los_criterios_van_guardados(self):
        p = self.plan(criterios=["la suite pasa", "cero issues nuevos"])
        self.assertEqual(self.ps.plan(p["id"])["criterios"],
                         ["la suite pasa", "cero issues nuevos"])


class TestSoloUnoEnCurso(Base):
    """La regla que hace posible decir «esto se replanifica»."""

    def test_tomar_suelta_al_que_habia(self):
        a = self.plan("el primero")
        b = self.plan("el segundo")
        self.ps.tomar(a["id"])
        tomado = self.ps.tomar(b["id"])
        self.assertEqual(self.ps.en_curso()["id"], b["id"])
        self.assertEqual(tomado["sustituido"], a["id"])
        self.assertEqual(tomado["sustituido_objetivo"], "el primero")

    def test_el_desplazado_vuelve_a_la_cola_no_se_pierde(self):
        """Abandonar no es cancelar.

        El plan desplazado conserva su prioridad y vuelve a `en_cola`. Si se
        perdiera, «Aegis ha reformulado» sería en realidad «Aegis ha
        olvidado», que es una pérdida de trabajo escondida detrás de una
        decisión.
        """
        a = self.plan("el primero", prioridad=30)
        b = self.plan("el segundo", prioridad=90)
        self.ps.tomar(a["id"])
        self.ps.tomar(b["id"])
        vuelto = self.ps.plan(a["id"])
        self.assertEqual(vuelto["estado"], "en_cola")
        self.assertEqual(vuelto["prioridad"], 30)

    def test_tomar_el_que_ya_esta_en_curso_no_lo_sustituye(self):
        a = self.plan()
        self.ps.tomar(a["id"])
        otra = self.ps.tomar(a["id"])
        self.assertIsNone(otra["sustituido"])
        self.assertEqual(self.ps.en_curso()["id"], a["id"])

    def test_tomar_un_plan_que_no_se_puede_tomar(self):
        p = self.plan()
        self.ps.tomar(p["id"])
        self.ps.bloquear(p["id"], "no puedo")
        with self.assertRaises(PlanError):
            self.ps.tomar(p["id"])

    def test_tomar_un_plan_inexistente(self):
        with self.assertRaises(PlanError):
            self.ps.tomar("plan-no-existe")


class TestPrioridad(Base):
    def test_mayor_prioridad_desplaza(self):
        bajo = self.plan("lo de antes", prioridad=20)
        alto = self.plan("lo nuevo", prioridad=90)
        self.ps.tomar(bajo["id"])
        self.assertTrue(self.ps.prioritario_sobre(alto["id"]))

    def test_igual_prioridad_no_desplaza(self):
        """A igual prioridad, el que corre sigue.

        Con `>=` cualquier plan nuevo sacaría al que está trabajando, y el
        efecto sería que Aegis no termina nada: siempre empezando.
        """
        a = self.plan("el primero", prioridad=60)
        b = self.plan("el segundo", prioridad=60)
        self.ps.tomar(a["id"])
        self.assertFalse(self.ps.prioritario_sobre(b["id"]))

    def test_menor_prioridad_no_desplaza(self):
        alto = self.plan("importante", prioridad=90)
        bajo = self.plan("urgente de verdad no", prioridad=10)
        self.ps.tomar(alto["id"])
        self.assertFalse(self.ps.prioritario_sobre(bajo["id"]))

    def test_nada_desplaza_sin_plan_en_curso(self):
        a = self.plan("solo")
        b = self.plan("otro", prioridad=99)
        self.assertFalse(self.ps.prioritario_sobre(b["id"]))

    def test_un_plan_no_se_desplaza_a_si_mismo(self):
        a = self.plan("solo", prioridad=99)
        self.ps.tomar(a["id"])
        self.assertFalse(self.ps.prioritario_sobre(a["id"]))


class TestOrdenDeCola(Base):
    def test_el_siguiente_es_el_de_mas_prioridad(self):
        self.plan("bajo", prioridad=10)
        self.plan("alto", prioridad=90)
        self.plan("medio", prioridad=50)
        self.assertEqual(self.ps.siguiente()["objetivo"], "alto")

    def test_a_igual_prioridad_manda_la_antiguedad(self):
        self.plan("primero", prioridad=70)
        self.plan("segundo", prioridad=70)
        self.assertEqual(self.ps.siguiente()["objetivo"], "primero")

    def test_el_en_curso_va_primero_en_la_lista(self):
        self.plan("encolado", prioridad=99)
        corriendo = self.plan("corriendo", prioridad=1)
        self.ps.tomar(corriendo["id"])
        self.assertEqual(self.ps.planes()[0]["id"], corriendo["id"])

    def test_el_siguiente_no_es_el_que_ya_corre(self):
        corriendo = self.plan("corriendo", prioridad=99)
        self.ps.tomar(corriendo["id"])
        self.plan("encolado", prioridad=10)
        self.assertEqual(self.ps.siguiente()["objetivo"], "encolado")

    def test_sin_cola_no_hay_siguiente(self):
        self.assertIsNone(self.ps.siguiente())


class TestCerrar(Base):
    """`cerrado` sin evidencia no es un estado: es una palabra."""

    def test_cerrar_sin_cierre_no_deja(self):
        p = self.plan()
        self.ps.tomar(p["id"])
        with self.assertRaises(PlanError):
            self.ps.cerrar(p["id"], cierre="")
        self.assertEqual(self.ps.plan(p["id"])["estado"], "en_curso")

    def test_cerrar_con_cierre_anota_el_enlace(self):
        p = self.plan()
        self.ps.tomar(p["id"])
        cerrado = self.ps.cerrar(p["id"], cierre="cierre-abc")
        self.assertEqual(cerrado["estado"], "cerrado")
        self.assertEqual(cerrado["cierre"], "cierre-abc")


class TestBloquear(Base):
    def test_bloquear_sin_motivo_no_deja(self):
        """Un bloqueo sin explicación es un plan perdido con otro nombre."""
        p = self.plan()
        self.ps.tomar(p["id"])
        with self.assertRaises(PlanError):
            self.ps.bloquear(p["id"], "   ")
        self.assertEqual(self.ps.plan(p["id"])["estado"], "en_curso")

    def test_bloquear_libera_la_plaza(self):
        """Si no, el siguiente plan no empezaría nunca."""
        a = self.plan("atascado")
        b = self.plan("el que sigue")
        self.ps.tomar(a["id"])
        self.ps.bloquear(a["id"], "necesita una respuesta del cliente")
        self.assertIsNone(self.ps.en_curso())
        self.assertEqual(self.ps.siguiente()["objetivo"], "el que sigue")

    def test_el_motivo_queda_guardado(self):
        p = self.plan()
        self.ps.bloquear(p["id"], "falta el OK del despliegue")
        self.assertEqual(self.ps.plan(p["id"])["reformula_motivo"],
                         "falta el OK del despliegue")


class TestReformular(Base):
    def test_reformular_sin_motivo_no_deja(self):
        p = self.plan()
        with self.assertRaises(PlanError):
            self.ps.reformular(p["id"], nuevo_objetivo="otro", motivo="")

    def test_reformular_sin_objetivo_no_deja(self):
        p = self.plan()
        with self.assertRaises(PlanError):
            self.ps.reformular(p["id"], nuevo_objetivo="  ", motivo="porque sí")

    def test_reformular_en_curso_no_lo_interrumpe(self):
        """El bug que se encontró probando esto: reformular **paraba** el plan.

        Pedir «procede, y además X» sobre un plan en curso reformulaba el
        objetivo y de paso le ponía `reformulado`, que saca de `en_curso`, y con
        ello liberaba la plaza para que otro plan empezara encima. Reformular por
        petición era una forma de interrumpir, que es lo contrario de lo pedido.
        """
        p = self.plan("lo de antes")
        self.ps.tomar(p["id"])
        r = self.ps.reformular(p["id"], nuevo_objetivo="lo de antes · además: X",
                               motivo="requisito añadido")
        self.assertEqual(r["estado"], "en_curso")
        self.assertEqual(self.ps.en_curso()["id"], p["id"])
        self.assertIn("además: X", self.ps.en_curso()["objetivo"])

    def test_reformular_cambia_objetivo_y_deja_estado(self):
        p = self.plan("lo viejo")
        r = self.ps.reformular(p["id"], nuevo_objetivo="lo nuevo",
                               motivo="llega uno de prioridad 90")
        self.assertEqual(r["objetivo"], "lo nuevo")
        self.assertEqual(r["estado"], "reformulado")
        self.assertEqual(r["reformula_motivo"], "llega uno de prioridad 90")

    def test_un_plan_reformulado_se_puede_tomar(self):
        p = self.plan()
        self.ps.reformular(p["id"], nuevo_objetivo="otro", motivo="x")
        self.ps.tomar(p["id"])
        self.assertEqual(self.ps.en_curso()["objetivo"], "otro")


class TestFiltros(Base):
    def test_filtrar_por_estado_desconocido_no_devuelve_cosas_raras(self):
        with self.assertRaises(PlanError):
            self.ps.planes(estado="inventado")

    def test_filtrar_por_proyecto(self):
        self.plan("en aegis", proyecto="aegis")
        self.plan("en otro", proyecto="otro")
        self.assertEqual(len(self.ps.planes(proyecto="aegis")), 1)

    def test_los_estados_declarados_son_los_que_se_pueden_poner(self):
        self.assertEqual(set(OCUPAN), {"en_curso"})


class TestSobrevive(Base):
    def test_el_almacen_se_abre_despues_de_cerrarse(self):
        p = self.plan("esto tiene que seguir aqui")
        ruta = self.ps.ruta
        self.ps.tomar(p["id"])
        otro = Planes(ruta)
        self.assertEqual(otro.en_curso()["objetivo"], "esto tiene que seguir aqui")

    def test_reabrir_no_duplica_la_tabla(self):
        ruta = self.ps.ruta
        self.plan("uno")
        Planes(ruta)
        Planes(ruta)
        self.assertEqual(len(Planes(ruta).planes()), 1)


if __name__ == "__main__":
    unittest.main()