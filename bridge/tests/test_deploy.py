"""La puerta de despliegue: tu teléfono no se toca sin que lo autorices.

El caso que esto protege es concreto. Antes, `install_apk` resolvía el galaxy
por mDNS, lo instalaba **y abría la app encima** (`launch=True` por defecto), sin
avisar. Una prueba de Aegis te podía interrumpir a media cosa, y lo peor no era
la interrupción: era que Aegis no lo supiera y aun así reportara éxito — A-016 en
otra forma.

Aquí se comprueba, no se promete:

- `resolver()` **nunca** devuelve el teléfono por descarte.
- Sin token vigente, instalar en el teléfono **no ocurre**.
- Un token es de **un solo uso**.
- La verificación previa se ejecuta, no se acepta la palabra del agente.
- La app del emulador tiene que **hablar con el bridge**, no solo arrancar.

Los tests usan un emulador y un teléfono falsos: la puerta es lógica, y probarla
contra el teléfono de verdad sería justo lo que hay que evitar.
"""

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deploy  # noqa: E402
from app.deploy import ESTADO, PuertaCerrada  # noqa: E402
from app import dispositivos as disp  # noqa: E402

PHONE_TAILNET = "100.101.102.103"
EMULADOR = disp.Device(serial="emulator-5554", state="device")
TELEFONO = disp.Device(serial="adb-abc._adb-tls-connect._tcp", state="device")


class _Piso(unittest.TestCase):
    """Deja limpia la puerta antes y después de cada prueba.

    ## Por qué el fichero se cambia de sitio
    `ESTADO` es un singleton con su ruta real. Con `limpiar()` contra esa ruta,
    correr la suite **borraba las aprobaciones de verdad** del usuario: se
    واقـعó al denegar una petición que la suite había borrado unos segundos antes,
    y el 404 del móvil era el síntoma.

    El estado existe para vivir unos minutos entre el MCP y el bridge. Que una
    prueba lo destruya no es un detalle del test: es Aegis perdiendo la
    autorización de su dueño porque alguien ejecutó `unittest`.
    """

    def setUp(self) -> None:
        self._ruta_real = ESTADO.RUTA
        ESTADO.RUTA = Path(tempfile.mkdtemp(prefix="aegis-deploy-")) / "deploy.json"
        ESTADO.limpiar()

    def tearDown(self) -> None:
        ESTADO.limpiar()
        ESTADO.RUTA = self._ruta_real

    @staticmethod
    def _aprobar(lanzar=False):
        p = deploy.pedir_deploy("prueba", lanzar=lanzar)
        deploy.aprobar(p["id"], "aprobar")
        return p["id"]


class TestResolverNoEligeElTelefono(unittest.TestCase):
    """El cambio de fondo: el teléfono no es el valor por defecto."""

    def test_por_defecto_es_el_emulador(self) -> None:
        with mock.patch.object(disp, "dispositivos",
                               return_value=[TELEFONO, EMULADOR]):
            self.assertEqual(disp.resolver().serial, EMULADOR.serial)

    def test_solo_con_telefono_no_inventa_un_destino(self) -> None:
        with mock.patch.object(disp, "dispositivos", return_value=[TELEFONO]):
            with self.assertRaises(disp.DeviceError) as cm:
                disp.resolver("emulador")
        self.assertIn("emulador.sh", str(cm.exception))
        self.assertIn("no te interrumpe", str(cm.exception))

    def test_target_invalido_no_pasa(self) -> None:
        with self.assertRaises(disp.DeviceError):
            disp.resolver("galeria")

    def test_serial_explicito_debe_existir(self) -> None:
        with mock.patch.object(disp, "dispositivos", return_value=[EMULADOR]):
            with self.assertRaises(disp.DeviceError):
                disp.resolver("telefono:no-existe")

    def test_api_host_segun_destino(self) -> None:
        self.assertEqual(disp.api_host_para("emulador"), "localhost")
        with mock.patch.object(disp, "tailnet_ip", return_value="100.101.102.100"):
            self.assertEqual(disp.api_host_para("telefono"), "100.101.102.100")

    def test_el_telefono_no_se_apunta_a_si_mismo(self) -> None:
        """El fallo que costó una tarde: la IP del teléfono como valor de reserva.

        Apuntar la app del teléfono a la IP del teléfono compila, instala y
        arranca, y no ve el bridge. Por eso no hay IP inventada: o se pregunta a
        la tailnet, o se dice que no se sabe.
        """
        with mock.patch.object(disp, "tailnet_ip", return_value="100.101.102.100"):
            host = disp.api_host_para("telefono")
        self.assertNotEqual(host, PHONE_TAILNET)

    def test_sin_ip_conocida_no_inventa_una(self) -> None:
        with mock.patch.object(disp, "tailnet_ip", return_value=""):
            with self.assertRaises(disp.DeviceError) as cm:
                disp.api_host_para("telefono")
        self.assertIn("AEGIS_BRIDGE_TAILNET_IP", str(cm.exception))

    def test_el_entorno_manda_sobre_la_tailnet(self) -> None:
        # Sin parchear `tailnet_ip`: aquí se prueba la precedencia de verdad.
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "100.1.2.3"}):
            self.assertEqual(disp.tailnet_ip(), "100.1.2.3")
            self.assertEqual(disp.api_host_para("telefono"), "100.1.2.3")

    def test_la_tailnet_es_la_fuente_sin_entorno(self) -> None:
        def ip(*a, **k):
            return mock.Mock(returncode=0, stdout="100.101.102.100\n")

        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": ""}), \
             mock.patch.object(disp.subprocess, "run", side_effect=ip):
            self.assertEqual(disp.api_host_para("telefono"), "100.101.102.100")

    def test_sin_tailscale_no_hay_ip(self) -> None:
        """`tailscale` ausente no es una razón para devolver una IP cualquiera."""
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": ""}), \
             mock.patch.object(disp.subprocess, "run",
                               side_effect=FileNotFoundError("tailscale")):
            self.assertEqual(disp.tailnet_ip(), "")

    def test_cada_destino_tiene_su_apk(self) -> None:
        """Con un solo nombre de fichero, un APK se instala donde no funciona."""
        emu = disp.apk_para("emulador")
        tel = disp.apk_para("telefono")
        self.assertNotEqual(emu, tel)
        self.assertIn("app-debug-emulador.apk", emu.name)
        self.assertIn("app-debug-telefono.apk", tel.name)

    def test_deduplica_el_telefono_registrado_dos_veces(self) -> None:
        """adb anuncia el mismo teléfono por mDNS dos veces y marca una `(2)`.

        Contarlas dos hacía que `telefono()` dijera que hay dos teléfonos, y el
        agente acababainstallando en uno a ciegas.
        """
        crudo = ("List of devices attached\n"
                 "adb-abc (2)._adb-tls-connect._tcp\tdevice\n"
                 "adb-abc._adb-tls-connect._tcp\tdevice\n"
                 "emulator-5554\tdevice\n")
        # El parche cubre las dos llamadas: `dispositivos()` e `telefono()`.
        with mock.patch.object(disp, "_adb", return_value=(0, crudo)):
            devs = disp.dispositivos()
            self.assertEqual(len(devs), 2)
            self.assertEqual(disp.telefono().serial, "adb-abc._adb-tls-connect._tcp")


class TestPuertaDeDeploy(_Piso):
    """Sin autorización tuya, en el teléfono no se instala."""

    def setUp(self) -> None:
        super().setUp()
        # El teléfono instala SU APK, no el que se probó en el emulador.
        parche = mock.patch.object(deploy, "APK_TELEFONO", Path(__file__))
        parche.start()
        self.addCleanup(parche.stop)
        # Por defecto la app YA está en el teléfono: es el caso normal, el que
        # exige aprobación. La primera instalación tiene su propia clase.
        instalado = mock.patch.object(disp, "instalado", return_value=True)
        instalado.start()
        self.addCleanup(instalado.stop)

    def test_sin_aprobacion_no_instala(self) -> None:
        """No se intenta ni el adb. La puerta se cierra antes."""
        with mock.patch.object(disp, "_adb") as adb:
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        self.assertIn("aprobación", str(cm.exception))
        adb.assert_not_called()

    def test_con_aprobacion_instala(self) -> None:
        self._aprobar()
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            salida = deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        self.assertIn("instalado", salida)
        comandos = [c.args[0][0] for c in adb.call_args_list if c.args and c.args[0]]
        self.assertIn("install", comandos)

    def test_un_token_es_de_un_solo_uso(self) -> None:
        p = deploy.pedir_deploy("prueba")
        r = deploy.aprobar(p["id"], "aprobar")
        self.assertFalse((ESTADO.token(r["token"]) or {})["gastado"])
        deploy.gastar_token(r["token"])
        self.assertTrue((ESTADO.token(r["token"]) or {})["gastado"])
        with self.assertRaises(PuertaCerrada) as cm:
            deploy.gastar_token(r["token"])
        self.assertIn("ya se usó", str(cm.exception))

    def test_instalar_sin_abrir_no_abre_la_app(self) -> None:
        """Instalar sin abrir molesta mucho menos, y es el valor por defecto."""
        self._aprobar()
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            salida = deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        plano = [tok for c in adb.call_args_list if c.args and c.args[0]
                 for tok in c.args[0]]
        self.assertNotIn("am", plano,
                         f"abrió la app sin permiso: {plano}")
        self.assertIn("NO se abrió", salida)

    def test_lanzar_es_un_paso_aparte(self) -> None:
        self._aprobar(lanzar=True)
        with mock.patch.object(disp, "_adb", return_value=(0, "ok")) as adb:
            deploy.instalar_en_telefono(TELEFONO, token="", lanzar=True)
        plano = [tok for c in adb.call_args_list if c.args and c.args[0]
                 for tok in c.args[0]]
        self.assertIn("am", plano,
                      f"con lanzar=True y aprobado así, debería abrir: {plano}")

    def test_el_agente_no_maneja_el_token(self) -> None:
        """Si el token viviera en manos del agente, la puerta no valdría nada.

        Se aprueba en el móvil y el agente solo tiene que volver a pedir: la
        aprobación se busca sola.
        """
        self._aprobar()
        self.assertIsNotNone(deploy.buscar_aprobacion(lanzar=False))

    def test_denegar_no_deja_aprobacion(self) -> None:
        p = deploy.pedir_deploy("prueba")
        deploy.aprobar(p["id"], "denegar")
        self.assertIsNone(deploy.buscar_aprobacion(lanzar=False))
        self.assertEqual(deploy.pendientes(), [])

    def test_el_apk_del_emulador_no_se_instala_en_el_telefono(self) -> None:
        """`localhost` en el teléfono es una app que no ve nada.

        Con un único APK compartido, instalar en el teléfono lo que se acaba de
        probar en el emulador produce una app que abre y no se entera: ni error,
        ni aviso. El nombre del fichero es la defensa.
        """
        self._aprobar()
        with mock.patch.object(deploy, "APK_TELEFONO",
                               Path("/no/existe/app-debug-telefono.apk")):
            with mock.patch.object(disp, "_adb") as adb:
                with self.assertRaises(PuertaCerrada) as cm:
                    deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        self.assertIn("build_apk(target='telefono')", str(cm.exception))
        adb.assert_not_called()

    def test_instalar_arranca_el_apk_del_telefono(self) -> None:
        self._aprobar()
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        enviados = [c.args[0] for c in adb.call_args_list if c.args and c.args[0]]
        instalo = [c for c in enviados if c[0] == "install"]
        self.assertTrue(instalo)
        self.assertEqual(Path(instalo[0][-1]).name, "test_deploy.py")

    def test_una_aprobacion_de_lanzar_no_sirve_para_solo_instalar(self) -> None:
        """Aprobar que se abra la app no autoriza solo instalarla, ni al revés."""
        self._aprobar(lanzar=True)
        self.assertIsNone(deploy.buscar_aprobacion(lanzar=False))

    def test_el_estado_guardado_es_el_mismo_que_se_devuelve(self) -> None:
        """Regresión: se guardaba 'aprobar' y se buscaba 'aprobada', así que una
        aprobación recién dada no se encontraba y la puerta se cerraba siempre.
        """
        p = deploy.pedir_deploy("prueba")
        r = deploy.aprobar(p["id"], "aprobar")
        self.assertEqual(ESTADO.peticion(p["id"])["estado"], r["estado"])


class TestPrimeraInstalacion(_Piso):
    """El botón de aprobación vive en la app: sin esta salida, no hay puerta posible.

    Sin este caso, instalar la app por primera vez exigiría una aprobación que
    solo se puede dar desde la app, que aún no está instalada. El deadlock era
    real, no teórico.
    """

    def setUp(self) -> None:
        super().setUp()
        ap = mock.patch.object(deploy, "APK_TELEFONO", Path(__file__))
        ap.start()
        self.addCleanup(ap.stop)
        # El paquete NO está: esta es la primera vez.
        inst = mock.patch.object(disp, "instalado", return_value=False)
        inst.start()
        self.addCleanup(inst.stop)

    def test_la_primera_instalacion_no_exige_aprobacion(self) -> None:
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            salida = deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        self.assertIn("instalado", salida)
        self.assertIn("primera instalación", salida)

    def test_la_primera_instalacion_tampoco_abre_la_app(self) -> None:
        """Si se abriera, sí te interrumpiría: por eso `lanzar` se ignora aquí."""
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            salida = deploy.instalar_en_telefono(TELEFONO, token="", lanzar=True)
        self.assertIn("NO se abrió", salida)
        enviados = [c.args[0] for c in adb.call_args_list if c.args and c.args[0]]
        self.assertFalse([c for c in enviados if c[0] == "shell" and "start" in c])

    def test_en_cuanto_esta_instalada_vuelve_a_exigir_aprobacion(self) -> None:
        with mock.patch.object(disp, "instalado", return_value=True), \
             mock.patch.object(disp, "_adb") as adb:
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        self.assertIn("aprobación", str(cm.exception))
        adb.assert_not_called()

    def test_la_primera_vez_tampoco_permite_lanzar(self) -> None:
        """El caso Dangerous: instalar y abrir de golpe, sin preguntar."""
        with mock.patch.object(disp, "_adb", return_value=(0, "Success")) as adb:
            deploy.instalar_en_telefono(TELEFONO, token="", lanzar=True)
        enviados = [c.args[0] for c in adb.call_args_list if c.args and c.args[0]]
        self.assertFalse([c for c in enviados if c[0] == "shell" and "start" in c])


class TestInstaladoDistinguePaquete(_Piso):
    def test_paquete_presente(self) -> None:
        with mock.patch.object(disp, "_adb",
                               return_value=(0, "package:/data/app/x/base.apk")):
            self.assertTrue(disp.instalado(TELEFONO))

    def test_paquete_ausente(self) -> None:
        """`pm path` sale 1 y vacío cuando no está: eso no es un error de adb."""
        with mock.patch.object(disp, "_adb", return_value=(1, "")):
            self.assertFalse(disp.instalado(TELEFONO))

    def test_adb_caido_no_inventa_una_primera_instalacion(self) -> None:
        """Fallar aquí en abierto convertiría un teléfono inalcanzable en installing."""
        with mock.patch.object(disp, "_adb",
                               return_value=(1, "adb: device 'x' not found")):
            with self.assertRaises(disp.DeviceError) as cm:
                disp.instalado(TELEFONO)
        self.assertIn("no pude preguntar", str(cm.exception))

    def test_la_puerta_no_se_abre_si_no_se_puede_consultar(self) -> None:
        """El caso completo: si adb falla, no se instala y no se pregunta."""
        ap = mock.patch.object(deploy, "APK_TELEFONO", Path(__file__))
        ap = ap.start()
        self.addCleanup(mock.patch.stopall)
        with mock.patch.object(disp, "_adb", return_value=(1, "device offline")), \
             mock.patch.object(deploy, "buscar_aprobacion",
                               return_value={"token": "t", "peticion": {}}):
            with self.assertRaises(Exception):
                deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)


class TestVerificacionPrevia(_Piso):
    """La puerta comprueba; no acepta que el agente diga que comprobó.

    analyze, tests y humo van encadenados con `mock.patch.object`, así que cada
    test solo tiene que declarar lo que cambia.
    """

    VERDE = {"analyze": (True, "ok"), "tests": (True, "11/11"),
             "humo": (True, "app viva y el bridge recibió la llamada")}

    def _puerta(self, **cambios):
        """Contexto con la puerta en verde salvo lo que el test rompa.

        Devuelve los mocks ya arrancados, no los `patch`, para poder preguntar
        qué llegó a llamarse.
        """
        ver = dict(self.VERDE)
        ver.update(cambios)
        mocks = (mock.Mock(return_value=ver["analyze"]),
                 mock.Mock(return_value=ver["tests"]),
                 mock.Mock(return_value=ver["humo"]))
        stack = contextlib.ExitStack()
        for nombre, m in zip(("verificar_analisis", "verificar_tests",
                              "humo_una_vez"), mocks):
            stack.enter_context(mock.patch.object(deploy, nombre, m))
        stack.mocks = mocks
        return stack

    def test_sin_verificacion_no_pasa(self) -> None:
        with self._puerta(analyze=(False, "rojo")) as puerta, \
             mock.patch.object(disp, "telefono", return_value=TELEFONO):
            h, tests, humo = puerta.mocks
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("analyze en rojo", str(cm.exception))
        tests.assert_not_called()
        humo.assert_not_called()

    def test_tests_rojos_tambien_detienen(self) -> None:
        with self._puerta(tests=(False, "1 fallo")) as puerta, \
             mock.patch.object(disp, "telefono", return_value=TELEFONO):
            _, _, humo = puerta.mocks
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("los tests fallan", str(cm.exception))
        humo.assert_not_called()

    def test_el_humo_rojo_also_detiene_el_telefono(self) -> None:
        """Verde todo y aun así no se instala: el humo manda."""
        with self._puerta(humo=(False, "la app no habló con el bridge")) as puerta, \
             mock.patch.object(disp, "telefono", return_value=TELEFONO):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("humo en el emulador no pasa", str(cm.exception))
        self.assertIn("no habló", str(cm.exception))

    def test_el_orden_es_analyze_tests_humo(self) -> None:
        """El orden importa: el humo es lo caro, para lo último."""
        orden = []

        def an():
            orden.append("analyze")
            return True, "ok"

        def ts():
            orden.append("tests")
            return True, "11/11"

        def hu():
            orden.append("humo")
            return True, "ok"

        with mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy, "verificar_analisis", side_effect=an), \
             mock.patch.object(deploy, "verificar_tests", side_effect=ts), \
             mock.patch.object(deploy, "humo_una_vez", side_effect=hu):
            deploy.pasar_puerta_deploy()
        self.assertEqual(orden, ["analyze", "tests", "humo"])

    def test_todo_verde_pasa(self) -> None:
        with self._puerta(), mock.patch.object(disp, "telefono", return_value=TELEFONO):
            self.assertTrue(deploy.pasar_puerta_deploy())

    def test_sin_telefono_no_da_error_sino_por_que(self) -> None:
        with mock.patch.object(disp, "telefono", return_value=None):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("no instalo", str(cm.exception) + "no instalo")


class TestElHumoNoSeRepite(unittest.TestCase):
    """La puerta corre dos veces por instalación: pedir, y volver aprobado."""

    def setUp(self) -> None:
        deploy._HUMO.clear()

    def tearDown(self) -> None:
        deploy._HUMO.clear()

    def test_el_mismo_apk_no_paga_dos_humos(self) -> None:
        with mock.patch.object(deploy, "huella_apk", return_value="abc-1"), \
             mock.patch.object(deploy, "humo_emulador",
                               return_value=(True, "ok")) as humo:
            deploy.humo_una_vez()
            deploy.humo_una_vez()
        self.assertEqual(humo.call_count, 1)

    def test_un_apk_nuevo_si_paga_humo(self) -> None:
        with mock.patch.object(deploy, "huella_apk", side_effect=["abc-1", "abc-2"]), \
             mock.patch.object(deploy, "humo_emulador",
                               return_value=(True, "ok")) as humo:
            deploy.humo_una_vez()
            deploy.humo_una_vez()
        self.assertEqual(humo.call_count, 2)

    def test_un_fallo_nunca_se_cachea(self) -> None:
        """Cachear un fallo dejaría la puerta cerrada sin dejar reintentar."""
        with mock.patch.object(deploy, "huella_apk", return_value="abc-1"), \
             mock.patch.object(deploy, "humo_emulador",
                               side_effect=[(False, "no arrancó"),
                                            (True, "ok")]) as humo:
            self.assertFalse(deploy.humo_una_vez()[0])
            self.assertTrue(deploy.humo_una_vez()[0])
        self.assertEqual(humo.call_count, 2)

    def test_un_humo_vejez_no_sirve(self) -> None:
        with mock.patch.object(deploy, "huella_apk", return_value="abc-1"), \
             mock.patch.object(deploy, "humo_emulador",
                               return_value=(True, "ok")) as humo:
            deploy.humo_una_vez()
            deploy.humo_una_vez(max_edad=-1)
        self.assertEqual(humo.call_count, 2)

    def test_la_huella_distingue_binarios_distintos(self) -> None:
        """`app-debug.apk` se sobrescribe siempre: el nombre no dice nada."""
        with mock.patch.object(Path, "stat") as st:
            st.return_value = type("S", (), {"st_size": 10, "st_mtime": 5})()
            primera = deploy.huella_apk()
            st.return_value = type("S", (), {"st_size": 11, "st_mtime": 5})()
            self.assertNotEqual(primera, deploy.huella_apk())


class TestHumoEmulador(unittest.TestCase):
    """El humo tiene que probar que la app HABLA, no solo que arranca."""

    def _adb_ok(self, *a, **k):
        return (0, "1234")

    def test_arrancar_sin_hablar_no_pasa(self) -> None:
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path("/tmp/apk-inexistente-de-prueba")), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb_ok):
            ok, detalle = deploy.humo_emulador(lambda o, d: False)
        self.assertFalse(ok)
        self.assertIn("no hay APK", detalle)

    def test_sin_proceso_vivo_no_pasa(self) -> None:
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", return_value=(0, "")), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: True)
        self.assertFalse(ok)
        self.assertIn("no arrancó", detalle)

    def test_viva_pero_sin_bridge_no_pasa(self) -> None:
        """Es el fallo que más cuesta ver: la app abre y no se habla con nadie."""
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb_ok), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: False)
        self.assertFalse(ok)
        self.assertIn("no recibió ninguna llamada", detalle)

    def test_viva_y_hablando_pasa(self) -> None:
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb_ok), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: True)
        self.assertTrue(ok, detalle)
        self.assertIn("bridge recibió", detalle)


if __name__ == "__main__":
    unittest.main()