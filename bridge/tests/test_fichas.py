"""La puerta: no se escribe en un proyecto que no se sabe qué es.

Regresión de la regla del usuario — *"primero conocer qué necesita el cliente,
para qué se usaría, alcance, alternativas"* — hecha verificable por máquina.

Dos propiedades importan aquí:

1. Una ficha recién creada **no** pasa la puerta. Si pasara, la puerta valdría
   nada: basta con escribir los encabezados y seguir como antes.
2. La puerta **no** es una puerta de geeks. Leer el proyecto sigue permitido,
   porque leer es justo lo que hay que hacer para entenderlo.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fichas, mcp_ops  # noqa: E402
from app.fichas import (  # noqa: E402
    FichaIncompleta,
    PENDIENTE,
    context_for,
    exige,
    parse,
    plantilla,
)

COMPLETA_HERRAMIENTA = """---
kind: herramienta
---

## Qué es
El agente local del freelance.

## Por qué existe
Sin esto no hay forma de trabajar a distancia.

## Invariantes
La memoria no guarda datos de cliente.

## Cómo se verifica
cd bridge && .venv/bin/python -m unittest discover -s tests -q

## Qué no toca
Producción jamás, ni el Worker.
"""


class _DirTemporal(unittest.TestCase):
    """Redirige las rutas de ficha a un temporal, para no tocar las reales.

    Solo hace falta parchear `FICHAS_DIR`/`PRIVADAS_DIR`: la puerta resuelve
    `exige` en tiempo de llamada, así que el módulo ya ve el temporal.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.fichas = self.tmp / "fichas"
        self.privadas = self.tmp / "privadas"
        self.fichas.mkdir()
        self.privadas.mkdir()
        for attr, valor in (("FICHAS_DIR", self.fichas),
                            ("PRIVADAS_DIR", self.privadas)):
            patcher = mock.patch.object(fichas, attr, valor)
            patcher.start()
            self.addCleanup(patcher.stop)

    def escribir(self, alias: str, texto: str) -> None:
        (self.fichas / f"{alias}.md").write_text(texto, encoding="utf-8")


class TestParseo(unittest.TestCase):
    def test_frontmatter_y_secciones(self) -> None:
        f = parse("x", COMPLETA_HERRAMIENTA)
        self.assertEqual(f.kind, "herramienta")
        self.assertEqual(len(f.secciones), 5)
        self.assertTrue(f.completa)

    def test_una_plantilla_no_cuenta_como_escrita(self) -> None:
        for kind in fichas.TIPOS:
            f = parse("x", plantilla(kind))
            self.assertFalse(f.completa, f"la plantilla de {kind} pasó la puerta")
            self.assertEqual(len(f.faltan()), len(fichas.SECCIONES_POR_TIPO[kind]))

    def test_texto_de_ayuda_no_cuenta(self) -> None:
        # Un comentario HTML es guía para quien rellena, no contenido.
        f = parse("x", "---\nkind: producto\n---\n\n## Qué es\n\n<!-- Una frase. -->\n")
        self.assertIn("Qué es", f.faltan())

    def test_comentario_multilinea_tampoco_cuenta(self) -> None:
        """Regresión: el filtro de comentarios era de una sola línea.

        Con el regex anterior, un comentario largo ocupaba varias líneas y la
        segunda se leía como contenido, así que una sección que solo tenía un
        comentario larguísimo contaba como escrita. La puerta se abría sola, que
        es justo lo que una puerta no puede hacer.
        """
        largo = ("<!-- Pendiente del usuario. Los invariantes de este repo salen de\n"
                 "     lo que no se puede romper: qué pasa si el móvil pierde\n"
                 "     conexión, si el servidor va lento, qué tamaño tiene el\n"
                 "     frame. -->\n")
        f = parse("x", "---\nkind: herramienta\n---\n\n## Invariantes\n\n" + largo)
        self.assertIn("Invariantes", f.faltan())

    def test_comentario_junto_a_contexto_real_si_cuenta(self) -> None:
        """Con texto de verdad alrededor, la sección sí está escrita."""
        f = parse("x", "---\nkind: producto\n---\n\n## Qué es\n\n"
                  "Aegis es el agente.\n\n<!-- falta expandarlo -->\n")
        self.assertNotIn("Qué es", f.faltan())

    def test_una_seccion_escrita_sale_de_la_lista(self) -> None:
        texto = plantilla("herramienta").replace("<!-- Una frase. -->", "Aegis es el agente.")
        f = parse("x", texto)
        self.assertNotIn("Qué es", f.faltan())
        self.assertFalse(f.completa)  # las demás siguen vacías

    def test_marcadores_de_pendiente_no_cuentan(self) -> None:
        for marca in ("TBD", "pendiente", "por completar", "—", "..."):
            with self.subTest(marca=marca):
                f = parse("x", f"---\nkind: producto\n---\n\n## Qué es\n\n{marca}\n")
                self.assertIn("Qué es", f.faltan())


class TestPuerta(_DirTemporal):
    def test_sin_ficha_no_pasa(self) -> None:
        with self.assertRaises(FichaIncompleta) as cm:
            exige("nuevo")
        self.assertIn("no tiene ficha", str(cm.exception))

    def test_ficha_incompleta_dice_que_falta(self) -> None:
        self.escribir("nuevo", plantilla("encargo"))
        with self.assertRaises(FichaIncompleta) as cm:
            exige("nuevo")
        mensaje = str(cm.exception)
        self.assertIn("Alternativas consideradas", mensaje)
        self.assertIn("Alcance fuera", mensaje)

    def test_tipo_desconocido_no_pasa(self) -> None:
        self.escribir("raro", "---\nkind: loquesea\n---\n\n## Qué es\n\nalgo\n")
        with self.assertRaises(FichaIncompleta) as cm:
            exige("raro")
        self.assertIn("tipo válido", str(cm.exception))

    def test_ficha_completa_pasa(self) -> None:
        self.escribir("aegis", COMPLETA_HERRAMIENTA)
        self.assertEqual(exige("aegis").kind, "herramienta")

    def test_cada_tipo_exige_su_propia_forma(self) -> None:
        # El motivo de que el tipo exista: no pedirle discovery a tu herramienta.
        self.escribir("mio", "---\nkind: herramienta\n---\n\n"
                      "## Qué es\n\nx\n\n## Por qué existe\n\ny\n\n"
                      "## Invariantes\n\nz\n\n## Cómo se verifica\n\nw\n\n"
                      "## Qué no toca\n\nq\n")
        exige("mio")  # no pide alternativas de cliente
        with self.assertRaises(FichaIncompleta):
            exige("sin-ficha")


class TestEscrituraDenegada(_DirTemporal):
    """La puerta en la tool, que es donde de verdad decide."""

    def test_escritura_denegada_sin_ficha(self) -> None:
        with mock.patch.object(mcp_ops, "root_of", return_value="nuevo"):
            salida = mcp_ops.aegis_write_file("bridge/app/mcp_ops.py", "nuevo")
        self.assertIn("DENEGADA", salida)
        self.assertIn("no tiene ficha", salida)

    def test_parche_denegado_sin_ficha(self) -> None:
        with mock.patch.object(mcp_ops, "root_of", return_value="nuevo"):
            salida = mcp_ops.aegis_patch_file("bridge/metodo.md", "a", "b")
        self.assertIn("DENEGADA", salida)

    def test_lectura_no_pas_por_la_puerta(self) -> None:
        with mock.patch.object(mcp_ops, "root_of", return_value="nuevo"):
            salida = mcp_ops.aegis_read_file("bridge/metodo.md")
        self.assertNotIn("DENEGADA", salida)

    def test_ficha_completa_deja_pasar(self) -> None:
        self.escribir("aegis", COMPLETA_HERRAMIENTA)
        real = Path(__file__).resolve().parent.parent / "metodo.md"
        with mock.patch.object(mcp_ops, "root_of", return_value="aegis"), \
             mock.patch.object(mcp_ops, "_write_guarded",
                               return_value=(True, "")) as guardia:
            salida = mcp_ops.aegis_write_file(str(real), "contenido")
        self.assertNotIn("DENEGADA", salida)
        self.assertTrue(guardia.called, "con ficha completa debería haber escrito")

    def test_lectura_funciona_aun_sin_ficha(self) -> None:
        """Leer es parte de entender. Si la puerta cerrara la lectura, inútil."""
        with mock.patch.object(mcp_ops, "root_of", return_value="nuevo"):
            salida = mcp_ops.aegis_read_file("bridge/metodo.md")
        self.assertNotIn("DENEGADA", salida)


class TestContextoParaElPrompt(unittest.TestCase):
    def test_proyecto_sin_ficha_no_aporta(self) -> None:
        self.assertEqual(context_for(""), "")
        self.assertEqual(context_for("no-es-un-proyecto-este"), "")

    def test_contexto_avisa_de_lo_pendiente(self) -> None:
        # `aegis` es un proyecto real; se le pone una plantilla en un temporal
        # para no tocar su ficha de verdad.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fichas, "FICHAS_DIR", Path(d)):
                (Path(d) / "aegis.md").write_text(plantilla("herramienta"), encoding="utf-8")
                ctx = context_for("aegis")
        self.assertIn("PENDIENTE", ctx)
        self.assertIn("Invariantes", ctx)


if __name__ == "__main__":
    unittest.main()

class TestSubseccionesNoRellenanLaSeccion(unittest.TestCase):
    """Un `###` no rellena el `##` que lo contiene."""

    def test_seccion_con_solo_subsections_no_cuenta(self) -> None:
        texto = ("---\nkind: herramienta\n---\n\n"
                 "## Qué no toca\n\n<!-- nada -->\n\n"
                 "### Dónde encaja\n\nEs infraestructura.\n")
        f = parse("x", texto)
        self.assertIn("Qué no toca", f.faltan())

    def test_seccion_con_texto_propio_si_cuenta(self) -> None:
        texto = ("---\nkind: herramienta\n---\n\n"
                 "## Qué no toca\n\nNo despliega nada.\n\n"
                 "### Dónde encaja\n\nEs infraestructura.\n")
        f = parse("x", texto)
        self.assertNotIn("Qué no toca", f.faltan())


class TestElAgenteVeLoQueFalta(unittest.TestCase):
    """Un proyecto sin ficha tiene que ser visible, o el agente no sabe qué hacer.

    Regresión real: `registry_list` solo miraba `registro/*.json`, así que los
    proyectos declarados en Python —compra-unida, portafolio, trazeurs— no
    aparecían nunca. Tres fichas que no existían, invisibles.
    """

    def test_resumen_abarca_todos_los_registrados(self) -> None:
        from app import alta as alta_mod
        from app.projects import PROJECTS
        texto = alta_mod.resumen_registro()
        for alias in PROJECTS:
            with self.subTest(alias=alias):
                self.assertIn(alias, texto, f"{alias} no aparece en el resumen")

    def test_el_resumen_dice_el_estado_de_cada_ficha(self) -> None:
        from app import alta as alta_mod
        texto = alta_mod.resumen_registro().lower()
        self.assertIn("sin ficha", texto)
        self.assertIn("completa", texto)

    def test_context_for_avisa_si_no_hay_ficha(self) -> None:
        """Devolver cadena vacía hace que Aegis no sepa ni que el proyecto existe."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fichas, "FICHAS_DIR", Path(d)):
                ctx = fichas.context_for("compra-unida")
        self.assertTrue(ctx, "un proyecto sin ficha debe producir contexto, no vacío")
        self.assertIn("ficha", ctx.lower())
        self.assertIn("compra-unida", ctx)

    def test_un_alias_desconocido_sigue_dando_vacio(self) -> None:
        """Un alias que no es proyecto no debe inventarse contexto."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fichas, "FICHAS_DIR", Path(d)):
                self.assertEqual(fichas.context_for("no-es-un-proyecto-este"), "")

    def test_leer_una_ficha_inexistente_no_revienta(self) -> None:
        # Proyecto real, ficha ausente: tiene que explicar qué hace falta.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fichas, "FICHAS_DIR", Path(d)):
                salida = fichas.leer_para_agente("compra-unida")
        self.assertIn("no tiene ficha", salida.lower())
        self.assertIn("compra-unida", salida)

    def test_leer_un_alias_que_no_es_proyecto_lo_dice(self) -> None:
        salida = fichas.leer_para_agente("no-existe-este")
        self.assertIn("no es un proyecto", salida.lower())


class TestEscrituraDeFichaSinModelo(unittest.TestCase):
    """La ruta que hace el móvil: el humano revisó el texto y el bridge lo guarda.

    La versión anterior mandaba el texto por el modelo con la instrucción de
    copiarlo "exactamente". Falló: el 7B **se come los `---` del frontmatter**,
    que es lo que declara el `kind`, y la ficha quedaba sin tipo. Por eso la
    escritura no pasa por el modelo.
    """

    def setUp(self) -> None:
        # Sin esto, la ruta de escritura del endpoint toca el directorio REAL de
        # fichas: el endpoint deriva la ruta desde el módulo, así que parchear
        # FICHAS_DIR en otro sitio no alcanza. Se deja apuntando a un temporal y
        # se restaura al terminar.
        import tempfile
        from app import mcp_ops
        # Lo que hay que redirigir es la **ruta resuelta**, no FICHAS_DIR: el
        # endpoint deriva el destino con `_safe_resolve`, que mira el disco real
        # a través del registro de proyectos. Parchear FICHAS_DIR no movía nada
        # y el test escribía sobre `bridge/fichas/` de verdad.
        self.tmp = Path(tempfile.mkdtemp())
        real_resolve = mcp_ops._safe_resolve
        real_dir = fichas.FICHAS_DIR
        mcp_ops._safe_resolve = lambda path: self.tmp / Path(path).name
        # También la lectura: si solo se redirige la escritura, el endpoint
        # escribe en el temporal y lee del disco real, y reporta "sin ficha"
        # sobre un archivo que acaba de crear.
        fichas.FICHAS_DIR = self.tmp

        def restaurar() -> None:
            mcp_ops._safe_resolve = real_resolve
            fichas.FICHAS_DIR = real_dir

        self.addCleanup(restaurar)

    def _post(self, alias: str, contenido: str):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app).post(f"/fichas/{alias}", json={"contenido": contenido})

    def test_escribe_byte_exacto_incluido_el_frontmatter(self) -> None:
        texto = "---\nkind: producto\n---\n\n# Trazeurs\n\n## Que es\n\naplicacion\n"
        r = self._post("compra-unida", texto)
        self.assertEqual(r.status_code, 200, r.text)
        escrito = (self.tmp / "compra-unida.md").read_text(encoding="utf-8")
        self.assertEqual(escrito, texto)
        self.assertEqual(fichas.parse("compra-unida", escrito).kind, "producto")

    def test_devuelve_el_estado_calculado(self) -> None:
        r = self._post("compra-unida", "---\nkind: producto\n---\n\n## Que es\n\nx\n")
        self.assertTrue(r.json()["escrito"])
        self.assertEqual(r.json()["estado"], "incompleta")
        self.assertIn("Próximo paso", r.json()["faltan"])

    def test_un_alias_inexistente_es_404(self) -> None:
        self.assertEqual(self._post("no-existe-este", "x").status_code, 404)

    def test_un_secreto_es_400_y_no_Deja_archivo(self) -> None:
        """Un 500 escondería que el rechazo fue correcto, no un fallo."""
        r = self._post(
            "compra-unida",
            "---\nkind: producto\n---\n\nAPI_KEY=sk-live-abcdef1234567890abcdef\n")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("sk-live", r.text, "el valor filtrado no debe aparecer en la respuesta")
        self.assertFalse((self.tmp / "compra-unida.md").exists())

