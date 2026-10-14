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
        # `PROJECTS` mezcla dos cosas: los proyectos **declarados en código**
        # (aegis, portafolio…) y los que vivienda en `registro/`. Los segundos se
        # quitan para el test, y los primeros se dejan: son frontera de seguridad
        # y un test que los borrara estaría comprobando un sistema que no existe.
        #
        # Se quitan por una razón medida: el alta de prueba de un alias que
        # existe de verdad en el workspace fallaba con "'acme' ya está
        # registrado" y parecía un fallo del alta. Un test que depende de lo que
        # hay vivo en el disco no es un test.
        # Se guardan los dos: `PROJECTS` es el mapa y `_DATOS` el `set` de alias que
        # vienen del disco. Vaciar cualquiera sin restaurarlo lo deja roto para
        # los tests siguientes —el síntoma aparece en otro fichero: un
        # `medir_base` que de pronto responde «no está en el registro»— y por
        # eso costaba atribuir el fallo a quien lo causaba.
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


class TestVerificadorEnElAlta(_WorkspaceTemporal):
    """Un proyecto recién dado de alta tiene que poder marcado para escritura.

    Sin verificador en el registro, `POST /autonomy/{alias}` responde 409: el
    proyecto existe, Aegis lo lee, y no hay forma de darle permiso de escribir.
    El alta podía terminar, con éxito, en un proyecto inútil para trabajar.
    """

    def test_el_json_declara_el_verificador(self) -> None:
        alta_mod.alta("acme", "apps", "encargo", verificar=(
            '{"check": ["python3 -m compileall -q ."], "test": ["pytest -q"]}'))
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertEqual(entrada["verify"],
                         {"check": ["python3 -m compileall -q ."], "test": ["pytest -q"]})
        # Y el puente lo ve sin reiniciar: sin esto la primera escritura falla.
        self.assertIn("acme", projects.PROJECTS)
        self.assertIn("test", projects.PROJECTS["acme"].verify)

    def test_el_saludo_dice_que_ya_se_puede_escribir(self) -> None:
        salida = alta_mod.alta("acme", "apps", "encargo", verificar='{"test": ["pytest -q"]}')
        self.assertIn("Verificador declarado", salida)
        self.assertIn("/autonomy/acme", salida)

    def test_sin_verificador_lo_dice_en_vez_de_callarse(self) -> None:
        salida = alta_mod.alta("acme", "apps", "encargo")
        self.assertIn("SIN verificador declarado", salida)

    def test_una_nota_sigue_siendo_una_nota(self) -> None:
        """Retrocompatible: lo que no empieza por `{` era texto libre."""
        alta_mod.alta("acme", "apps", "encargo", verificar="se mira a mano")
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertEqual(entrada["note"], "se mira a mano")
        self.assertNotIn("verify", entrada)

    def test_un_verificador_ilegible_se_rechaza(self) -> None:
        with self.assertRaises(AltaInvalida) as cm:
            alta_mod.alta("acme", "apps", "encargo", verificar='{"check": ')
        self.assertIn("ilegible", str(cm.exception))
        self.assertFalse((self.registro / "acme.json").exists())

    def test_listas_vacias_no_dejan_ruido(self) -> None:
        alta_mod.alta("acme", "apps", "encargo", verificar='{"check": [], "test": []}')
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertNotIn("verify", entrada)

    def test_los_dos_argumentos_planos_declaran_el_verificador(self) -> None:
        """La forma que usa el modelo.

        Con un JSON embebido en una cadena el modelo lo emitía como objeto en una
        llamada y como texto en la siguiente: los argumentos dejaban de coincidir
        con los aprobados y el token nunca casaba. Dos cadenas planas se repiten
        iguales.
        """
        from app.mcp_ops import project_create
        salida = project_create("acme", "apps", "producto",
                                verificar_check="tsc --noEmit, dart format --set-exit-if-changed .",
                                verificar_test="vitest run")
        self.assertIn("Verificador declarado", salida)
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertEqual(entrada["verify"], {
            "check": ["tsc --noEmit", "dart format --set-exit-if-changed ."],
            "test": ["vitest run"]})

    def test_un_verificador_plano_vacio_no_inventa(self) -> None:
        from app.mcp_ops import project_create
        project_create("acme", "apps", "producto")
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertNotIn("verify", entrada)

    def test_la_entrada_declara_si_misma_si_tiene_base(self) -> None:
        """El contrato del registro (test_neon) lo exige en todas las entradas.

        Un alta nueva sin `db` pasaba los tests del módulo y rompía el de la
        frontera: los tests de una cosa y los de su frontera tienen que leer el
        mismo contrato, no dosemplos distintos del mismo fichero.
        """
        from app.mcp_ops import project_create
        project_create("acme", "apps", "producto", db="neon")
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertEqual(entrada["db"], "neon")

    def test_db_vacio_significa_que_no_se_sabe(self) -> None:
        from app.mcp_ops import project_create
        project_create("acme", "apps", "producto")
        entrada = json.loads((self.registro / "acme.json").read_text(encoding="utf-8"))
        self.assertIn("db", entrada)
        self.assertEqual(entrada["db"], "")


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
        """Un `registro/aegis.json` no puede sustituir la entrada de Python.

        ## Por qué se compara con `entorno.RAIZ` y no con una ruta literal
        Antes comparaba contra `/ruta/al/repo`, la ruta de la
        máquina donde se escribió. En un clon en otro sitio fallaba con un
        `PosixPath(...) != PosixPath('/home/usuario/...')` que no dice nada del
        comportamiento que se quiere comprobar (A-057). Lo que importa no es la
        ruta, es que el registro no la cambie.
        """
        from app import entorno
        raiz_antes = projects.PROJECTS["aegis"].root
        verif_antes = dict(projects.PROJECTS["aegis"].verify)

        self.escribir("aegis", {"alias": "aegis", "area": "apps", "kind": "encargo"})
        reload()

        self.assertEqual(projects.PROJECTS["aegis"].root, raiz_antes)
        self.assertEqual(projects.PROJECTS["aegis"].root, entorno.RAIZ,
                         "la raíz del repo se deriva del propio repo")
        self.assertEqual(projects.PROJECTS["aegis"].verify, verif_antes,
                         "el registro no puede quitarle el verificador a un "
                         "proyecto declarado en Python: sin verificador no hay "
                         "autonomía, y eso se decide en el código")

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
        """Sin ficha, tampoco hay tipo: y el motivo sale escrito.

        El tipo viene del frontmatter de la ficha. Si no hay ficha, inventar un
        tipo sería fabricar un dato —y el móvil lo muestra como si fuera verdad.
        Se usa `aegis` con la ruta de fichas vacía, así que el resultado no
        depende de qué proyectos tenga registrados quien ejecuta la suite.
        """
        import tempfile
        from pathlib import Path
        from unittest import mock
        from app import fichas
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fichas, "FICHAS_DIR", Path(d)):
                tipo, legible, _ = fichas.secciones_que_faltan("aegis")
        self.assertEqual(tipo, "")
        self.assertEqual(legible, "no tiene ficha")
