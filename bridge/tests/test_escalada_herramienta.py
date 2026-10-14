"""La escalada que faltaba: querer llamar a una tool sin haberla llamado.

Medido sobre los 108 runs con `fin: sin_tools`, las últimas 20 respuestas
incluían dos que eran **una llamada a tool servida como respuesta**:

    {"name": "uso_enfoque", "arguments": {"nombre": "", "por_que": "..."}}
    {"name": "fichas_read", "parameters": {"f": "aegis projects"}}

`fichas_read` no existe en el schema. `uso_enfoque` va con el nombre vacío. El
modelo pidió una herramienta, Aegis no pudo, y el JSON crudo quedó como
respuesta con el run marcado como completado.

Es A-016 con otro traje, y sin la red que lo delata en un run de agente: en
conversación no hay tool que revisar ni verificador que salga rojo. La persona
lee una respuesta y cree que Aegis respondió.

Estos tests fijan las dos mitades del predicado. La que no escala es la
importante: sin ella, basta con que Aegis hable de herramientas para que cada
mención dispare un T2.
"""

import unittest

from app.autopilot import anuncia_tool_sin_ejecutar


class TestAnunciaToolSinEjecutar(unittest.TestCase):
    """Una llamada que se quedó en el aire sí es intención de llamar."""

    def test_json_de_tool_completo(self):
        self.assertTrue(anuncia_tool_sin_ejecutar(
            '{"name": "fichas_read", "parameters": {"f": "aegis projects"}}'))

    def test_json_con_argumentos_vacios(self):
        # El caso medido: el nombre de la tool existe pero el argumento no.
        # Con esquema, `nombre=""` significa «suelta el enfoque» y es legítimo.
        # Sin esquema es solo JSON perdido, y eso también escala.
        self.assertTrue(anuncia_tool_sin_ejecutar(
            '{"name": "uso_enfoque", "arguments": {"nombre": ""}}'))

    def test_json_cortado_por_el_limite_de_tokens(self):
        self.assertTrue(anuncia_tool_sin_ejecutar(
            '{"name": "repo_verify", "arg'))

    def test_llamada_sin_herramientas(self):
        self.assertTrue(anuncia_tool_sin_ejecutar("aegis_read_file"))

    def test_llamada_suelta_y_abierta(self):
        # Sin schema el modelo a veces contesta el nombre y ahí se acaba: no es
        # una respuesta ni una frase, es una llamada a la que no le llegó a
        # llegar `arguments`. Y por tanto no se ejecutó.
        self.assertTrue(anuncia_tool_sin_ejecutar("aegis_read_file("))

    def test_preguntar_por_una_tool_no_es_una_llamada(self):
        for texto in ("¿qué hace repo_verify?", "el repo_verify", "aegis_write_file,"):
            with self.subTest(texto=texto):
                self.assertFalse(anuncia_tool_sin_ejecutar(texto))

    def test_placeholders_de_otros_idiomas(self):
        # El regex de `_DANGLING_RE` también reconoce los placeholders en
        # chino y japonés, que es de donde viene el corte a mitad de llamada.
        # Van como escapes y no literales a propósito: `test_texto.py` exige
        # que ningún fichero del repo se salga de Latin, y el comportamiento se
        # comprueba igual —lo que se testea es el regex, no el fichero.
        for texto in ("(tool call)", "(\u5de5\u5177\u8c03\u7528)",
                      "(\u547c\u3073\u51fa\u3057):", "calling tool:"):
            with self.subTest(texto=texto):
                self.assertTrue(anuncia_tool_sin_ejecutar(texto))

    def test_vacio_no_es_intencion(self):
        # Sin texto no hay nada que annoncer. El silencio escala por su cuenta,
        # en otra rama: si esto devolviera True, el motivo del log mentiría.
        self.assertFalse(anuncia_tool_sin_ejecutar(""))
        self.assertFalse(anuncia_tool_sin_ejecutar("   \n  "))


class TestNoEscalarPorHablarDeHerramientas(unittest.TestCase):
    """Nombrar una tool es conversación. Solo la *forma* de llamada escala.

    La diferencia es la que separa dos cosas que se parecen mucho y son
    opuestas: decir «voy a usar `aegis_read_file`» es explicar el plan, y
    `{"name": "aegis_read_file"}` es dejarlo sin hacer. Sin esta mitad, una
    respuesta normal sobre cómo funcionan las tools dispara un T2 entero.
    """

    def test_plan_en_lenguaje_natural(self):
        for texto in (
            "Voy a usar aegis_read_file para mirarlo",
            "para eso haría falta repo_verify; dime y lo lanzo",
            "el método dice que aegis_write_file pide aprobación, ¿lo hacemos?",
        ):
            with self.subTest(texto=texto):
                self.assertFalse(anuncia_tool_sin_ejecutar(texto))

    def test_conversacion_normal(self):
        for texto in (
            "¡Hola! ¿En qué puedo ayudarte hoy?",
            "No encontré una lección A-088, ¿puedes confirmar el número?",
            "Aegis no se niega a hacer nada en lo comercial.",
            " according to the method, it should work. ",
        ):
            with self.subTest(texto=texto):
                self.assertFalse(anuncia_tool_sin_ejecutar(texto))


class TestLaFormaDeLaLlamada(unittest.TestCase):
    """La forma se reconoce por el nombre del campo, no por el texto entero.

    `name:` dentro de un JSON cualquiera es la señal. Se prueban las variantes
    que el 7B emite de verdad, porque son las que aparecen en los logs: con
    `name` y con `function`, con el objeto suelto y envuelto en `calls`.
    """

    def test_variantes_de_nombre_de_campo(self):
        for texto in (
            '{"tool_name": "repo_verify", "arguments": {}}',
            '{"function": "repo_verify", "arguments": {}}',
            '[{"name": "repo_verify", "arguments": {}}]',
            '{"calls": [{"name": "repo_verify", "arguments": {}}]}',
        ):
            with self.subTest(texto=texto):
                self.assertTrue(anuncia_tool_sin_ejecutar(texto))


if __name__ == "__main__":
    unittest.main()