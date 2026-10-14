"""La tool `memoria`: recordar bajo demanda, no por defecto.

## Por qué existe en forma de tool y no solo inyectada
Hasta el 2026-10-14 la memoria era **solo** un bloque de 1 800 chars que el
bridge metía en el prompt, y **solo si el encargo traía `project`**. Tres
consecuencias, y las tres se pueden comprobar aquí:

1. El modelo **no podía preguntar**. Recibía lo que el bridge ya había elegido.
2. **Sin proyecto no había memoria**, que es justo el caso de una conversación.
3. **Se pagaba en todos los runs** aunque no sirviera —medido: un prompt más
   grande no cambió el comportamiento que describía—.

## Lo que estos tests fijan
Que la tool **exige** `consulta`, que **filtra** lo no resuelto, y que cuando no
tiene nada que decir **lo dice** en vez de devolver una lista vacía que el modelo
rellenaría de invención.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mcp_ops  # noqa: E402


def _tool():
    return mcp_ops.mcp._tool_manager.get_tool("memoria").fn


class _MemoriaFalsa:
    """Una memoria con lo que el test necesita y nada más."""

    def __init__(self, episodios):
        self._episodios = episodios
        self.consultas = []

    async def recall(self, consulta, k=3):
        self.consultas.append((consulta, k))
        return {"episodes": self._episodios, "graph": []}

    def render_context(self, results, max_chars=1800):
        filas = results.get("episodes") or []
        if not filas:
            return ""
        return "\n".join(f"- {f.get('metadata', {}).get('summary', '')}"
                         for f in filas)[:max_chars]


def _ep(outcome: str, resumen: str) -> dict:
    return {"metadata": {"outcome": outcome, "summary": resumen}}


class TestLaToolMemoria(unittest.TestCase):
    def test_exige_una_consulta(self) -> None:
        """Sin `consulta` sería «dame todo», que es un volcado, no una respuesta."""
        salida = _tool()()
        self.assertIn("palabras tuyas", salida)
        self.assertIn("verificador", salida,
                      "el ejemplo tiene que ser uno real, o no sirve de nada")

    def test_pasa_la_consulta_tal_cual(self) -> None:
        """El texto de la persona es lo que se busca. Si se normaliza, deja de servir."""
        mem = _MemoriaFalsa([_ep("success", "el verificador estaba en verde")])
        with mock.patch("app.memory.get_memory", return_value=mem):
            _tool()(consulta="El VERIFICADOR de Aegis, la última vez", limite=3)
        self.assertEqual([("El VERIFICADOR de Aegis, la última vez", 9)], mem.consultas)

    def test_lo_no_resuelto_no_se_devuelve(self) -> None:
        """El filtro vive en la tool, no solo en el renderizador.

        `render_context` está escrito para no confiar en nadie, y la tool
        también. Dos sitios filtrando es la forma de que uno cambie y el otro no
        se entere.
        """
        mem = _MemoriaFalsa([
            _ep("failed", "se rompió y no se arregló"),
            _ep("sin_evidencia", "nunca se comprobó"),
            _ep("success", "esto sí salió bien"),
        ])
        with mock.patch("app.memory.get_memory", return_value=mem):
            salida = _tool()(consulta="algo")
        self.assertIn("esto sí salió bien", salida)
        self.assertNotIn("se rompió", salida)
        self.assertNotIn("nunca se comprobó", salida)

    def test_sin_nada_que_contar_lo_dice(self) -> None:
        """«No lo sé» es una respuesta. Una lista vacía es una invitación a inventar."""
        mem = _MemoriaFalsa([_ep("failed", "falló"), _ep("sin_evidencia", "nunca se vio")])
        with mock.patch("app.memory.get_memory", return_value=mem):
            salida = _tool()(consulta="lo que sea")
        self.assertIn("no tengo nada resuelto", salida)
        self.assertIn("No te invento un recuerdo", salida)

    def test_un_fallo_en_la_memoria_no_tumba_el_run(self) -> None:
        """Chroma puede no estar. Eso degrada la memoria, nunca el trabajo."""

        class _Rota:
            async def recall(self, consulta, k=3):
                raise RuntimeError("chroma no está")

            def render_context(self, *a, **k): return ""

        with mock.patch("app.memory.get_memory", return_value=_Rota()):
            salida = _tool()(consulta="algo")
        self.assertIn("No pude consultar la memoria", salida)
        self.assertIn("RuntimeError", salida)

    def test_el_limite_se_acota(self) -> None:
        """Ni 0 ni 10 000: lo que se le pide, lo que se le da."""
        mem = _MemoriaFalsa([_ep("success", "x")])
        with mock.patch("app.memory.get_memory", return_value=mem):
            _tool()(consulta="c", limite=0)
            _tool()(consulta="c", limite=99_999)
        # `limite or 3` primero: un 0 es «no lo he dicho», no «cero». Después
        # `max(1, min(…, 8))`, y el recall recibe el triple porque se filtran los
        # no resueltos antes de cortar.
        #
        # El 0 cae al default en vez de a 1 a propósito: `limite=0` es lo que
        # emite un 7B cuando no le da la gana, y «no he dicho nada» tiene que
        # querer decir «lo de siempre», no «búscame cero cosas».
        self.assertEqual([("c", 9), ("c", 24)], mem.consultas)


class TestLaMemoriaEsLibre(unittest.TestCase):
    def test_esta_clasificada_como_solo_lectura(self) -> None:
        """Preguntar por la memoria no cambia nada del disco.

        Y hasta hace poco la memoria **no se podía preguntar**, así que leerla
        era, de hecho, lo más parecido que había a una operación de solo lectura
        que Aegis pudiera hacer por su cuenta.
        """
        from app.autonomy import CON_PERMISO, LIBRES, REQUIERE_OK
        self.assertIn("memoria", LIBRES)
        self.assertNotIn("memoria", CON_PERMISO)
        self.assertNotIn("memoria", REQUIERE_OK)

    def test_esta_en_el_schema(self) -> None:
        """Si no está en el schema, el modelo no puede llamarla. A-082."""
        nombres = [t.name for t in mcp_ops.mcp._tool_manager.list_tools()]
        self.assertIn("memoria", nombres)


if __name__ == "__main__":
    unittest.main()
