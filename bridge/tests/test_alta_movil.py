"""El alta de un proyecto desde el móvil: la puerta de entrada.

## Qué se prueba y por qué
Empezar un encargo es la acción más frecuente que no existeía: hasta ahora
había que editar Python o llamar a una tool del agente desde un run de autopilot.
Aquí se cierra ese hueco, y se prueban tres cosas que se pueden romper por
motivos distintos:

1. **La ruta funciona y crea lo que dice** — carpeta, registro, ficha pública y
   ficha privada. Un 200 que no creó nada es peor que un 500.
2. **La ficha privada nace flexible**, no como un formulario con campos fijos.
   Los encargos no se cobran todos igual, y una plantilla con «Precio:» escrito
   obliga a inventar un valor para un proyecto que no se cobra.
3. **Lo comercial no se cuela en la pública**, y la privada no viaja en git.

## Lo que no se prueba
Que la ficha privada quede «completa». No tiene puerta a propósito: el modelo
de cobro no tiene forma canónica, y exigirla obliga al usuario a rellenar
campos que en su encargo no existen.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import alta as alta_mod  # noqa: E402
from app import fichas, projects  # noqa: E402


class _AltaTemporal(unittest.TestCase):
    """Workspace, registro y fichas en un tmpdir. `PROJECTS` de código se queda."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.registro = self.tmp / "registro"
        self.registro.mkdir()
        (self.tmp / "apps").mkdir()
        for mod, attr, valor in (
            (projects, "REGISTRO_DIR", self.registro),
            (alta_mod, "REGISTRO_DIR", self.registro),
            (fichas, "FICHAS_DIR", self.tmp / "fichas"),
            (fichas, "PRIVADAS_DIR", self.tmp / "priv"),
        ):
            patcher = mock.patch.object(mod, attr, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        self._settings = mock.patch(
            "app.config.get_settings",
            return_value=mock.Mock(workspace_dir=str(self.tmp),
                                   workspace_areas="apps,web,mobile"))
        self._settings.start()
        self.addCleanup(self._settings.stop)
        # Se guardan los dos. `PROJECTS` es el mapa y `_DATOS` el **set de alias**
        # que vienen del disco; los dos son estado global, y vaciar cualquiera
        # sin restaurarlo lo deja roto para los tests siguientes.
        self._codigo = dict(projects.PROJECTS)
        self._datos = set(projects._DATOS)
        for alias in list(projects._DATOS):
            projects.PROJECTS.pop(alias, None)
        projects._DATOS.clear()
        self.addCleanup(self._restaurar)

    def _restaurar(self) -> None:
        projects.PROJECTS.clear()
        projects.PROJECTS.update(self._codigo)
        projects._DATOS.clear()
        projects._DATOS.update(self._datos)


class TestAltaCreaLoQueDice(_AltaTemporal):
    def test_nace_lo_que_promete(self) -> None:
        from app.alta import alta
        alta(alias="encargo-nuevo", area="apps", kind="encargo",
             nombre="Encargo nuevo")
        self.assertTrue((self.tmp / "apps" / "encargo-nuevo").is_dir())
        self.assertTrue((self.tmp / "registro" / "encargo-nuevo.json").is_file())
        self.assertTrue(fichas.ficha_path("encargo-nuevo").is_file())

    def test_nace_tambien_la_ficha_privada(self) -> None:
        """Sin ella, el alta deja al usuario sin dónde poner el precio y la fecha.

        Y esos son justo los dos datos que el agente tiene prohibido suponer, así
        que el hueco no se nota hasta que Aegis pregunta en el peor momento.
        """
        from app.alta import alta
        alta(alias="encargo-nuevo", area="apps", kind="encargo")
        privada = fichas.privada_path("encargo-nuevo")
        self.assertTrue(privada.is_file())
        self.assertIn("Cliente y contacto", privada.read_text(encoding="utf-8"))

    def test_el_salido_dice_que_existe_la_privada(self) -> None:
        """Si no lo dice, el usuario no sabe que hay un segundo fichero."""
        from app.alta import alta
        mensaje = alta(alias="encargo-nuevo", area="apps", kind="encargo")
        self.assertIn("Privada:", mensaje)

    def test_no_pisa_la_privada_ya_escrita(self) -> None:
        """Repetir el alta no puede borrar lo comercial ya escrito."""
        from app.alta import alta
        alta(alias="encargo-nuevo", area="apps", kind="encargo")
        privada = fichas.privada_path("encargo-nuevo")
        privada.write_text("ya escrito", encoding="utf-8")
        with self.assertRaises(Exception):
            # el alias ya está: el alta se niega antes de llegar a la privada
            alta(alias="encargo-nuevo", area="apps", kind="encargo")
        self.assertEqual("ya escrito", privada.read_text(encoding="utf-8"))


class TestPlantillaPrivadaEsFlexible(_AltaTemporal):
    """La flexibilidad no es un detalle de redacción: es lo que la hace usable."""

    def setUp(self) -> None:
        super().setUp()
        self.texto = fichas.plantilla_privada()
        # Aplanado una vez para todos: el ajuste de línea parte las frases, y
        # lo que se prueba es que la guía existe, no dónde cayó el salto.
        self.plano = " ".join(self.texto.split())

    def test_no_hay_campos_obligatorios_de_cobro(self) -> None:
        """Nada de «Precio:» o «Forma de pago:» como campo a rellenar.

        Si el encargo es interno o el cliente ya paga una cuota fija, esos
        campos no tienen valor, y una plantilla que los exige produce
        información inventada —que es peor que información ausente.
        """
        for campo in ("Precio:", "Horas estimadas:", "Forma de pago:"):
            self.assertNotIn(campo, self.texto)

    def test_ofrece_los_modelos_de_cobro_como_menu(self) -> None:
        """El menú es lo que permite no inventar: se elige uno y se borra el resto."""
        for modelo in ("precio cerrado", "por hitos", "por horas", "sin cobro"):
            self.assertIn(modelo, self.texto,
                          f"falta el modelo «{modelo}» en el menú de cobro")

    def test_dice_explicitamente_que_se_borran_las_secciones(self) -> None:
        """Sin esta instrucción, la plantilla se rellena entera y se inventa."""
        self.assertIn("Borra las secciones que no apliquen", self.plano)

    def test_dice_que_aegis_no_inventa_precios(self) -> None:
        """La razón de esta advertencia está en el fichero, no en el código."""
        self.assertIn("nunca pone un precio", self.plano)

    def test_pide_el_modelo_y_el_entregable(self) -> None:
        """Lo único que de verdad hace falta para no proponer trabajo de más."""
        self.assertIn("modelo de cobro", self.plano.lower())

    def test_toda_la_guia_va_en_comentarios(self) -> None:
        """Lo que guía no puede ser prosa suelta.

        La app decide si la ficha privada está rellena **mirando el texto**, y
        con una guía escrita como texto normal no hay forma de distinguir «esto
        es una instrucción para ti» de «esto es la respuesta del cliente». Lo
        que se queda fuera de los comentarios es exactamente lo que la persona
        escribió, que es lo único que cuenta como respuesta.

        Esta regla se rompió una vez al escribir la plantilla: el menú de modelos
        de cobro y la nota de uso estaban en prosa, así que una ficha recién
        creada se declaraba rellena —el error que `sinRellenar` existe para
        evitar—.
        """
        import re
        limpio = re.sub(r"<!--.*?-->", "", self.texto, flags=re.DOTALL)
        # Se quitan el frontmatter y los encabezados: son el andamiaje del
        # formato, no guía. Lo que queda es prosa, y la prosa es lo que la app
        # leería como respuesta.
        limpio = limpio.split("---", 2)[-1]
        for linea in limpio.splitlines():
            t = linea.strip()
            if not t or t.startswith("#"):
                continue
            self.assertTrue(False, f"guía fuera de comentario: {t!r}")

    def test_el_menu_sigue_estando_dentro_de_un_comentario(self) -> None:
        """La guía no desaparece al arreglarla: sigue ahí, solo que comentada."""
        self.assertIn("sin cobro", self.plano)
        self.assertIn("por hitos", self.plano)

    def test_avisa_de_los_datos_de_contacto(self) -> None:
        """Los datos de un tercero no salen en ninguna respuesta de Aegis."""
        self.assertIn("no deben salir", self.plano)


class TestLoPrivadoNoSeVersiona(unittest.TestCase):
    """La partición es la frontera entre conocimiento de ingeniería y PII."""

    def test_el_gitignore_cubre_el_directorio(self) -> None:
        raiz = Path(__file__).resolve().parent.parent.parent
        texto = (raiz / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/bridge/fichas-privadas/", texto)

    def test_la_plantilla_no_menciona_precios_de_ejemplo(self) -> None:
        """Un número de ejemplo es un número que alguien copia."""
        texto = (Path(__file__).resolve().parent.parent
                 / "fichas" / "_plantilla-privada.md").read_text(encoding="utf-8")
        import re
        # Montos con símbolo de moneda, o cantidades que parecen un precio.
        self.assertIsNone(re.search(r"\d+\s*(?:€|\$|USD|EUR|CLP)", texto),
                          "la plantilla privada trae un importe de ejemplo: "
                          "alguien lo va a copiar sin querer")


class TestPlantillaPrivadaEsLegible(unittest.TestCase):
    """Un turno anterior dejó esta plantilla con bytes nulos y texto en otros
    alfabetos. Un fichero ilegible rompe el alta entera, y el error que sale
    («no such file») no dice que el problema es el fichero."""

    def test_se_lee_como_utf8(self) -> None:
        ruta = fichas.ruta_plantilla_privada()
        self.assertTrue(ruta.is_file(), f"no está la plantilla en {ruta}")
        texto = ruta.read_bytes().decode("utf-8")  # lanza si hay bytes nulos/rotos
        self.assertTrue(texto.strip())

    def test_no_tiene_bytes_nulos(self) -> None:
        crudo = fichas.ruta_plantilla_privada().read_bytes()
        self.assertNotIn(b"\x00", crudo,
                         "la plantilla tiene bytes nulos: es un fichero binario "
                         "disfrazado de texto y no se puede editar en el móvil")

    def test_no_tiene_alfabetos_ajenos(self) -> None:
        """El repo es en español; un CJK colado indica texto generado y no escrito."""
        import unicodedata
        texto = fichas.ruta_plantilla_privada().read_text(encoding="utf-8")
        culpables = []
        for numero, linea in enumerate(texto.splitlines(), 1):
            for ch in linea:
                if ch < "":
                    continue
                nombre = unicodedata.name(ch, "")
                if nombre.startswith(("CJK", "HIRAGANA", "KATAKANA", "HANGUL",
                                      "CYRILLIC", "ARABIC", "HEBREW", "THAI")):
                    culpables.append(f"{numero}: {ch!r} {nombre}")
        self.assertEqual([], culpables, "\n".join(culpables))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()