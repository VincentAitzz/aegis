"""Los endpoints del alta y de la ficha privada, probados como llamadas de verdad.

## Por qué HTTP y no llamadas a funciones
`alta.alta()` y `fichas.crear_privada()` ya tienen sus propios tests. Lo que solo
se ve por HTTP son tres cosas que el móvil depende y que una función no
comprueba:

- que la ruta **exista** con el método y el nombre exactos que la app pide;
- que **pida token** —esto lo cubre `test_puerta_http` de forma general, y aquí
  se comprueba que la excepción de lectura no se aplicó por error;
- que la ruta privada **no** se cuelgue de la pública por un prefijo mal puesto,
  que es el fallo clásico al añadir `/fichas/{alias}/privada` debajo de
  `/fichas/{alias}`.

## Lo que no se prueba
El install en el teléfono. Eso es la puerta de `docs/runbook.md` §4, y depende
de que el teléfono esté en la tailnet.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402


class _Cliente(unittest.TestCase):
    """Cliente con una llave puesta, para no pelearse con el token en cada test."""

    def setUp(self) -> None:
        from app import main as main_mod
        self.main_mod = main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        self.addCleanup(setattr, main_mod.settings, "aegis_api_key", original)
        self.c = TestClient(main_mod.app)
        self.headers = {"X-Aegis-Token": "clave-de-prueba"}


class TestLaPuertaDelAlta(_Cliente):
    def test_el_alta_sin_llave_es_401(self) -> None:
        r = self.c.post("/proyectos", json={"alias": "x-nuevo", "area": "apps",
                                            "kind": "encargo"})
        self.assertEqual(401, r.status_code)

    def test_la_privada_sin_llave_es_401(self) -> None:
        """Los datos del cliente no se leen desde otro dispositivo de la tailnet."""
        r = self.c.get("/fichas/recepcion-persa/privada")
        self.assertEqual(401, r.status_code)


class TestLasRutasExisten(_Cliente):
    """Los nombres exactos que la app va a pedir. Un 404 aquí es un 404 en el móvil."""

    def test_get_proyectos_sigue_siendo_lectura_abierta(self) -> None:
        """El alta no puede cerrar el inventario que la app lee antes de tener llave."""
        r = self.c.get("/proyectos")
        self.assertEqual(200, r.status_code)
        self.assertIn("proyectos", r.json())

    def test_la_ruta_privada_no_cae_en_la_publica(self) -> None:
        """`/fichas/{alias}/privada` no puede resolverse como `/fichas/{alias}`.

        Si el orden o el patrón estuvieran mal, el segmento `privada` se
        interpretaría como parte del alias y la respuesta sería la ficha pública
        —que es justo lo contrario de lo que se pidió, y sin error visible.
        """
        r = self.c.get("/fichas/recepcion-persa/privada", headers=self.headers)
        self.assertEqual(200, r.status_code)
        cuerpo = r.json()
        self.assertIn("texto", cuerpo)
        self.assertEqual("recepcion-persa", cuerpo["alias"])
        self.assertNotEqual(
            self.c.get("/fichas/recepcion-persa", headers=self.headers).json()["texto"],
            cuerpo["texto"],
            "la ruta privada devolvió la ficha pública")

    def test_la_ruta_privada_de_un_alias_fantasma_es_404(self) -> None:
        r = self.c.get("/fichas/no-existe-este/privada", headers=self.headers)
        self.assertEqual(404, r.status_code)


class TestElAltaPorHttp(_Cliente):
    """El alta completa, con las rutas de escritura parcheadas a un tmpdir."""

    def setUp(self) -> None:
        super().setUp()
        from app import alta as alta_mod, fichas, projects
        import tempfile
        from pathlib import Path
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
        # Se guarda **todo**, no solo lo de código: los proyectos del registro
        # también son estado global, y un `_DATOS.clear()` que no se restaura
        # borra `data-sending` para los tests que vengan después. Pasaba
        # desapercibido porque el síntoma (un `medir_base` que responde «no está
        # en el registro») está en otro fichero.
        # `_DATOS` es un `set` de alias, no un mapa: `dict()` sobre él revienta.
        self.codigo = dict(projects.PROJECTS)
        self.datos = set(projects._DATOS)
        for alias in list(projects._DATOS):
            projects.PROJECTS.pop(alias, None)
        projects._DATOS.clear()

        def _restaurar() -> None:
            projects.PROJECTS.clear()
            projects.PROJECTS.update(self.codigo)
            projects._DATOS.clear()
            projects._DATOS.update(self.datos)
        self.addCleanup(_restaurar)

    def test_alta_crea_carpeta_registro_y_las_dos_fichas(self) -> None:
        from app import fichas
        r = self.c.post("/proyectos", headers=self.headers, json={
            "alias": "encargo-http", "area": "apps", "kind": "encargo",
            "nombre": "Encargo por HTTP", "alcance": "Una cosa concreta.",
        })
        self.assertEqual(200, r.status_code, r.text)
        cuerpo = r.json()
        self.assertEqual("encargo-http", cuerpo["alias"])
        self.assertEqual("encargo", cuerpo["tipo"])
        self.assertTrue((self.tmp / "apps" / "encargo-http").is_dir())
        self.assertTrue((self.registro / "encargo-http.json").is_file())
        self.assertTrue(fichas.ficha_path("encargo-http").is_file())
        self.assertTrue(fichas.privada_path("encargo-http").is_file())

    def test_devuelve_las_secciones_que_faltan(self) -> None:
        """El móvil pinta «te faltan estas»; sin esto solo puede decir «se creó»."""
        r = self.c.post("/proyectos", headers=self.headers, json={
            "alias": "encargo-http", "area": "apps", "kind": "encargo",
        })
        self.assertEqual(200, r.status_code, r.text)
        cuerpo = r.json()
        self.assertNotEqual([], cuerpo["faltan"])
        self.assertIn("Qué problema resuelve", cuerpo["faltan"])

    def test_un_alias_invalido_es_400_con_el_motivo(self) -> None:
        """422 sería un error de validación genérico; aquí el motivo está escrito
        para la persona que está rellenando el formulario."""
        r = self.c.post("/proyectos", headers=self.headers, json={
            "alias": "Mal Alias Con Espacios", "area": "apps", "kind": "encargo",
        })
        self.assertEqual(400, r.status_code)
        self.assertIn("alias", r.json()["detail"].lower())

    def test_un_tipo_invalido_es_400(self) -> None:
        r = self.c.post("/proyectos", headers=self.headers, json={
            "alias": "encargo-http", "area": "apps", "kind": "inventado",
        })
        self.assertEqual(400, r.status_code)

    def test_alta_no_concede_permiso_de_escritura(self) -> None:
        """Crear el proyecto y poder escribir en él son dos decisiones distintas.

        La segunda además sigue exigiendo verificador declarado, así que un alta
        sin `verificar` deja el proyecto en lectura, y eso es lo correcto.

        ## Por qué esto mira el almacén y **no** llama a `decide`
        Porque `decide()` sin `almacen_` escribe en el almacén **real**, y eso
        dejó 31 aprobaciones de `ficha_write` falsas en el móvil de quien esto
        escribe. Este test se ejecutó 31 veces y cada una dejó una.

        La lección está en `tests/test_registro.py` y en la de A-103: un test que
        toca estado global tiene que aislarlo. Aquí aislarlo era facilísimo —
        `almacen()` devuelve el almacén— y no se hizo. El síntoma apareció días
        después en la pantalla de Ahora de un móvil, sin ninguna relación visible
        con este test.
        """
        from app import autonomy
        self.c.post("/proyectos", headers=self.headers, json={
            "alias": "encargo-http", "area": "apps", "kind": "encargo",
        })
        escribibles = autonomy.almacen().proyectos()
        self.assertNotIn(
            "encargo-http", escribibles,
            "el alta concedio escritura por su cuenta: crear el proyecto y poder "
            "escribir en él son dos decisiones distintas")


class TestLaPrivadaPorHttp(_Cliente):
    """Escribir la ficha comercial: lo que el móvil manda y el prompt recibe."""

    def setUp(self) -> None:
        super().setUp()
        from app import fichas, projects
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "apps").mkdir()
        for attr, valor in (("FICHAS_DIR", self.tmp / "fichas"),
                            ("PRIVADAS_DIR", self.tmp / "priv")):
            patcher = mock.patch.object(fichas, attr, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(projects, "PROJECTS", dict(projects.PROJECTS))
        patcher.start()
        self.addCleanup(patcher.stop)
        # `root` como `Path`: `_safe_resolve` llama a `.resolve()`, y un `str`
        # ahí revienta con un AttributeError que no dice nada del contexto.
        projects.PROJECTS["prueba-http"] = mock.Mock(
            root=self.tmp / "apps" / "prueba-http")
        self.addCleanup(projects.PROJECTS.pop, "prueba-http", None)

    def test_se_escribe_y_luego_se_lee(self) -> None:
        contenido = "## Cliente y contacto\n\nPersona de prueba, en persona."
        r = self.c.post("/fichas/prueba-http/privada", headers=self.headers,
                        json={"contenido": contenido})
        self.assertEqual(200, r.status_code, r.text)
        leida = self.c.get("/fichas/prueba-http/privada", headers=self.headers).json()
        self.assertEqual(contenido, leida["texto"])
        self.assertTrue(leida["existe"])

    def test_una_plantilla_sin_escribir_no_rompe(self) -> None:
        """Si no hay privada, `GET` responde con `existe: false` y texto vacío.

        Un 404 haría que el móvil no pudiera abrir el editor para crearla, que es
        justo el primer uso del flujo.
        """
        leida = self.c.get("/fichas/prueba-http/privada", headers=self.headers).json()
        self.assertFalse(leida["existe"])
        self.assertEqual("", leida["texto"])

    def test_el_texto_llega_al_prompt(self) -> None:
        """El motivo de escribirla: si no llega al prompt, no sirve de nada."""
        self.c.post("/fichas/prueba-http/privada", headers=self.headers, json={
            "contenido": "## Modelo de cobro\n\nPrecio cerrado, dos pagos.",
        })
        from app import fichas
        # La privada se inyecta **al final** de `context_for`, y solo si la
        # publica existe: sin ficha no hay contexto que montar. Por eso este
        # test escribe una publica mínima también, que es el estado real del
        # proyecto una vez creado.
        fichas.FICHAS_DIR.mkdir(parents=True, exist_ok=True)
        fichas.ficha_path("prueba-http").write_text(
            "---\nkind: encargo\n---\n\n## Qué problema resuelve\n\nAlgo.\n",
            encoding="utf-8")
        ctx = fichas.context_for("prueba-http")
        self.assertIn("Precio cerrado", ctx)
        self.assertIn("no lo nombres ni lo repitas", ctx)

    def test_un_secreto_en_la_privada_se_rechaza(self) -> None:
        """Mismo guardarraíl que el resto de escrituras, también en lo comercial."""
        r = self.c.post("/fichas/prueba-http/privada", headers=self.headers, json={
            # La cadena se **construye en runtime**, no se escribe literal. Motivo
        # medido: `test_guardrails` abre el código real del repo y le pasa
        # el escáner, así que una credencial de mentira escrita en el fichero
        # hace fallar *otro* test — el guardarraíl acabaría tapanado su
        # propio test para poder probar el guardarraíl.
        # Y este es el caso real: en una ficha privada es exactamente donde
        # alguien pegaría la connection string del cliente.
        "contenido": "## Base de datos\n\npostgresql://usuario:" + "clave" + "@host/db",
        })
        self.assertEqual(400, r.status_code)
        self.assertIn("denegado", r.json()["detail"].lower())

    def test_un_contenido_vacio_es_422(self) -> None:
        """El modelo de cuerpo exige `min_length=1`: un fichero vacío se traga el
        nombre del cliente sin avisar."""
        r = self.c.post("/fichas/prueba-http/privada", headers=self.headers,
                        json={"contenido": ""})
        self.assertEqual(422, r.status_code)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

class TestPlantillasDeFicha(_Cliente):
    """Qué secciones hay que escribir, y de dónde sale esa lista."""

    def test_las_secciones_salen_del_disco(self) -> None:
        from app import fichas
        r = self.c.get("/fichas/plantillas", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        d = r.json()
        # La lista **es** `SECCIONES_POR_TIPO`. Si este test pasa y aun así el
        # móvil no muestra una sección, el problema está en el móvil y no en
        # una copia desincronizada.
        self.assertEqual(fichas.SECCIONES_POR_TIPO, d["secciones"])
        self.assertEqual(list(fichas.TIPOS), d["tipos"])

    def test_la_privada_trae_sus_secciones(self) -> None:
        from app import fichas
        r = self.c.get("/fichas/plantillas", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        d = r.json()
        self.assertIn("Cliente y contacto", d["privada"])
        self.assertIn("Modelo de cobro", d["privada"])
        # Y sale de la plantilla, no de una lista en Python.
        esperadas = list(fichas.parse("_p", fichas.plantilla_privada()).secciones)
        self.assertEqual(esperadas, d["privada"])

    def test_no_pide_nada_de_lectura_sin_llave(self) -> None:
        """Las secciones no son datos tuyos, pero la lista de proyectos tampoco
        está abierta y esta va con los proyectos."""
        r = self.c.get("/fichas/plantillas")
        self.assertEqual(401, r.status_code)


class TestSeccionesParseadas(_Cliente):
    """El mapa de secciones, que es lo que permite prellenar el formulario."""

    def test_la_ficha_publica_trae_sus_secciones(self) -> None:
        r = self.c.get("/fichas/recepcion-persa", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        d = r.json()
        self.assertIn("Qué problema resuelve", d["secciones"])
        self.assertIn("Cómo se verifica", d["secciones"])
        self.assertEqual(d["faltan"], [s for s in d["secciones"]
                                       if s not in d["escritas"]],
                         msg="«escritas» debe ser el complement exacto de «faltan»")

    def test_la_privada_trae_sus_secciones_tambien(self) -> None:
        r = self.c.get("/fichas/recepcion-persa/privada", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        d = r.json()
        self.assertIn("Cliente y contacto", d["secciones"],
                      msg='la plantilla tiene que llegar parseada o el '
                          'formulario no puede prellenar')
        # Sin escribir nada, nada está escrito: es la diferencia entre «existe»
        # y «tiene datos», que es justo la que un formulario necesita.
        self.assertEqual([], d["escritas"])
