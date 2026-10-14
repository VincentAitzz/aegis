"""El endpoint que sirve el APK, y las tres cosas que tiene que negarse a hacer.

## Qué se prueba
No es «devuelve el fichero», que es lo fácil. Es lo contrario, que es lo que
importa:

1. **No sirve un binario sin puerta.** Por la red, un APK sin comprobar es un
   APK sin comprobar pero además distribuido. El endpoint hereda las dos
   comprobaciones que ya usa `instalar_pendiente`, y en su orden: primero de
   dónde salió el fichero, después si pasó las pruebas.
2. **No se sirve cacheado.** Un APK cacheado por el Wi-Fi es instalar código
   viejo, que es el peor desenlace posible de una actualización. Los cachés de
   malla cachean por defecto, así que esto no es un riesgo teórico.
3. **`X-Aegis-Version` sale del propio APK**, no de `pubspec.yaml`. Es el dato
   con el que la app decide si hay versión nueva antes de descargar 50 MB, y sale
   del binario para que no pueda discrepar de lo que Android va a instalar.

## Y una cosa que este endpoint **no** hace
No instala. Bajar un fichero no es ejecutarlo: lo instala el diálogo del sistema
y lo autoriza la cola de aprobaciones. Si este endpoint instalara, la invariante
«nada irreversible sin OK» se podría saltar con una descarga.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402


class _Cliente(unittest.TestCase):
    def setUp(self) -> None:
        from app import main as main_mod
        self.main_mod = main_mod
        original = main_mod.settings.aegis_api_key
        main_mod.settings.aegis_api_key = "clave-de-prueba"
        self.addCleanup(setattr, main_mod.settings, "aegis_api_key", original)
        self.c = TestClient(main_mod.app)
        self.headers = {"X-Aegis-Token": "clave-de-prueba"}

    def _con_apk(self, nombre="app-release-telefono.apk", cuerpo=b"APK-FALSO"):
        """Parchea el APK a un fichero temporal, con sus dos sellos."""
        import tempfile
        from app import deploy as deploy_mod
        from app import dispositivos as disp

        self.tmp = Path(tempfile.mkdtemp())
        apk = self.tmp / nombre
        apk.write_bytes(cuerpo)

        patches = [
            mock.patch.object(disp, "apk_para", return_value=apk),
            mock.patch.object(deploy_mod, "APK_TELEFONO", apk),
            # La puerta se declara en verde: lo que se prueba aquí es que el
            # endpoint la **consulta**, no que la puerta sepa detectar un rojo.
            mock.patch.object(deploy_mod, "apk_desactualizado", return_value=""),
            mock.patch.object(deploy_mod, "apk_sin_verificar", return_value=""),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return apk


class TestElEndpointNiegaLoQueNoDebe(_Cliente):
    def test_sin_llave_es_401(self) -> None:
        """Servir un APK firmado es lo de más consecuencia que hace el bridge.

        Abierto, es «cualquiera en la LAN se baja un binario que Android acepta
        como Aegis».
        """
        self._con_apk()
        r = self.c.get("/apk/telefono")
        self.assertEqual(401, r.status_code)

    def test_no_esta_entre_las_lecturas_abiertas(self) -> None:
        """Que siga en la lista cerrada, y no por costumbre.

        `test_puerta_http` ya recorre las rutas comprobando la dependencia; este
        dice por qué esta en particular no debe abrirse nunca.
        """
        from app.main import LECTURAS_ABIERTAS
        self.assertNotIn("/apk/{base}", LECTURAS_ABIERTAS)

    def test_un_destino_inventado_es_404(self) -> None:
        self._con_apk()
        r = self.c.get("/apk/inventado", headers=self.headers)
        self.assertEqual(404, r.status_code)
        self.assertIn("destino desconocido", r.json()["detail"])

    def test_sin_apk_es_404_con_el_motivo(self) -> None:
        """El motivo dice qué hacer, no solo que falta.

        Un 404 sin explicación obliga a buscar el motivo a mano; con él, el
        siguiente paso es obvio.
        """
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        with mock.patch.object(disp, "apk_para", return_value=Path("/no/existe.apk")), \
             mock.patch.object(deploy_mod, "APK_TELEFONO", Path("/no/existe.apk")):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual(404, r.status_code)
        self.assertIn("build_apk", r.json()["detail"])

    def test_un_apk_desactualizado_no_se_sirve(self) -> None:
        """Está verificado y aun así no sirve: lo que se verificó fue *ese*
        fichero, y el código ya es otro."""
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_desactualizado",
                               return_value="el código cambió a las 12:04"), \
             mock.patch.object(disp, "apk_para", return_value=apk):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual(409, r.status_code)
        self.assertIn("12:04", r.json()["detail"])

    def test_el_motivo_tambien_va_en_cabecera_para_un_HEAD(self) -> None:
        """Un `HEAD` no tiene cuerpo, así que el `detail` no le llega a la app.

        ## Por qué esto importa
        La app pregunta con `HEAD`. Con el motivo solo en el `detail` —que es lo
        natural—, un `409` por APK viejo llegaba al móvil **sin texto**, y la
        pantalla enseñaba «el bridge no tiene un APK que servir todavía»: lo
        contrario de lo que pasaba, porque había un APK y lo que faltaba era
        recompilarlo. Un motivo que se pierde en el camino no es un motivo.
        """
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_desactualizado",
                               return_value="el código cambió"), \
             mock.patch.object(disp, "apk_para", return_value=apk):
            head = self.c.head("/apk/telefono", headers=self.headers)
            get = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual(409, head.status_code)
        self.assertIn("recompila", head.headers["x-aegis-motivo"])
        # Y el cuerpo del GET sigue diciendo lo mismo: la cabecera no sustituye
        # al `detail`, lo acompaña.
        self.assertEqual(409, get.status_code)
        self.assertIn("el código cambió", get.json()["detail"])
        # La cabecera es ASCII a propósito, y el motivo original lleva tilde.
        self.assertNotIn("ó", head.headers["x-aegis-motivo"])

    def test_el_motivo_no_se_pierde_al_volver_a_preguntar(self) -> None:
        """La app pregunta al abrir y vuelve a preguntar al volver de Ajustes.

        El motivo tiene que seguir ahí en la segunda: es el mismo 409, y quien
        acaba de cambiar el permiso del sistema es quien lo va a leer.
        """
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_desactualizado",
                               return_value="el código cambió"), \
             mock.patch.object(disp, "apk_para", return_value=apk):
            primera = self.c.head("/apk/telefono", headers=self.headers)
            segunda = self.c.head("/apk/telefono", headers=self.headers)
        self.assertEqual(primera.headers["x-aegis-motivo"],
                         segunda.headers["x-aegis-motivo"])

    def test_un_apk_sin_puerta_no_se_sirve(self) -> None:
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_sin_verificar",
                               return_value="analyze: 1 error"), \
             mock.patch.object(disp, "apk_para", return_value=apk):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual(409, r.status_code)
        self.assertIn("analyze", r.json()["detail"])

    def test_el_orden_es_origen_primero(self) -> None:
        """Desactualizado gana sobre sin-verificar.

        Un APK viejo que además no pasó la puerta son dos motivos, y el que
        ayuda más es el primero: no arregla nada pasar la puerta de un binario
        que ya no representa el código.
        """
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_desactualizado", return_value="viejo"), \
             mock.patch.object(deploy_mod, "apk_sin_verificar",
                               return_value="sin puerta"), \
             mock.patch.object(disp, "apk_para", return_value=apk):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertIn("viejo", r.json()["detail"])
        self.assertNotIn("sin puerta", r.json()["detail"])


class TestElEndpointSiSirve(_Cliente):
    def test_sirve_el_binario_con_lo_que_hace_falta(self) -> None:
        apk = self._con_apk(cuerpo=b"contenido-del-apk")
        r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(b"contenido-del-apk", r.content)
        self.assertEqual(
            "application/vnd.android.package-archive", r.headers["content-type"])

    def test_no_se_cachea(self) -> None:
        """Un APK cacheado por el Wi-Fi es instalar código viejo.

        Los cachés de malla cachean por defecto, así que sin `no-store` esto
        pasaría sin que nadie lo decidiera.
        """
        self._con_apk()
        r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertIn("no-store", r.headers.get("cache-control", ""))

    def test_lleva_etag_para_no_bajar_lo_que_ya_tiene(self) -> None:
        self._con_apk()
        r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertTrue(r.headers.get("etag"),
                        msg="sin ETag la app no puede saber que ya tiene el fichero")

    def test_la_version_sale_del_apk_y_no_del_registro(self) -> None:
        """Del binario, no de otro sitio.

        Es el número con el que la app decide si hay versión nueva antes de
        descargar 50 MB, y sale del fichero para que no pueda discrepar de lo que
        Android va a instalar.
        """
        from app import dispositivos as disp
        self._con_apk()
        with mock.patch.object(disp, "version_de", return_value=(7, "9.9.9")):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual("7", r.headers["x-aegis-version"])
        self.assertEqual("9.9.9", r.headers["x-aegis-version-name"])

    def test_el_sello_lo_puede_leer_la_app(self) -> None:
        """Del qué código salió, para que el móvil pueda decirlo con palabras."""
        from app import deploy as deploy_mod
        from app import dispositivos as disp
        apk = self._con_apk()
        deploy_mod.sello_de(apk).write_text("42a4d6d48e2e40f5\n", encoding="utf-8")
        with mock.patch.object(disp, "apk_para", return_value=apk):
            r = self.c.get("/apk/telefono", headers=self.headers)
        self.assertEqual("42a4d6d48e2e40f5", r.headers.get("x-aegis-sello"))

    def test_head_pregunta_la_version_sin_bajar_50_mb(self) -> None:
        """La app pregunta con `HEAD` antes de bajarse nada.

        Sin esto tendría que **empezar** la descarga para descubrir que ya tiene
        esa versión, y en una línea de datos son 50 MB por una respuesta que
        cabía en tres cabeceras.
        """
        self._con_apk()
        r = self.c.head("/apk/telefono", headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(b"", r.content, msg="un HEAD no puede traer el fichero")
        self.assertTrue(r.headers.get("x-aegis-version"))

    def test_head_rechaza_lo_mismo_que_get(self) -> None:
        """Las **mismas** reglas, y esta es la parte que no puede romperse.

        Si el `HEAD` colgar de otro sitio, o se olvidara de una comprobación,
        devolvería «hay versión» sobre un APK que el `GET` luego rechaza. La app
        enseñaría «descargar» y la descarga fallaría, sin explicación.
        """
        from app import deploy as deploy_mod

        apk = self._con_apk()
        with mock.patch.object(deploy_mod, "apk_desactualizado", return_value="el código cambió"), \
             mock.patch.object(deploy_mod, "apk_sin_verificar", return_value="analyze: 1 error"):
            # Las dosguards a la vez: el `HEAD` tiene que parar en la primera,
            # y eso da el mismo 409 que el `GET`.
            r = self.c.head("/apk/telefono", headers=self.headers)
        self.assertEqual(409, r.status_code)

    def test_head_sin_apk_es_404_igual_que_get(self) -> None:
        """Sin APK no hay nada que preguntar, y el motivo tiene que salir igual.

        El `409` del desactualizado y el `404` del inexistente son dos
        situaciones distintas para quien lee: uno se arregla recompilando, el
        otro compilando primero.
        """
        from app import dispositivos as disp
        import tempfile
        with mock.patch.object(disp, "apk_para", return_value=Path(tempfile.mkdtemp()) / "nada.apk"):
            self.assertEqual(404, self.c.head("/apk/telefono", headers=self.headers).status_code)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

class TestElPerfilDelBinarioQueSeMueve(unittest.TestCase):
    """El bug que cerrado puerta entera, y que vuelve si nadie lo ata.

    `build_apk` movía `app-debug.apk` —el nombre legacy— y en **release** Flutter
    escribe `app-release.apk`. El `if APK.exists()` era falso, `movido` se
    quedaba en `False`, y todo lo que va después se saltaba: **incluido anotar
    el token**, que es lo que la puerta exige después.

    El síntoma era del todo culposo del sitio equivocado: la puerta se cerraba
    diciendo «este APK se compiló sin anotar token», y el build sí lo anotaba,
    pero a un fichero que nunca se movió. Dos mensajes que apuntan a cosas
    distintas y solo una es verdad.
    """

    def test_apk_legacy_sigue_al_perfil(self) -> None:
        from app.dispositivos import apk_legacy
        self.assertEqual("app-debug.apk", apk_legacy("debug").name)
        self.assertEqual("app-release.apk", apk_legacy("release").name)

    def test_el_perfil_invalido_no_se_traga(self) -> None:
        from app.dispositivos import apk_legacy
        with self.assertRaises(ValueError):
            apk_legacy("inventado")

    #: Un token de mentira, declarado aquí para que el test no dependa de que la
    #: máquina tenga `AEGIS_API_KEY` en su `.env`.
    TOKEN_DE_PRUEBA = "clave-de-prueba"

    def test_build_apk_mueve_el_fichero_de_su_perfil(self) -> None:
        """Con el binario en el sitio que le toca, `movido` es True."""
        import tempfile
        from app import mcp_ops

        self.tmp = Path(tempfile.mkdtemp())
        self.release = self.tmp / "app-release.apk"
        self.release.write_bytes(b"apk-de-release")

        class _Proc:
            returncode = 0
            stdout = "Built app-release.apk"
            stderr = ""

        # `mcp_ops` captura `settings` **al importar**, así que parchear
        # `get_settings` no cambia lo que lee `build_apk`. Antes el test pasaba en
        # la máquina de quien lo escribió porque su `bridge/.env` traía
        # `AEGIS_API_KEY`, y fallaba en un clon limpio con «el APK sale sin
        # token»: verde por casualidad, no por el motivo que dice (A-057).
        with mock.patch.object(mcp_ops, "_run", return_value=_Proc()), \
             mock.patch.object(mcp_ops, "MOBILE", self.tmp), \
             mock.patch("app.dispositivos.apk_para",
                        lambda base, perfil="release": self.tmp / f"app-{perfil}-{base}.apk"), \
             mock.patch("app.dispositivos.apk_legacy",
                        lambda perfil="debug": self.tmp / f"app-{perfil}.apk"), \
             mock.patch.object(mcp_ops, "current_brand", return_value="0x00FFAA"), \
             mock.patch("app.mcp_ops.LEGACY_BRAND", "0x000000"), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(aegis_api_key=self.TOKEN_DE_PRUEBA)), \
             mock.patch.object(mcp_ops.settings, "aegis_api_key",
                               self.TOKEN_DE_PRUEBA), \
             mock.patch("app.deploy.verificar_analisis", return_value=(True, "limpio")), \
             mock.patch("app.deploy.verificar_tests", return_value=(True, "147 tests")), \
             mock.patch("app.deploy.verificar_binario", return_value=(True, "puerta ok")), \
             mock.patch("app.deploy.anotar_token_del_apk") as anotar, \
             mock.patch("app.mcp_ops._short_diff", return_value="sin cambios"):
            # El toolchain se da por presente **fuera** del bloque de mocks, y no
            # dentro: un comentario no se puede escribir en una continuación de
            # línea con `\`, que es donde viven esos mocks. Aquí se prueba que el
            # binario **se mueve**, no que `build_apk` sepa decir qué falta — eso
            # tiene su propio test, y en una máquina sin Flutter este fallaría
            # por un motivo que no es el suyo.
            with mock.patch("app.entorno.faltan", return_value=[]):
                salida = mcp_ops.build_apk("telefono")

        self.assertIn("app-release-telefono.apk", str(salida), )
        self.assertTrue((self.tmp / "app-release-telefono.apk").is_file())
        # El token se anotó: ese era el punto de todo.
        anotar.assert_called_once()
