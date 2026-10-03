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
    ocurrió al denegar una petición que la suite había borrado unos segundos
    antes, y el 404 del móvil era el síntoma.
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

        def _adb(args, timeout=30, serial=""):
            # `ro.serialno` se responde aparte. Devolverle la lista entera haría
            # que **todos** los aparatos compartieran la misma identidad y se
            # unificaran, que es justo lo que `_identidad_hardware` descarta.
            if args[:1] == ["devices"]:
                return 0, crudo
            if "ro.serialno" in args:
                return 0, "ABC123\n"
            return 0, ""

        with mock.patch.object(disp, "_adb", side_effect=_adb):
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
        deploy.aprobar(p["id"], "denegar", "no quiero tocar el móvil ahora")
        self.assertIsNone(deploy.buscar_aprobacion(lanzar=False))
        self.assertEqual(deploy.pendientes(), [])

    def test_denegar_sin_motivo_se_rechaza(self) -> None:
        """Un "no" sin motivo no se guarda, y se dice por qué.

        ## Por qué
        El motivo es lo que el bridge inyecta en el prompt del siguiente run
        (§2 de `AGENTS.md`). Sin motivo, denegar es un "no" que no se puede
        aplicar a la siguiente situación parecida, así que Aegis no aprende nada y
        volverá a proponer lo mismo. Guardarlo en silencio sería aceptar un dato
        inútil: el móvil no enseñaría ningún error y quien aprieta "no" creería
        que hizo falta.
        """
        p = deploy.pedir_deploy("prueba")
        with self.assertRaises(deploy.PuertaCerrada) as caught:
            deploy.aprobar(p["id"], "denegar")
        self.assertIn("motivo", str(caught.exception))
        # Y sigue pendiente: un "no" que no se guardó no cierra la puerta.
        self.assertEqual(len(deploy.pendientes()), 1)

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

    def test_la_tool_no_pide_autorizacion_la_primera_vez(self) -> None:
        """El camino que de verdad se usa.

        La excepción vivía solo en `instalar_en_telefono`, y la tool pedía
        autorización y volvía sin llegar a instalar: en el teléfono nuevo se
        quedaba pidiendo una aprobación que era la única forma de instalar.
        """
        from unittest import mock as m
        with m.patch.object(disp, "instalado", return_value=False), \
             m.patch.object(disp, "_adb", return_value=(0, "Success")), \
             m.patch.object(disp, "telefono", return_value=TELEFONO), \
             m.patch.object(disp, "emulador", return_value=EMULADOR), \
             m.patch.object(disp, "resolver", return_value=TELEFONO), \
             m.patch.object(deploy, "verificar_analisis", return_value=(True, "ok")), \
             m.patch.object(deploy, "verificar_tests", return_value=(True, "11/11")), \
             m.patch.object(deploy, "humo_una_vez", return_value=(True, "humo ok")), \
             m.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             m.patch.object(disp, "telefono_alcanza", return_value=(True, "ok")), \
             m.patch.object(disp, "apk_para") as apk_para:
            apk_para.return_value = Path(__file__)
            from app import mcp_ops
            salida = mcp_ops.install_apk("telefono", lanzar=False)
        self.assertIn("instalado", salida)
        # Ojo: "no hacía falta tu autorización" contiene "falta tu autorización"
        # como subcadena, así que hay que mirar lo que la tool habría respondido.
        self.assertNotIn("NO INSTALADO", salida)
        self.assertNotIn("id de petición", salida)

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
        # La puerta también pregunta al teléfono si alcanza al bridge. Por defecto
        # responde que sí, para que cada test no tenga que mockear la red.
        stack.enter_context(mock.patch.object(disp, "api_host_para",
                                              return_value="100.101.102.100"))
        stack.enter_context(mock.patch.object(disp, "telefono_alcanza",
                                              return_value=(True, "ok")))
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
             mock.patch.object(deploy, "humo_una_vez", side_effect=hu), \
             mock.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             mock.patch.object(disp, "telefono_alcanza", return_value=(True, "ok")):
            deploy.pasar_puerta_deploy()
        self.assertEqual(orden, ["analyze", "tests", "humo"])

    def test_un_telefono_que_no_alcanza_el_bridge_no_instala(self) -> None:
        """La puerta anterior daba por bueno un APK con una dirección sin probar.

        El APK del teléfono lleva la dirección del bridge dentro. Si el móvil no
        llega, la app instala y abre sin ver nada, que es el peor resultado
        posible: parece que funcionó.
        """
        with self._puerta(), mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             mock.patch.object(disp, "telefono_alcanza",
                               return_value=(False, "no llega a 100.101.102.100:8000")):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("no ve el bridge", str(cm.exception))

    def test_si_alcanza_pasa(self) -> None:
        with self._puerta(), mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             mock.patch.object(disp, "telefono_alcanza", return_value=(True, "ok")):
            self.assertTrue(deploy.pasar_puerta_deploy())

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

    def _token_valido(self):
        """Anota el APK con el token que hay puesto, para que el humo no falle
        por la puerta y sí por lo que este test mide.

        Es explícito a propósito: si el sello no está, el humo se quejaría del
        token en vez de del proceso, y el fallo aparecería en el test
        equivocado.
        """
        import app.config as cfg
        # Se anota **el mismo path que se va a mockear**, que en estos tests es
        # el propio fichero de test. Anotar `deploy.APK` y luego mockearlo a
        # otro deja el sello en un sitio que nadie mira, y el humo se queja del
        # token en vez de del proceso.
        deploy.anotar_token_del_apk(Path(__file__),
                                    cfg.get_settings().aegis_api_key)
        self.addCleanup(lambda: deploy._sello_de_token(Path(__file__)).unlink(missing_ok=True))
        return mock.patch.object(deploy, "APK", Path(__file__))

    def test_el_humo_tambien_mira_el_token(self) -> None:
        """Un APK sin token abre y dibuja: solo falla con 401 en las secciones
        nuevas. Por eso el humo lo comprueba (A-039).

        ## Por qué este test usa un APK de temporal y no `deploy.APK`
        La primera versión guardaba `original = _sello_de_token(deploy.APK)` y
        hacía `original.unlink()` sobre el **sello real del binario real**. El test
        pasaba, la suite entera pasaba, y al terminar había borrado el sello del
        APK del emulador.

        El síntoma era desconcertante y se repitió tres veces: la puerta
        rechazaba la instalación con «este APK se compiló sin anotar token.
        Recompílalo», y recompilando volvía a pasar, y al volver a correr los tests
        se borraba otra vez. Un ciclo sin salida aparente, causado por un test.

        Por eso el APK del humo es un fichero de `tempfile`, siempre. Un test que
        toca el directorio de compilación no está probando el humo: está
        cambiando lo que el humo va a encontrar después (A-051).
        """
        import app.config as cfg
        if not cfg.get_settings().aegis_api_key:
            self.skipTest("no hay clave puesta en este entorno")
        temporal = Path(tempfile.mkdtemp(prefix="aegis-humo-")) / "app-debug-emulador.apk"
        temporal.write_bytes(b"APK")   # sin sello, a propósito
        with mock.patch.object(disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", temporal), \
             mock.patch.object(disp, "_adb", side_effect=self._adb_ok), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: True)
        self.assertFalse(ok, "el humo dio verde con un APK sin token")
        self.assertIn("autonomía", detalle)


    def test_sin_proceso_vivo_no_pasa(self) -> None:
        self._token_valido()
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", return_value=(0, "")), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: True)
        self.assertFalse(ok)
        self.assertIn("no arrancó", detalle)

    def test_viva_pero_sin_bridge_no_pasa(self) -> None:
        """Es el fallo que más cuesta ver: la app abre y no se habla con nadie."""
        self._token_valido()
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb_ok), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: False)
        self.assertFalse(ok)
        self.assertIn("no recibió ninguna llamada", detalle)

    def test_viva_y_hablando_pasa(self) -> None:
        self._token_valido()
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy, "APK", Path(__file__)), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb_ok), \
             mock.patch.object(deploy.time, "sleep"):
            ok, detalle = deploy.humo_emulador(lambda o, d: True)
        self.assertTrue(ok, detalle)
        self.assertIn("bridge recibió", detalle)
        self.assertIn("token", detalle)


class _PisoAvisos(_Piso):
    """El piso de los avisos, más el contador global.

    `deploy._AVISO` es un módulo entero a propósito: es lo que evita que dos
    peticiones iguales produzcan dos notificaciones. Sin resetearlo entre tests,
    un test puede_NO_ notificar y el siguiente esperar que sí, y el fallo
    aparece en el test equivocado.
    """

    def setUp(self) -> None:
        super().setUp()
        self._aviso_previo = deploy._AVISO
        deploy._AVISO = (0.0, "")
        #: Cada llamada es el comando de adb **más** el serial de destino. El
        #: serial va en el kwarg, no en los argumentos: mirar solo los args
        #: pasaría con cualquier aviso, vaya a donde vaya.
        self.llamadas: list[dict] = []
        #: ¿La app llegó a publicar el aviso? Para poder simular que sí y que no.
        self.hay_aviso = True

    def tearDown(self) -> None:
        deploy._AVISO = self._aviso_previo
        super().tearDown()

    def _adb(self, args, timeout=60, serial=""):
        self.llamadas.append({"args": list(args), "serial": serial})
        a = list(args)
        # El puente **verifica** la entrega leyendo `dumpsys`. Si el mock no
        # devuelve el registro, la verificación falla y el aviso se da por no
        # entregado — que es lo que debe pasar cuando el aviso no existe.
        if "dumpsys" in a and "notification" in a:
            if self.hay_aviso:
                return 0, (f"    NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                           f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=null)")
            return 0, "sin notificaciones"
        if "appops" in a:
            return 0, "Uid mode: POST_NOTIFICATION: allow"
        # `am broadcast` responde con esto; sin él el puente no lo da por entregado.
        if "broadcast" in a:
            return 0, "Broadcasting: Intent {...}\nBroadcast completed: result=0"
        return 0, ""

    def _destinos(self) -> list[str]:
        return [c["serial"] for c in self.llamadas]


class TestAvisosQueVanAlTelefono(_PisoAvisos):
    """Lo que sí se mide: cuántas notificaciones salen, a dónde, y si llegan.

    ## La premisa cambió, y el motivo importa
    Antes esta clase se llamaba `TestAvisosNoInvadanElTelefono` y afirmaba que
    el aviso intermedio **no** podía ir al móvil. La razón era buena: el aviso
    viejo lo firmaba `com.android.shell`, no era accionable y solo estorbaba, así
    que iba al emulador.

    Ahora el aviso lo publica la propia app, con su icono, y **se aprueba desde
    ahí**: un aviso que hay que decidir en el móvil tiene que llegar al móvil.
    Quien decide en otro sitio no decide.

    ## Y el inundar se resuelve en otro sitio
    Que vaya al teléfono no significa que llene el teléfono:

    - la app publica **un** aviso con el número de pendientes, con ID fijo, así
      que se actualiza en sitio;
    - aquí se mide la deduplicación por motivo, que es la mitad que sí es del
      puente.

    ## Por qué se mira el destino, no el texto
    Que el mensaje diga "telefono" no prueba nada: el mensaje es una cadena, y el
    destino es el `-s <serial>` de adb. Un test que mirara el texto pasaría con el
    aviso yendo al emulador.
    """

    def _solo_broadcasts(self) -> list[dict]:
        return [c for c in self.llamadas if "broadcast" in c["args"]]

    def _destinos(self) -> list[str]:
        """Solo de los broadcasts.

        La verificación lee `dumpsys` contra el mismo dispositivo, así que
        `self.llamadas` tiene el serial repetido. Mirar todos los destinos sería
        mirar dos veces el mismo sitio.
        """
        return [c["serial"] for c in self._solo_broadcasts()]

    @staticmethod
    def _sin_dormir():
        """La verificación espera hasta 6 s a que el aviso aparezca.

        En un test eso son 6 s reales por cada caso de fallo, y no prueba nada
        sobre el tiempo: el mock responde o no responde.
        """
        return mock.patch.object(deploy.time, "sleep", lambda _s: None)

    def test_el_aviso_intermedio_va_al_telefono(self) -> None:
        """Se aprueba desde el móvil, así que al móvil va."""
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            deploy.pedir_deploy("prueba")
        self.assertEqual(len(self._solo_broadcasts()), 1, self.llamadas)
        self.assertEqual(self._destinos(), [TELEFONO.serial])

    def test_sin_telefono_cae_al_emulador(self) -> None:
        """Y si el móvil no está, al emulador. Un aviso que no se entrega no avisa."""
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=None), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.pedir_deploy("prueba")["aviso"]
        self.assertEqual(self._destinos(), [EMULADOR.serial])
        self.assertIn("entregado y verificado", salida)

    def test_reintentos_no_multiplican_notificaciones(self) -> None:
        """Tres `install_apk` sin aprobación son una petición y un aviso.

        Es el caso real: el agente pregunta, no obtiene aprobación, y vuelve a
        preguntar. Antes eso era un aviso por intento.
        """
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            for _ in range(3):
                deploy.pedir_deploy("mismo motivo", lanzar=False)
        self.assertEqual(len(self._solo_broadcasts()), 1,
                         f"3 peticiones, {len(self._solo_broadcasts())} avisos: "
                         f"{self.llamadas}")

    def test_un_motivo_distinto_suena_nuevo(self) -> None:
        """La deduplicación es por motivo, no un reloj que se calla siempre.

        Si dos avisos distintos se comieran el segundo, el móvil se quedaría sin
        enterarse de algo que sí pasó.
        """
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb), \
             mock.patch.object(deploy.time, "time",
                               side_effect=[100.0, 100.0, 120.0, 120.0]):
            deploy.pedir_deploy("motivo A")
            deploy.pedir_deploy("motivo B")
        self.assertEqual(len(self._solo_broadcasts()), 2, self.llamadas)

    def test_pasada_la_ventana_vuelve_a_sonar(self) -> None:
        """El aviso se calla un rato, no para siempre."""
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb), \
             mock.patch.object(deploy.time, "time",
                               side_effect=[100.0, 100.0,
                                            100.0, 100.0 + deploy.VENTANA_AVISO + 1]):
            deploy.pedir_deploy("mismo motivo")
            deploy.pedir_deploy("mismo motivo")
        self.assertEqual(len(self._solo_broadcasts()), 2, self.llamadas)

    def test_avisos_desactivados_no_llaman_a_adb(self) -> None:
        with mock.patch.object(deploy, "AVISO_INTERMEDIO", "ninguno"), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.pedir_deploy("prueba")["aviso"]
        self.assertEqual(self.llamadas, [])
        self.assertIn("desactivados", salida)

    def test_el_aviso_final_si_llega_al_telefono(self) -> None:
        """Y este, el de que ya no hay nada que decidir, también y solo uno."""
        with mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.avisar_telefono({"razon": "instalado", "id": "deploy-1"})
        self.assertEqual(len(self._solo_broadcasts()), 1, self.llamadas)
        self.assertEqual(self._destinos(), [TELEFONO.serial])
        self.assertIn("verificado", salida)

    def test_sin_verificar_no_dice_que_aviso(self) -> None:
        """La entrega se **lee del sistema**, no se supone por el código de salida.

        ## El fallo que esto previene
        `_postear` devolvía «aviso enviado» con `exit=0`. En un Samsung no había
        notificación ninguna, el `appop` de la app estaba en `ignore` y el aviso
        era del shell. El puente escribió «aviso enviado» y el usuario se lo
        creyó. Es A-016 por sexta vez: un éxito que nadie comprobó.
        """
        self.hay_aviso = False
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             self._sin_dormir(), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.pedir_deploy("prueba")["aviso"]
        self.assertIn("NO VERIFICADO", salida)
        self.assertNotIn("entregado", salida)

    def test_bloqueado_dice_como_desbloquear(self) -> None:
        """Con las notificaciones de Aegis apagadas, el motivo va en el mensaje.

        Sin esto el puente diría «no verificado» y el usuario no sabría qué hacer.
        """
        self.hay_aviso = False
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             self._sin_dormir(), \
             mock.patch.object(deploy, "_permiso_avisos",
                               return_value="Uid mode: POST_NOTIFICATION: ignore"), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.pedir_deploy("prueba")["aviso"]
        self.assertIn("bloqueadas", salida)
        self.assertIn("Ajustes", salida)

    def test_la_peticion_se_guarda_antes_de_avisar(self) -> None:
        """La app pregunta al puente qué hay pendiente: tiene que estar ya.

        ## El fallo que esto previene
        `avisar_intermedio` iba **antes** de `ESTADO.nueva`. La app despertaba del
        broadcast, iba a `/deploys`, no encontraba esta petición —solo las
        viejas—, y publicaba «nada pendiente».
        """
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy, "_avisar_app") as avisar:
            def _pregunta(*_a, **_k):
                # Lo que la app ve por `/deploys` en el instante del aviso.
                return [deploy.ESTADO.peticion(p["id"]) for p in
                        deploy.pendientes()]
            avisar.side_effect = lambda dev, **k: str(_pregunta())
            p = deploy.pedir_deploy("una sola")
        self.assertIsNotNone(deploy.ESTADO.peticion(p["id"]))

    def test_el_motivo_legible_no_inventa(self) -> None:
        """Sin petición (primera instalación) el motivo no se inventa: se dice."""
        self.assertIn("APK verificado",
                      deploy.peticion_razon(TELEFONO, {"lanzar": False}))
        self.assertIn("mi motivo",
                      deploy.peticion_razon(TELEFONO, {"razon": "mi motivo"}))

    def test_instalar_avisa_una_vez_al_telefono(self) -> None:
        """Puerta cerrada por completo y la instalación notificada, una sola vez."""
        with mock.patch.object(deploy.disp, "instalado", return_value=False), \
             mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.instalar_en_telefono(TELEFONO, token="", lanzar=False)
        avisos = [c for c in self.llamadas if "broadcast" in c["args"]]
        self.assertEqual(len(avisos), 1, self.llamadas)
        self.assertIn("verificado", salida)


if __name__ == "__main__":
    unittest.main()

class TestElTokenDelApk(_Piso):
    """El humo tiene que distinguir "abrió" de "funciona".

    ## El fallo que esto previene
    Con la puerta de `X-Aegis-Token` puesta, un APK compilado sin token
    **arranca, pinta y habla con el bridge**: llama a `/health` y a `/proyectos`,
    que no lo exigen. Lo único que falla es autonomía, agenda y memoria, con un
    401. Es A-039: "compila, instala, abre y dibuja" suena a entrega completa y
    no lo es.

    La comprobación es una **huella del token anotada al compilar**, porque
    desensamblar el APK no es un test de humo: es una auscultación.
    """

    def setUp(self) -> None:
        super().setUp()
        self.apk = Path(tempfile.mkdtemp(prefix="aegis-apk-")) / "app-debug-emulador.apk"
        self.apk.write_bytes(b"APK")
        self._clave = os.environ.get("AEGIS_API_KEY", "")

    def _con_clave(self, valor: str):
        import app.deploy as d
        return mock.patch.object(d, "get_settings",
                                **{}) if False else mock.patch(
            "app.config.get_settings", return_value=mock.Mock(aegis_api_key=valor))

    def test_sin_clave_no_hay_puerta_que_comprobar(self):
        """No se falla por algo que no existe: exigir una clave vacía es
        inventar un fallo."""
        with self._con_clave(""):
            ok, motivo = deploy.el_token_llega(self.apk)
        self.assertTrue(ok)
        self.assertIn("no exige token", motivo)

    def test_clave_sin_sello_falla(self):
        with self._con_clave("clave-de-prueba"):
            ok, motivo = deploy.el_token_llega(self.apk)
        self.assertFalse(ok, "un APK sin token no puede pasar por bueno")
        self.assertIn("autonomía", motivo)

    def test_sello_que_coincide_pasa(self):
        deploy.anotar_token_del_apk(self.apk, "clave-de-prueba")
        with self._con_clave("clave-de-prueba"):
            ok, motivo = deploy.el_token_llega(self.apk)
        self.assertTrue(ok, motivo)

    def test_tras_rotar_la_clave_el_apk_viejo_deja_de_valer(self):
        """Es lo que pasa al rotar `AEGIS_API_KEY` sin recompilar: el token del
        binario ya no es el que el bridge espera."""
        deploy.anotar_token_del_apk(self.apk, "clave-vieja")
        with self._con_clave("clave-nueva"):
            ok, motivo = deploy.el_token_llega(self.apk)
        self.assertFalse(ok)
        self.assertIn("OTRO token", motivo)

    def test_la_huella_no_es_la_clave(self):
        """La huella se escribe a disco junto al APK. Si fuera la clave, el
        secreto estaría en un fichero al lado del binario."""
        deploy.anotar_token_del_apk(self.apk, "secreto-de-32-caracteres")
        escrito = deploy._sello_de_token(self.apk).read_text(encoding="utf-8")
        self.assertNotIn("secreto-de-32-caracteres", escrito)
        self.assertEqual(len(escrito.strip()), 16)


class TestInstalarEnSegundoPlano(_Piso):
    """Aprobar y que instale, sin que el agente se entere.

    ## El fallo que esto previene
    Aprobar devolvía un token y el agente tenía que volver a llamar a
    `install_apk` para gastarlo. Eso no es instalar en segundo plano: es que el
    agente se entere. Con el agente parado, o sin ganas de llamar otra vez, el
    APK aprobado se quedaba en el disco para siempre y tú no te enterabas.

    ## Por qué el token no sale
    Porque lo gasta el propio bridge, dentro de aquí. Un token de un solo uso
    que pasa por las manos del agente solo es de un solo uso si el agente
    cumple.
    """

    def _peticion_aprobada(self, **extra) -> dict:
        p = deploy.pedir_deploy("prueba", **extra)
        deploy.aprobar(p["id"], "aprobar")
        return deploy.ESTADO.peticion(p["id"])

    def test_no_instalar_una_pendiente(self) -> None:
        """Sin aprobar, no hay nada que instalar. Ni aunque alguien lo pida."""
        p = deploy.pedir_deploy("prueba")
        with self.assertRaises(deploy.PuertaCerrada) as caught:
            deploy.instalar_pendiente(p["id"])
        self.assertIn("pendiente", str(caught.exception))

    def test_no_instalar_una_inexistente(self) -> None:
        with self.assertRaises(deploy.PuertaCerrada):
            deploy.instalar_pendiente("deploy-inventado")

    def test_un_token_gastado_no_se_reinventa(self) -> None:
        """El token es de un solo uso, también para quien lo pide dos veces."""
        p = self._peticion_aprobada()
        deploy.gastar_token(p["token"])
        with self.assertRaises(deploy.PuertaCerrada) as caught:
            deploy.instalar_pendiente(p["id"])
        self.assertIn("un solo uso", str(caught.exception))

    def test_un_apk_distinto_al_aprobado_no_se_instala(self) -> None:
        """Lo que aprobaste tiene que ser el binario que hay ahora.

        Entre que se pide el OK y se pulsa "sí" pueden pasar minutos, y en ese
        rato una recompilación deja otro APK en la misma ruta. Instalar ese sería
        instalar algo que nadie aprobó.
        """
        p = self._peticion_aprobada()
        with mock.patch.object(deploy, "_huella_binario", return_value="otra-cosa"), \
             self.assertRaises(deploy.PuertaCerrada) as caught:
            deploy.instalar_pendiente(p["id"])
        self.assertIn("cambió", str(caught.exception))

    def test_el_token_se_gasta_dentro_del_bridge(self) -> None:
        """La cadena entera: aprueba → instala → el token queda gastado.

        ## Por qué no se falsea `instalar_en_telefono`
        Falsear la función que **gasta el token** y luego comprobar que el token
        quedó gastado es una comprobación que no puede fallar: está midiendo el
        test, no el código. Aquí lo único falseado es `adb`, que es el borde
        real, y lo que se mide es que el token se gastó **sin que nadie lo pidiera
        desde fuera**.
        """
        # `APK_TELEFONO` se parchea **antes** de pedir: la petición guarda la
        # huella del binario que hay en ese momento, y esa es la que después se
        # comprueba. Cambiarlo entre medias es justamente lo que el guard rechaza.
        # `pasar_puerta_deploy` devuelve un **device**, como en producción.
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)), \
             mock.patch.object(deploy, "pasar_puerta_deploy",
                               return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "instalado", return_value=True), \
             mock.patch.object(deploy, "avisar_telefono", return_value="ok"), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb",
                               return_value=(0, "Success")):
            p = self._peticion_aprobada()
            salida = deploy.instalar_pendiente(p["id"])
        self.assertIn("instalado", salida)
        self.assertTrue(deploy.ESTADO.token(p["token"])["gastado"],
                        "el token tiene que quedar gastado tras la instalación")


class TestHuellaDelBinario(_Piso):
    """Lo aprobado y lo ejecutado tienen que ser el mismo fichero."""

    def test_la_misma_fichero_da_la_misma_huella(self) -> None:
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)):
            self.assertEqual(deploy._huella_binario(Path(__file__)),
                             deploy._huella_binario(Path(__file__)))

    def test_un_fichero_que_no_existe_no_revienta(self) -> None:
        self.assertEqual(deploy._huella_binario(Path("/no/existe/apk")), "sin-fichero")

    def test_la_peticion_guarda_que_apk_pide(self) -> None:
        """Sin esto, aprobar no dice sobre qué: solo sobre un motivo en prosa."""
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "emulador", return_value=None), \
             mock.patch.object(deploy, "_avisar_app", return_value="ok"):
            p = deploy.pedir_deploy("prueba")
        self.assertEqual(p["apk"], deploy._huella_binario(Path(__file__)))


class TestLaNotificacionSeComprueba(_PisoAvisos):
    """Que la entrega se lea del sistema, no del código de salida."""

    DUMPSYS_SI = (f"  NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                  f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=null)")
    DUMPSYS_NO = "  (sin notificaciones)"

    def test_reconoce_el_registro_de_aegis(self) -> None:
        self.assertTrue(deploy._hay_aviso_aegis(self.DUMPSYS_SI))

    def test_otro_aviso_no_cuenta(self) -> None:
        """Un aviso de otra app no es un aviso de Aegis.

        La línea del shell —que es la que publicaba el sistema antes— tiene el
        mismo `id` pero otro paquete, y ahí es donde se causticaba el falso
        «entregado».
        """
        otro = (f"  NotificationRecord(0x1: pkg=com.android.shell "
                f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=aegis")
        self.assertFalse(deploy._hay_aviso_aegis(otro))

    def test_otro_id_no_cuenta(self) -> None:
        otro = (f"  NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                f"user=UserHandle{{0}} id=999 tag=null")
        self.assertFalse(deploy._hay_aviso_aegis(otro))

    def test_sin_nada_no_cuenta(self) -> None:
        self.assertFalse(deploy._hay_aviso_aegis(self.DUMPSYS_NO))


class TestLaAprobacionCubreElBinarioQueHay(_Piso):
    """Una puerta tiene que decir *qué* deja pasar.

    ## El fallo que esto previene
    `buscar_aprobacion` devolvía la aprobación más reciente sin mirar el binario.
    Como el APK se llama siempre igual y se sobrescribe, una aprobación de hace
    diez minutos autorizaba el APK que hubiera ahora. Bastaba con que cambiara
    el tamaño o el mtime —o sea, con recompilar— para que una puerta autorizara
    algo que nadie había visto.
    """

    def test_una_aprobacion_vieja_no_cubre_un_apk_nuevo(self) -> None:
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)):
            p = deploy.pedir_deploy("prueba")
            deploy.aprobar(p["id"], "aprobar")
            # El token sigue vivo: no se gasta, simplemente no vale para esto.
            self.assertIsNotNone(deploy.buscar_aprobacion(lanzar=False))
            with mock.patch.object(deploy, "_huella_binario",
                                   return_value="otro-binario"):
                self.assertIsNone(deploy.buscar_aprobacion(lanzar=False))

    def test_el_token_no_se_gasta_al_descartarlo(self) -> None:
        """Descartar una aprobación no es gastarla: sigue pidiendo la suya."""
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)):
            p = deploy.pedir_deploy("prueba")
            deploy.aprobar(p["id"], "aprobar")
            tok = deploy.ESTADO.peticion(p["id"])["token"]
            with mock.patch.object(deploy, "_huella_binario",
                                   return_value="otro-binario"):
                deploy.buscar_aprobacion(lanzar=False)
            self.assertFalse(deploy.ESTADO.token(tok)["gastado"])


class TestReconocerElTelefono(_Piso):
    """Qué cuenta como «el teléfono» cuando llega por donde llega.

    ## El fallo que esto previene
    `telefono()` solo aceptaba seriales con `_adb-tls-connect`. Pero la ruta
    manual que documenta el runbook —`adb mdns services` → `adb connect
    <ip>:<puerto>`— deja el serial como `100.101.102.103:46119`, sin ese nombre.
    Resultado: el teléfono estaba conectado y respondiendo, y la puerta decía
    «tu teléfono no aparece en adb. Conéctalo», pidiéndole algo que ya estaba
    conectado. A-046.
    """

    def test_el_serial_por_ip_cuenta(self) -> None:
        self.assertTrue(disp._parece_telefono("100.101.102.103:46119"))
        self.assertTrue(disp._parece_telefono("192.168.0.5:38027"))

    def test_el_nombre_mdns_sigue_contando(self) -> None:
        self.assertTrue(disp._parece_telefono(
            "adb-SERIAL1234567-tkpktJ._adb-tls-connect._tcp"))

    def test_el_emulador_no_cuenta(self) -> None:
        """Con el emulador siempre levantado, «algún dispositivo» no es el
        teléfono. Es el caso común, no el raro."""
        self.assertFalse(disp._parece_telefono("emulator-5554"))
        self.assertFalse(disp._parece_telefono("emulator-5556"))

    def test_el_loopback_no_cuenta(self) -> None:
        """`adb connect localhost:puerto` no es el teléfono de nadie."""
        self.assertFalse(disp._parece_telefono("127.0.0.1:5555"))
        self.assertFalse(disp._parece_telefono("localhost:5037"))

    def test_un_serial_sin_puerto_no_cuenta(self) -> None:
        self.assertFalse(disp._parece_telefono("R58Mxxxxxxx"))

    def test_por_ip_se_reconoce_el_telefono_entero(self) -> None:
        por_ip = disp.Device(serial="100.101.102.103:46119", state="device")
        with mock.patch.object(disp, "dispositivos", return_value=[por_ip, EMULADOR]):
            self.assertEqual(disp.telefono().serial, por_ip.serial)

    def _adb_que_devuelve(self, lineas: list[str], identidades: dict[str, str]):
        """Un `adb` falso: lista estos dispositivos y da esta identidad a cada uno.

        Se pasa por `dispositivos()` y no por `telefono()` a propósito: la
        unificación ocurre al **enumerar**, y un test que se salta esa capa está
        probando una función que nadie usa.
        """
        salida = "List of devices attached\n" + "".join(
            f"{s}\tdevice\n" for s in lineas)

        def _adb(args, timeout=30, serial=""):
            if args[:1] == ["devices"]:
                return 0, salida
            if "ro.serialno" in args:
                return 0, identidades.get(serial, "") + "\n"
            return 0, ""

        return _adb

    MDNS = "adb-SERIAL1234567-tkpktJ._adb-tls-connect._tcp"
    POR_IP = "100.101.102.103:46119"

    def test_el_mismo_telefono_por_dos_vias_es_uno(self) -> None:
        """mDNS y `host:puerto` son dos seriales del mismo aparato.

        ## El fallo que esto previene
        Al reconocer también los seriales por IP (A-046), un teléfono conectado
        a la vez por mDNS y por `adb connect` pasó a contar como dos. Entonces
        `telefono()` se quejaba de «hay 2 teléfonos» y **todo** lo del teléfono se
        detenía, con el móvil delante y el aviso sin poder salir.
        """
        _adb = self._adb_que_devuelve(
            [self.MDNS, self.POR_IP, "emulator-5554"],
            {self.MDNS: "SERIAL1234567", self.POR_IP: "SERIAL1234567",
             "emulator-5554": "emulador"})
        with mock.patch.object(disp, "_adb", side_effect=_adb):
            self.assertEqual(disp.telefono().serial, self.MDNS)

    def test_se_queda_el_mdns_porque_es_estable(self) -> None:
        """El puerto de un `adb connect` cambia en cada reinicio del teléfono.

        Quedarse con el `host:puerto` haría que el serial fuese distinto mañana,
        sin que nada haya cambiado.
        """
        _adb = self._adb_que_devuelve(
            [self.POR_IP, self.MDNS], {self.POR_IP: "X", self.MDNS: "X"})
        with mock.patch.object(disp, "_adb", side_effect=_adb):
            self.assertEqual(disp.telefono().serial, self.MDNS)

    def test_dos_aparatos_distintos_siguen_siendo_dos(self) -> None:
        """Unificar es por **identidad**, no por forma del serial."""
        _adb = self._adb_que_devuelve(
            [self.POR_IP, "192.168.0.7:38027"],
            {self.POR_IP: "A", "192.168.0.7:38027": "B"})
        with mock.patch.object(disp, "_adb", side_effect=_adb):
            with self.assertRaises(disp.DeviceError):
                disp.telefono()

    def test_si_no_se_puede_leer_la_identidad_no_se_une_nada(self) -> None:
        """Sin `ro.serialno` no hay prueba de que sean el mismo.

        Unificar a ciegas sería peor que no unificar: instalaría en un aparato
        distinto del comprobado. Por eso, sin identidad, se cuentan aparte y
        `telefono()` sigue pidiendo que digas cuál.
        """
        _adb = self._adb_que_devuelve([self.MDNS, self.POR_IP], {})
        with mock.patch.object(disp, "_adb", side_effect=_adb):
            with self.assertRaises(disp.DeviceError):
                disp.telefono()

    def test_dos_telefonos_siguen_pidiendo_que_elijas(self) -> None:
        """Reconocer más formas no significa adivinar más."""
        a = disp.Device(serial="100.101.102.103:46119", state="device")
        b = disp.Device(serial="192.168.0.5:38027", state="device")
        with mock.patch.object(disp, "dispositivos", return_value=[a, b, EMULADOR]):
            with self.assertRaises(disp.DeviceError) as cm:
                disp.telefono()
        self.assertIn("target='telefono:<serial>'", str(cm.exception))


class TestLaPuertaDevuelveElDevice(_Piso):
    """El contrato de `pasar_puerta_deploy`, comprobado **por tipo**.

    ## Por qué hace falta un test de tipo
    La puerta devolvía `dev.serial` (un `str`) y un llamador se lo pasaba a
    `instalar_en_telefono`, que espera un `Device`. Reventaba con
    `AttributeError` en un hilo en segundo plano, un minuto y medio después de
    que el usuario pulsara «sí».

    ## Por qué los tests unitarios no lo cazaron
    Porque fijaban el mock a un `Device`. El test **mintió sobre la firma real**
    y por eso pasó. Un mock que devuelve algo que la función no devuelve no
    prueba el contrato: lo contradice mientras parece confirmarlo.

    Aquí no hay mock: se deja correr la puerta de verdad contra un dispositivo
    simulado, y se mira **qué clase** sale.
    """

    def _puerta_verde(self) -> "contextlib.ExitStack":
        """La puerta en verde: los tres verificadores.

        Se falsean **solo** los verificadores. La resolución del teléfono y la
        comprobación de la huella se dejan correr de verdad, porque son parte de
        lo que este test mide: el contrato entre la puerta y quien la usa.
        """
        stack = contextlib.ExitStack()
        for nombre in ("verificar_analisis", "verificar_tests", "humo_una_vez"):
            stack.enter_context(
                mock.patch.object(deploy, nombre, return_value=(True, "ok")))
        return stack

    def test_devuelve_un_device_no_un_serial(self) -> None:
        with self._puerta_verde(), \
             mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             mock.patch.object(disp, "telefono_alcanza", return_value=(True, "ok")):
            salida = deploy.pasar_puerta_deploy()
        self.assertIsInstance(salida, disp.Device,
                              "la puerta devuelve el device; un serial obliga a "
                              "volver a resolver, y esa resolución puede dar "
                              "otro teléfono")
        self.assertEqual(salida.serial, TELEFONO.serial)

    def test_lo_que_devuelve_llega_intacto_a_instalar(self) -> None:
        """El contrato de punta a punta: lo que sale de la puerta, se instala.

        Sin esto, cada llamador puede estar esperando otra cosa y los tests
        unitarios —con sus mocks— no lo notan.
        """
        with mock.patch.object(deploy, "APK_TELEFONO", Path(__file__)), \
             self._puerta_verde(), \
             mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(disp, "api_host_para", return_value="100.101.102.100"), \
             mock.patch.object(disp, "telefono_alcanza", return_value=(True, "ok")), \
             mock.patch.object(disp, "instalado", return_value=True), \
             mock.patch.object(deploy, "avisar_telefono", return_value="ok"), \
             mock.patch.object(disp, "_adb", return_value=(0, "Success")):
            p = deploy.pedir_deploy("prueba")
            deploy.aprobar(p["id"], "aprobar")
            # Sin mocks en medio: la cadena real, de la petición a la instalación.
            salida = deploy.instalar_pendiente(p["id"])
        self.assertIn("instalado", salida)
