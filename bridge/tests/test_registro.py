"""El registro de proyectos: dar de alta sin editar Python, sin abrir la whitelist.

El registro amplía lo que Aegis puede tocar, así que sus límites son frontera de
seguridad y se prueban como tales:

- la ruta del proyecto **se deriva** de `WORKSPACE/{area}/{alias}`; un `root`
  escrito a mano en el JSON se ignora;
- un área fuera de la lista, un tipo inválido o un alias con traversal no se
  cargan;
- un alta es visible sin reiniciar el bridge (si no, la primera escritura en el
  proyecto nuevo fallaría sin explicación).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import alta as alta_mod  # noqa: E402
from app import fichas, projects  # noqa: E402
from app.alta import AltaInvalida  # noqa: E402
from app.projects import REGISTRO_DIR, areas, reload  # noqa: E402


class _WorkspaceTemporal(unittest.TestCase):
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
        # `PROJECTS` es un dict global: cada test deja el suyo si no se restaura.
        # Se restaura por snapshot, no con `reload()`, porque al limpiar los
        # parches el registro real ya no es el temporal y recargaría lo de más.
        antes = dict(projects.PROJECTS)
        self.addCleanup(self._restaurar, antes)

    def _restaurar(self, antes: dict) -> None:
        for alias in list(projects.PROJECTS):
            if alias not in antes:
                projects.PROJECTS.pop(alias, None)
        projects.PROJECTS.update(antes)
        projects._DATOS.clear()

    def escribir(self, alias: str, datos: dict) -> None:
        (self.registro / f"{alias}.json").write_text(
            json.dumps(datos, ensure_ascii=False), encoding="utf-8")


class TestAlta(_WorkspaceTemporal):
    def test_alta_crea_carpeta_registro_y_ficha(self) -> None:
        salida = alta_mod.alta("acme", "apps", "encargo", nombre="Acme")
        self.assertTrue((self.tmp / "apps" / "acme").is_dir())
        self.assertTrue((self.registro / "acme.json").exists())
        self.assertTrue(fichas.ficha_path("acme").exists())
        self.assertIn("Alta de 'acme'", salida)

    def test_el_alta_es_visible_sin_reiniciar(self) -> None:
        self.assertNotIn("acme", projects.PROJECTS)
        alta_mod.alta("acme", "apps", "encargo")
        self.assertIn("acme", projects.PROJECTS)
        self.assertEqual(projects.PROJECTS["acme"].root, self.tmp / "apps" / "acme")

    def test_la_ficha_nace_incompleta_a_proposito(self) -> None:
        alta_mod.alta("acme", "apps", "encargo")
        ficha = fichas.read_ficha("acme")
        self.assertTrue(ficha.existe)
        self.assertFalse(ficha.completa)
        with self.assertRaises(Exception):
            fichas.exige("acme")

    def test_el_alcance_pasa_a_la_seccion_correcta(self) -> None:
        alta_mod.alta("acme", "apps", "encargo", alcance="Inventario del local.")
        ficha = fichas.read_ficha("acme")
        self.assertEqual(ficha.secciones["Alcance dentro"], "Inventario del local.")

    def test_no_sobrescribe_un_proyecto_existente(self) -> None:
        with self.assertRaises(AltaInvalida):
            alta_mod.alta("aegis", "apps", "encargo")

    def test_no_sobrescribe_una_ficha_existente(self) -> None:
        fichas.FICHAS_DIR.mkdir(parents=True, exist_ok=True)
        fichas.ficha_path("acme").write_text("kind: producto\n", encoding="utf-8")
        with self.assertRaises(AltaInvalida):
            alta_mod.alta("acme", "apps", "encargo")


class TestLimitesDelAlta(_WorkspaceTemporal):
    """Lo que un alta NO puede hacer, aunque se lo pidan."""

    def test_area_fuera_de_la_lista(self) -> None:
        with self.assertRaises(AltaInvalida) as cm:
            alta_mod.alta("acme", "/etc", "encargo")
        self.assertIn("área", str(cm.exception))

    def test_area_con_traversal(self) -> None:
        with self.assertRaises(AltaInvalida):
            alta_mod.alta("acme", "../../", "encargo")

    def test_alias_con_traversal(self) -> None:
        for alias in ("../escape", "a/b", "a b", "ACME", "", "a" * 60):
            with self.subTest(alias=alias):
                with self.assertRaises(AltaInvalida):
                    alta_mod.alta(alias, "apps", "encargo")

    def test_tipo_desconocido(self) -> None:
        with self.assertRaises(AltaInvalida) as cm:
            alta_mod.alta("acme", "apps", "inventado")
        self.assertIn("tipo", str(cm.exception))

    def test_una_base_de_cliente_no_se_migra(self) -> None:
        alta_mod.alta("acme", "apps", "encargo")
        self.assertFalse(projects.PROJECTS["acme"].can_migrate)


class TestCargaDelRegistro(_WorkspaceTemporal):
    """El registro se lee de disco y no puede salirse del workspace."""

    def test_la_raiz_se_deriva_y_el_root_del_json_se_ignora(self) -> None:
        self.escribir("malo", {"alias": "malo", "area": "apps",
                               "kind": "encargo", "root": "/etc"})
        reload()
        self.assertIn("malo", projects.PROJECTS)
        self.assertEqual(projects.PROJECTS["malo"].root, self.tmp / "apps" / "malo")
        self.assertFalse(str(projects.PROJECTS["malo"].root).startswith("/etc"))

    def test_una_entrada_invalida_no_rompe_el_arranque(self) -> None:
        (self.registro / "roto.json").write_text("{no es json", encoding="utf-8")
        self.escribir("bueno", {"alias": "bueno", "area": "apps", "kind": "producto"})
        reload()
        self.assertIn("bueno", projects.PROJECTS)
        self.assertNotIn("roto", projects.PROJECTS)

    def test_sin_campos_obligatorios_se_ignora(self) -> None:
        self.escribir("incompleto", {"alias": "incompleto"})
        reload()
        self.assertNotIn("incompleto", projects.PROJECTS)

    def test_un_json_no_puede_pisar_al_codigo(self) -> None:
        # `aegis` está declarado en Python con sus verificadores y su base. El
        # disco no puede sustituirlo por una entrada vacía.
        self.escribir("aegis", {"alias": "aegis", "area": "apps", "kind": "encargo"})
        reload()
        self.assertEqual(projects.PROJECTS["aegis"].root,
                         Path("/RUTA/AL/WORKSPACE/aegis"))

    def test_reload_olvida_lo_que_se_borro(self) -> None:
        self.escribir("temporal", {"alias": "temporal", "area": "apps", "kind": "encargo"})
        reload()
        self.assertIn("temporal", projects.PROJECTS)
        (self.registro / "temporal.json").unlink()
        reload()
        self.assertNotIn("temporal", projects.PROJECTS)

    def test_archivos_guion_underscore_se_ignoran(self) -> None:
        self.escribir("_plantilla", {"alias": "_plantilla", "area": "apps",
                                     "kind": "encargo"})
        reload()
        self.assertNotIn("_plantilla", projects.PROJECTS)


class TestResumen(_WorkspaceTemporal):
    def test_resumen_dice_el_estado_de_cada_ficha(self) -> None:
        alta_mod.alta("acme", "apps", "encargo")
        texto = alta_mod.resumen_registro()
        self.assertIn("acme", texto)
        self.assertIn("incompleta", texto)


if __name__ == "__main__":
    unittest.main()

class TestEstadoParaElMovil(unittest.TestCase):
    """Lo que la app necesita para pintar el selector: alias, tipo y estado."""

    def test_un_proyecto_siempre_tiene_los_campos_que_la_app_usa(self) -> None:
        from app.main import ProyectoOut
        from app.projects import PROJECTS
        from app.fichas import secciones_que_faltan
        for alias in PROJECTS:
            with self.subTest(alias=alias):
                tipo, legible, faltan = secciones_que_faltan(alias)
                estado = ("completa" if legible == "completa"
                          else "sin_ficha" if legible == "no tiene ficha" else "parcial")
                salida = ProyectoOut(alias=alias, kind=tipo, estado=estado,
                                     faltan=list(faltan))
                self.assertIn(salida.estado, ("sin_ficha", "parcial", "completa"))
                self.assertIsInstance(salida.faltan, list)

    def test_un_proyecto_sin_tipo_no_inventa_tipo(self) -> None:
        from app.fichas import secciones_que_faltan
        tipo, legible, _ = secciones_que_faltan("compra-unida")
        self.assertEqual(tipo, "")
        self.assertEqual(legible, "no tiene ficha")
