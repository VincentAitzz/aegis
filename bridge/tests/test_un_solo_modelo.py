"""Un solo modelo residente, y por qué.

Dos modelos resident son **dos `llama-server` en RAM a la vez**. Medido en esta
máquina (15 GB de RAM, cero swap):

    llama-server (7B)      6,07 GB de RAM
    llama-server (embed)   0,64 GB de RAM
    swap                    0          ← por eso moría el editor

Con cero swap, un OOM mata lo que esté abierto, y «que Aegis no se cuelgue ni
pierda el trabajo» es uno de los cuatro sentidos de «confiable». El diseño de
dos modelos era, sin saberlo, la causa de la inestabilidad.

Por eso `t1_model` viene vacío y se resuelve con `modelo_t1()`. Un valor que
tiene que coincidir con otro divergirá; un valor vacío no.
"""

import unittest

from app.config import Settings


class TestUnSoloModelo(unittest.TestCase):
    def test_vacio_significa_el_de_siempre(self):
        s = Settings(t1_model="")
        self.assertEqual(s.modelo_t1(), s.autopilot_model)

    def test_no_es_un_segundo_modelo_por_defecto(self):
        """El defecto tiene que ser un solo modelo, no dos distintos.

        Si esto falla, significa que alguien volvió a poner un nombre aquí. El
        coste no es un nombre feo: es el segundo `llama-server`, el intercambio
        de 6–15 s y el OOM.
        """
        self.assertEqual(Settings().modelo_t1(), Settings().autopilot_model)

    def test_un_nombre_explicito_sigue_funcionando(self):
        """Poner un modelo pequeño a mano tiene que seguir siendo posible.

        Es lo que hace falta para medir un modelo pequeño al lado del grande sin
        tocar nada más, y no se quiere quitar la palanca.
        """
        s = Settings(t1_model="llama3.2:3b")
        self.assertEqual(s.modelo_t1(), "llama3.2:3b")

    def test_espacios_no_cuentan_como_nombre(self):
        self.assertEqual(Settings(t1_model="   ").modelo_t1(),
                         Settings().autopilot_model)


if __name__ == "__main__":
    unittest.main()