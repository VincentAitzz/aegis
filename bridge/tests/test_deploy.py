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
        # El APK real se queda viejo en cuanto se toca `mobile/`, y `pedir_deploy`
        # **se niega a crear la petición** si lo está. Sin falsearlo aquí, media
        # suite se ponía roja cada vez que se editaba la app —que es lo más
        # corriente del mundo— y el fallo hablaba del sello, no de lo que el test
        # estaba mirando.
        #
        # El sello tiene su propia clase (`TestElApkCorrespondeAlCodigo`) y ahí se
        # llama a `apk_desactualizado` de verdad, sobre un proyecto de mentira. El
        # resto prueba puertas y avisos, y ninguno de los dos depende del binario.
        self._parchea_sello()

        self._ruta_real = ESTADO.RUTA
        ESTADO.RUTA = Path(tempfile.mkdtemp(prefix="aegis-deploy-")) / "deploy.json"
        ESTADO.limpiar()

    def _parchea_sello(self, real: bool = False) -> None:
        """Pone (o quita) el sello falso, y se puede volver al real.

        ## Por qué existe el interruptor
        Casi ningún test de la puerta depende del árbol real, y depender de él
        hace que la suite se ponga roja cada vez que se toca `mobile/`, que es lo
        más corriente del mundo. Pero **un** test sí lo necesita:
        `TestElApkCorrespondeAlCodigo`, el único sitio donde `apk_desactualizado`
        se comprueba de verdad. Con un `mock.patch` anidado no podría deshacerlo,
        así que los parches se guardan y se pueden parar a mano.
        """
        if real:
            for parche in getattr(self, "_parches_sello", []):
                parche.stop()
            self._parches_sello = []
            return
        self._parches_sello = [
            mock.patch.object(deploy, "apk_desactualizado", return_value=""),
            mock.patch.object(deploy, "apk_verificado", return_value=True),
            mock.patch.object(deploy, "apk_sin_verificar", return_value=""),
        ]
        for parche in self._parches_sello:
            parche.start()
            self.addCleanup(parche.stop)

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
        # Se parchea `_es_de_esta_maquina` para que el test mida **precedencia** y
        # no la red en la que se ejecuta: una IP inventada no es de esta máquina
        # casi nunca, y un test que depende de eso no es un test (A-057).
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "100.1.2.3"}), \
             mock.patch.object(disp, "_es_de_esta_maquina", return_value=True):
            self.assertEqual(disp.tailnet_ip(), "100.1.2.3")
            self.assertEqual(disp.api_host_para("telefono"), "100.1.2.3")

    def test_una_ip_caducada_no_manda(self) -> None:
        """La IP vieja declarada en el `.env`: el fallo que se coló.

        `bridge/.env` declaraba `AEGIS_BRIDGE_TAILNET_IP` con 192.168.0.50, que
        no era la Tailscale del bridge (100.101.102.100) ni la de esta máquina en su
        propia red (192.168.0.51). La función devolvía lo declarado tal cual y
        cada `build_apk(target='telefono')` compilaba una app apuntando a una
        dirección muerta.

        En el emulador no se notó —el `adb reverse` la dejaba hablar por
        `localhost`— y la actualización entera pasó la puerta con el host
        equivocado. Un fallo que solo aparece cuando ya no queda otra ruta es un
        fallo que llega al móvil.
        """
        propias = {"192.168.0.51", "100.101.102.100"}
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "192.168.0.50"}), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(bridge_tailnet_ip="")), \
             mock.patch.object(disp, "direcciones_locales", return_value=propias), \
             mock.patch.object(
                 disp.subprocess, "run",
                 return_value=mock.Mock(returncode=0, stdout="100.101.102.100\n")):
            self.assertEqual(disp.tailnet_ip(), "100.101.102.100")

    def test_una_ip_de_lan_que_si_es_de_esta_maquina_sigue_manda(self) -> None:
        # El caso bueno que el arreglo anterior rompía: el móvil puede no tener
        # sesión de Tailscale, y apuntar a la LAN es legítimo (ver
        # `TestLaIpDelPuenteEnElTelefono`). La regla no es «que sea de la
        # tailnet», es «que sea de esta máquina».
        propias = {"192.168.0.51", "100.101.102.100"}
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "192.168.0.51"}), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(bridge_tailnet_ip="")), \
             mock.patch.object(disp, "direcciones_locales", return_value=propias):
            self.assertEqual(disp.api_host_para("telefono"), "192.168.0.51")

    def test_sin_poder_comprobar_se_acepta_lo_declarado(self) -> None:
        # Si `ip` no está en la máquina es un problema del entorno, no del
        # código. Rechazar a ciega dejaría sin poder compilar, que es peor que
        # compilar con algo declarable y corregible.
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "192.168.0.50"}), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(bridge_tailnet_ip="")), \
             mock.patch.object(disp, "direcciones_locales", return_value=set()):
            self.assertEqual(disp.tailnet_ip(), "192.168.0.50")

    def test_la_comprobacion_es_de_esta_maquina_y_no_de_un_rango(self) -> None:
        # El intento que se descartó: exigir `100.64.0.0/10`. Habría roto el caso
        # bueno de apuntar a la LAN, y un fallo común no se arregla con una regla
        # más estricta: se arregla con la regla que dice lo que importa.
        propias = {"192.168.0.51", "172.17.0.1", "127.0.0.1"}
        self.assertTrue(disp._es_de_esta_maquina("192.168.0.51", propias))
        self.assertTrue(disp._es_de_esta_maquina("172.17.0.1", propias))
        self.assertFalse(disp._es_de_esta_maquina("192.168.0.50", propias))
        self.assertFalse(disp._es_de_esta_maquina("8.8.8.8", propias))
        self.assertFalse(disp._es_de_esta_maquina("", propias))

    def test_la_tailnet_es_la_fuente_sin_entorno(self) -> None:
        def ip(*a, **k):
            return mock.Mock(returncode=0, stdout="100.101.102.100\n")

        # Sin entorno **y** sin `.env`: un `.env` local con la IP de la LAN
        # declarada haría fallar esto en la máquina de quien lo tiene, y sin
        # querer. Un test que depende de tu `.env` no es un test (A-057).
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": ""}), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(bridge_tailnet_ip="")), \
             mock.patch.object(disp.subprocess, "run", side_effect=ip):
            self.assertEqual(disp.api_host_para("telefono"), "100.101.102.100")

    def test_sin_tailscale_no_hay_ip(self) -> None:
        """`tailscale` ausente no es una razón para devolver una IP cualquiera."""
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": ""}), \
             mock.patch("app.config.get_settings",
                        return_value=mock.Mock(bridge_tailnet_ip="")), \
             mock.patch.object(disp.subprocess, "run",
                               side_effect=FileNotFoundError("tailscale")):
            self.assertEqual(disp.tailnet_ip(), "")

    def test_cada_destino_tiene_su_apk(self) -> None:
        """Con un solo nombre de fichero, un APK se instala donde no funciona."""
        emu = disp.apk_para("emulador")
        tel = disp.apk_para("telefono")
        self.assertNotEqual(emu, tel)
        self.assertIn("emulador.apk", emu.name)
        self.assertIn("telefono.apk", tel.name)

    def test_el_perfil_va_en_el_nombre(self) -> None:
        """Un release dentro de un `app-debug-` rompe la promesa del nombre.

        Los dos perfiles **coexisten** en el directorio de build, así que un
        nombre que no los distingue acaba sirviendo el binario equivocado —y por
        el camino equivocado, que es el fallo más caro porque la app abre y no ve
        nada.
        """
        self.assertEqual(
            disp.apk_para("telefono", "release"),
            disp.apk_para("telefono", "release"))
        self.assertNotEqual(
            disp.apk_para("telefono", "release"),
            disp.apk_para("telefono", "debug"))
        self.assertIn("release", disp.apk_para("telefono").name)
        # Y el destino sigue mandando: release del emulador y release del
        # teléfono son binarios distintos.
        self.assertNotEqual(
            disp.apk_para("emulador", "release"),
            disp.apk_para("telefono", "release"))

    def test_un_perfil_invalido_no_se_traga(self) -> None:
        with self.assertRaises(ValueError):
            disp.apk_para("telefono", "inventado")

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
             m.patch.object(deploy, "apk_desactualizado", return_value=""), \
             m.patch.object(deploy, "apk_verificado", return_value=True), \
             m.patch.object(deploy, "apk_sin_verificar", return_value=""), \
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
    """La puerta **partida**: lo caro se comprueba al compilar, lo barato al instalar.

    ## Por qué está partida
    Medido (2026-10-03): la puerta completa corría **después** de que aprobaras.
    `flutter analyze` + `flutter test` + el humo son minutos, así que el aviso
    decía «se instala» y luego había varios minutos de silencio con el dedo de
    alguien puesto encima de un botón. Y si la puerta se cerraba, ese «sí» había
    servido para pedirte que aprobaras una instalación que no iba a ocurrir.

    Ahora compilar verifica y deja el resultado sellado en `<apk>.verificado`, e
    instalar solo comprueba que ese sello siga cuadrando con el binario de ahora.
    Lo que queda entre tu «sí» y el APK instalado es un `adb install`.

    ## Qué se sigue comprobando al instalar, y por qué
    Que el teléfono esté, y que **alcance** al bridge. Eso no se puede verificar
    al compilar: depende del cable, de Tailscale y de si la app está encendida,
    y cambia sin avisar.
    """

    VERDE = {"analyze": (True, "ok"), "tests": (True, "11/11"),
             "humo": (True, "app viva y el bridge recibió la llamada")}

    def _puerta(self, **cambios):
        """Contexto con la puerta en verde salvo lo que el test rompa."""
        ver = dict(self.VERDE)
        ver.update(cambios)
        mocks = (mock.Mock(return_value=ver["analyze"]),
                 mock.Mock(return_value=ver["tests"]),
                 mock.Mock(return_value=ver["humo"]))
        stack = contextlib.ExitStack()
        for nombre, m in zip(("verificar_analisis", "verificar_tests",
                              "humo_una_vez"), mocks):
            stack.enter_context(mock.patch.object(deploy, nombre, m))
        stack.enter_context(mock.patch.object(disp, "api_host_para",
                                              return_value="100.101.102.100"))
        stack.enter_context(mock.patch.object(disp, "telefono_alcanza",
                                              return_value=(True, "ok")))
        # Un APK verificado, que es lo normal después de `build_apk`.
        stack.enter_context(mock.patch.object(deploy, "apk_verificado",
                                              return_value=True))
        stack.enter_context(mock.patch.object(deploy, "apk_sin_verificar",
                                              return_value=""))
        # El APK real **está** desactualizado mientras se toca `mobile/`, y la
        # puerta lo detecta. Aquí se falsea: esta clase prueba la lógica de la
        # puerta, y si el rojo fuera el sello real estos tests dirían «no pasa»
        # por un motivo que no es el que están mirando.
        stack.enter_context(mock.patch.object(deploy, "apk_desactualizado",
                                              return_value=""))
        stack.mocks = mocks
        return stack

    # -- la puerta que queda al instalar -------------------------------------

    def test_instalar_no_vuelve_a_pasar_analyze(self) -> None:
        """El motivo de que la puerta exista partida:|minutos con el dedo puesto.

        Antes, aprobar y esperar era esto: tres comprobaciones de minutos. Ahora
        instalar no llama a ninguna, y el que lo afirma es el mock —si mañana
        alguien las vuelve a meter aquí, el test se pone rojo.
        """
        with self._puerta() as puerta, \
             mock.patch.object(disp, "telefono", return_value=TELEFONO):
            analyze, tests, humo = puerta.mocks
            deploy.pasar_puerta_deploy()
        analyze.assert_not_called()
        tests.assert_not_called()
        humo.assert_not_called()

    def test_sin_verificar_no_pasa(self) -> None:
        """Un APK sin pasar la puerta no se propone ni se instala."""
        with self._puerta(), mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy, "apk_verificado", return_value=False), \
             mock.patch.object(deploy, "apk_sin_verificar",
                               return_value="este APK no ha pasado la puerta todavía"):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("no ha pasado la puerta", str(cm.exception))

    def test_un_apk_recompilado_despues_no_pasa(self) -> None:
        """El `.verificado` ata a un binario, no a un nombre de fichero.

        Compilar dos veces deja el mismo nombre con otro contenido. Si el sello se
        guardara por ruta, una aprobación vieja autorizaría un binario que nadie
        vio; por eso se guarda la firma del **binario** (A-061 aplicado a esto).
        """
        with self._puerta(), mock.patch.object(disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy, "apk_verificado", return_value=False), \
             mock.patch.object(deploy, "apk_sin_verificar",
                               return_value="el APK se recompiló después de verificarse"):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("recompiló", str(cm.exception))

    def test_un_telefono_que_no_alcanza_el_bridge_no_instala(self) -> None:
        """La puerta anterior daba por bueno un APK con una dirección sin probar.

        El APK del teléfono lleva la dirección del bridge dentro. Si el móvil no
        llega, la app instala y abre sin ver nada, que es el peor resultado
        posible: parece que funcionó. Y esto **no** se puede comprobar al
        compilar: depende del cable y de Tailscale.
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

    def test_sin_telefono_no_da_error_sino_por_que(self) -> None:
        with mock.patch.object(disp, "telefono", return_value=None):
            with self.assertRaises(PuertaCerrada) as cm:
                deploy.pasar_puerta_deploy()
        self.assertIn("no instalo", str(cm.exception) + "no instalo")

    # -- la puerta cara, que ahora corre al compilar ------------------------

    def test_verificar_binario_pasa_analyze_tests_y_humo(self) -> None:
        """Al compilar: verde, y con humo si lo piden."""
        with self._puerta() as puerta:
            analyze, tests, humo = puerta.mocks
            ok, _ = deploy.verificar_binario(deploy.APK_TELEFONO, con_humo=True)
        self.assertTrue(ok)
        analyze.assert_called_once()
        tests.assert_called_once()
        humo.assert_called_once()

    def test_sin_humo_no_se_arranca_el_emulador(self) -> None:
        """Compilar para tu propio uso no debería instalar en el emulador.

        El humo cuesta alrededor de un minuto e instala y arranca el AVD. Por
        defecto se apaga; quien quiera sellar el APK como instalable lo pide.
        """
        with self._puerta() as puerta:
            analyze, tests, humo = puerta.mocks
            ok, _ = deploy.verificar_binario(deploy.APK_TELEFONO, con_humo=False)
        self.assertTrue(ok)
        analyze.assert_called_once()
        tests.assert_called_once()
        humo.assert_not_called()

    def test_analyze_rojo_no_llega_al_humo(self) -> None:
        """Analyze y tests se pasan los dos aunque uno falle; el humo no.

        Correr los dos aunque analyze esté rojo es a propósito: da la foto
        completa en una pasada, en vez de obligar a arreglar analyze, repetir, y
        descubrir que los tests también estaban rojos. El humo **sí** se salta,
        porque cuesta un minuto y si analyze ya está en rojo su resultado no va
        a cambiar la conclusión.
        """
        with self._puerta(analyze=(False, "rojo")) as puerta, \
             mock.patch.object(deploy, "apk_desactualizado", return_value=""):
            analyze, tests, humo = puerta.mocks
            ok, detalle = deploy.verificar_binario(deploy.APK_TELEFONO, con_humo=True)
        self.assertFalse(ok)
        self.assertIn("analyze: rojo", detalle)
        analyze.assert_called_once()
        tests.assert_called_once()
        humo.assert_not_called()

    def test_humo_rojo_tambien_detiene(self) -> None:
        """Verde todo y aun así no se instala: el humo manda."""
        with self._puerta(humo=(False, "la app no habló con el bridge")) as puerta, \
             mock.patch.object(deploy, "apk_desactualizado", return_value=""):
            ok, detalle = deploy.verificar_binario(deploy.APK_TELEFONO, con_humo=True)
        self.assertFalse(ok)
        self.assertIn("no habló", detalle)

    def test_un_apk_desactualizado_no_se_verifica(self) -> None:
        """Verificar un binario que no es del código actual no sirve de nada."""
        with self._puerta() as puerta, \
             mock.patch.object(deploy, "apk_desactualizado",
                               return_value="el APK no corresponde al código de ahora"):
            analyze, _, _ = puerta.mocks
            ok, detalle = deploy.verificar_binario(deploy.APK_TELEFONO, con_humo=True)
        self.assertFalse(ok)
        self.assertIn("no corresponde al código", detalle)
        analyze.assert_not_called()


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
        #: El estado del **último** broadcast, para que el `dumpsys` falso enseñe
        #: el mismo título que el aviso de verdad.
        #:
        #: ## Por qué hace falta y no era un detalle
        #: `_hay_aviso_aegis` comprueba que el aviso esté **en el estado que se
        #: acaba de pedir**, no solo que exista. Antes el mock enseñaba un
        #: `NotificationRecord` sin título, así que cualquier estado nuevo daba
        #: «no verificado» y los tests de resultado se pusieron rojos.
        #:
        #: Lo peligroso es el revés: un mock que **siempre** dice «está» hace que
        #: la verificación parezca funcionar sin comprobar nada. Y con un solo id
        #: eso es exactamente lo que pasaba en el dispositivo: tras `hecho`,
        #: `dumpsys` seguía enseñando `EN MARCHA` y el puente decía «verificado».
        self.estado_actual = "pendiente"

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
            if not self.hay_aviso:
                return 0, "sin notificaciones"
            titulo = (deploy.MARCA_ESTADO.get(self.estado_actual)
                      or "NECESITO TU OK")
            return 0, (
                f"    NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=null)\n"
                f"      android.title=String (AEGIS · {titulo})\n"
                f"      android.text=String (algo)")
        if "appops" in a:
            return 0, "Uid mode: POST_NOTIFICATION: allow"
        # `am broadcast` responde con esto; sin él el puente no lo da por entregado.
        if "broadcast" in a:
            if "tipo" in a:
                self.estado_actual = a[a.index("tipo") + 1]
            return 0, "Broadcasting: Intent {...}\nBroadcast completed: result=0"
        return 0, ""

    def _solo_broadcasts(self) -> list[dict]:
        """Solo los `am broadcast`. El resto es `dumpsys`, `appops` y compañía."""
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


class TestElCicloDelAviso(_PisoAvisos):
    """Un aviso, un id, y cuatro estados que se sustituyen en sitio.

    ## Por qué esta clase existe
    El fallo medido (2026-10-03) fue que un aviso de un test **quedó en la
    bandeja sin forma de quitarlo**. La causa no fue un estado mal pintado: fue
    que había **dos** ids (4101 para decidir, 4102 para el resultado), que solo
    se cancelaba el primero, y solo cuando otro aviso de pendientes veía la cola
    vacía. Si no volvía a haber nada que decidir, ese otro aviso nunca llegaba y
    el aviso se quedaba ahí para siempre.

    ## Lo que se afirma
    1. Los cuatro estados viajan con el nombre que la app espera.
    2. `limpiar` **no** se verifica contra `dumpsys`: no publica nada, y preguntar
       por él daría «no verificado» siempre, que es ruido y no un dato.
    3. Todo lleva `ts`, que es lo que permite ordenar y descartar avisos viejos.
    """

    def _extra(self, clave: str, indice: int = 0) -> str:
        """El **valor** del `--es <clave> <valor>` del n-ésimo broadcast.

        Se busca por el nombre de la clave y se lee el siguiente elemento, que es
        su valor. La versión anterior buscaba `--es` y leía el siguiente, que es
        la **clave** —«tipo»— en vez del valor, y por eso afirmaba que todos los
        avisos decían «tipo».
        """
        args = self._solo_broadcasts()[indice]["args"]
        return args[args.index(clave) + 1] if clave in args else ""

    def _estado(self, indice: int = 0) -> str:
        return self._extra("tipo", indice)

    def _con_telefono(self):
        return mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
            mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR)

    def test_los_cuatro_estados_viajan_con_su_nombre(self) -> None:
        tlf, emu = self._con_telefono()
        with tlf, emu, self._sin_dormir(), \
                mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            deploy.avisar_trabajando("deploy-1", "instalando")
            deploy.avisar_telefono({"id": "deploy-1", "razon": "instalado"})
            deploy.avisar_fallo_telefono("deploy-2", "no se pudo")
            deploy.avisar_limpiar()
        tipos = [self._estado(i) for i in range(len(self._solo_broadcasts()))]
        self.assertEqual(tipos, ["trabajando", "hecho", "fallo", "limpiar"])

    def test_limpiar_no_se_verifica(self) -> None:
        """`limpiar` cancela. Preguntar en `dumpsys` si hay un aviso daría siempre
        «no verificado», que no es un fallo: es lo único que puede pasar."""
        tlf, emu = self._con_telefono()
        with tlf, emu, self._sin_dormir(), \
                mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.avisar_limpiar()
        self.assertEqual(salida, "aviso limpiado")
        self.assertNotIn("VERIFICADO", salida)

    def test_todo_lleva_ts_para_poder_ordenar(self) -> None:
        """Sin `ts`, un broadcast tardío puede pisar un estado más nuevo.

        Los broadcasts van por adb, uno a uno, pero sin orden entre llamadas
        distintas: el puente avisa por teléfono y por emulador en procesos
        separados. Sin esta marca, un «instalado» que llegaba tarde podía dejar la
        bandeja pidiendo un OK sobre algo ya hecho.
        """
        tlf, emu = self._con_telefono()
        with tlf, emu, self._sin_dormir(), \
                mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            deploy.avisar_telefono({"id": "d1", "razon": "instalado"})
        args = self._solo_broadcasts()[0]["args"]
        self.assertIn("--es", args)
        self.assertIn("ts", args)
        self.assertGreater(float(args[args.index("ts") + 1]), 0.0)

    def test_el_estado_tambien_lo_ve_la_peticion_que_lo_causo(self) -> None:
        """`pet_id` para que la app pueda ignorar lo de una petición que ya no existe."""
        tlf, emu = self._con_telefono()
        with tlf, emu, self._sin_dormir(), \
                mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            deploy.avisar_trabajando("deploy-xyz", "instalando")
        self.assertEqual(self._extra("pet_id"), "deploy-xyz")

    def test_verificar_exige_el_estado_y_no_solo_la_existencia(self) -> None:
        """Un aviso que ya existía **no** prueba que el estado nuevo esté puesto.

        ## El fallo, medido en el emulador
        Con un solo id, los estados se sustituyen en sitio, así que el aviso
        anterior sigue ahí mientras el nuevo se publica en el hilo del receptor.
        `_hay_aviso_aegis` solo miraba que hubiera un aviso de Aegis, así que
        devolvía «entregado y verificado» sin esperar nada. Medido: tras pedir
        `hecho`, `dumpsys` seguía enseñando `AEGIS · EN MARCHA`.

        Es A-042 otra vez —un éxito que nadie comprobó— y lo causó el arreglo
        anterior, que fue a mejor en todo lo demás.
        """
        registro = (f"    NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                    f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=null)\n"
                    "      android.title=String (AEGIS · EN MARCHA)\n"
                    "      android.text=String (instalando)")

        def _adb(args, timeout=60, serial=""):
            if "dumpsys" in args:
                return 0, registro
            return 0, "Broadcasting: Intent {...}\nBroadcast completed: result=0"

        with mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             self._sin_dormir(), \
             mock.patch.object(deploy.disp, "_adb", side_effect=_adb):
            salida = deploy._avisar_app(TELEFONO, deploy.ESTADO_HECHO)
        # El aviso existe, pero es el de antes: no se puede dar por entregado.
        self.assertIn("NO VERIFICADO", salida)
        self.assertNotIn("entregado", salida)

    def test_verificar_con_el_estado_bueno_si_pasa(self) -> None:
        """El otro lado: si el título es el que se pidió, se acepta."""
        registro = (f"    NotificationRecord(0x1: pkg={deploy.PAQUETE} "
                    f"user=UserHandle{{0}} id={deploy.ID_AVISO} tag=null)\n"
                    "      android.title=String (AEGIS · INSTALADO)")

        def _adb(args, timeout=60, serial=""):
            if "dumpsys" in args:
                return 0, registro
            return 0, "Broadcasting: Intent {...}\nBroadcast completed: result=0"

        with mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             self._sin_dormir(), \
             mock.patch.object(deploy.disp, "_adb", side_effect=_adb):
            salida = deploy._avisar_app(TELEFONO, deploy.ESTADO_HECHO)
        self.assertIn("entregado y verificado", salida)

    def test_limpiar_llega_al_emulador_si_no_hay_telefono(self) -> None:
        """Un aviso que hay que quitar tiene que poder quitarse **donde está**.

        ## El fallo
        `avisar_intermedio` caía al emulador si no había teléfono; los otros tres
        avisos, no. Medido: en una máquina sin teléfono conectado, el aviso atascado
        del emulador **no se podía limpiar nunca**, porque `limpiar` se quedaba
        mirando el teléfono, que no existía. Cuatro maneras de decidir a quién
        avisar es cuatro maneras de que una se quede sin probar.
        """
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=None), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            salida = deploy.avisar_limpiar()
        self.assertEqual(salida, "aviso limpiado")
        self.assertEqual(self._destinos(), [EMULADOR.serial])

    def test_limpiar_prefiere_el_telefono(self) -> None:
        """Y si hay los dos, va al teléfono: es donde se decide."""
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb):
            deploy.avisar_limpiar()
        self.assertEqual(self._destinos(), [TELEFONO.serial])

    def test_el_id_verificado_sigue_siendo_el_que_publica(self) -> None:
        """El puente **comprueba** este id en `dumpsys` para decir que llegó.

        Si Kotlin publica en un id distinto de `ID_AVISO`, el aviso se entrega y
        el puente responde «AVISO NO VERIFICADO»: un fallo que no se ve en ninguna
        parte, porque los dos lados compilan bien por separado.
        """
        fuente = Path(__file__).resolve().parents[2] / "mobile" / "android" / "app" \
            / "src" / "main" / "kotlin" / "com" / "aegis" / "aegis_console" \
            / "NotificacionReceiver.kt"
        if not fuente.exists():
            self.skipTest("el proyecto Android no está a mano")
        kotlin = fuente.read_text(encoding="utf-8")
        self.assertIn(f"const val ID = {deploy.ID_AVISO}", kotlin)
        # Y no queda el segundo id, que es lo que no se cancelaba nunca.
        self.assertNotIn("ID_RESULTADO", kotlin)
        # Y la caducidad coincide con la del puente, o el aviso se va antes o
        # después de lo que el puente dice que se queda.
        ms = int(kotlin.split("CADUCIDAD_MS = ")[1].split("L")[0])
        self.assertEqual(ms, deploy.CADUCIDAD_FINAL_MS)


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

    class _Reloj:
        """Un reloj que el test **mueve**, en vez de una lista de valores.

        ## Por qué controlarlo y no listarlo
        Antes era `side_effect=[100.0, 100.0, 120.0, 120.0]`: una lista ata el test
        al **número** de llamadas a `time.time()` que hay dentro de `pedir_deploy`
        más `_avisar_app`. Añadir el `ts` al aviso —una llamada más— lo dejó en
        rojo sin que hubiera cambiado una sola regla de deduplicación. El test
        estaba midiendo la implementación por accidente.

        Con un reloj que el test mueve entre llamadas, lo que se afirma es lo que
        dice el nombre: «pasada la ventana, vuelve a sonar».
        """

        def __init__(self, ahora: float = 100.0) -> None:
            self.ahora = ahora

        def __call__(self) -> float:
            return self.ahora

        def avanza(self, segundos: float) -> None:
            self.ahora += segundos

    def _reloj(self, ahora: float = 100.0) -> "_Reloj":
        return self._Reloj(ahora)

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
        reloj = self._reloj()
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb), \
             mock.patch.object(deploy.time, "time", side_effect=reloj):
            deploy.pedir_deploy("motivo A")
            reloj.avanza(20.0)
            deploy.pedir_deploy("motivo B")
        self.assertEqual(len(self._solo_broadcasts()), 2, self.llamadas)

    def test_pasada_la_ventana_vuelve_a_sonar(self) -> None:
        """El aviso se calla un rato, no para siempre."""
        reloj = self._reloj()
        with mock.patch.object(deploy.disp, "emulador", return_value=EMULADOR), \
             mock.patch.object(deploy.disp, "telefono", return_value=TELEFONO), \
             mock.patch.object(deploy.disp, "_adb", side_effect=self._adb), \
             mock.patch.object(deploy.time, "time", side_effect=reloj):
            deploy.pedir_deploy("mismo motivo")
            deploy.pedir_deploy("mismo motivo")
            self.assertEqual(len(self._solo_broadcasts()), 1, "no se repitió de más")
            # Y pasada la ventana, vuelve a sonar. Eso es lo que se afirma: que la
            # ventana **acaba**, en vez de que el aviso se calla para siempre.
            reloj.avanza(deploy.VENTANA_AVISO + 1)
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
            avisar.side_effect = lambda dev, *a, **k: str(_pregunta())
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

    def test_el_serial_declarado_cuenta(self) -> None:
        """Un serial USB declarado por la persona sí es su teléfono.

        Es la cuarta forma, y viene de `AEGIS_PHONE_SERIAL`. Antes no existía
        porque `adb` por USB (`SERIAL1234567`) no se parece a mDNS ni a
        `ip:puerto`, y el resultado era que Aegis no veía un teléfono enchufado y
        conectado, que es el caso más fácil de resolver que había.
        """
        with mock.patch.dict(os.environ, {"AEGIS_PHONE_SERIAL": "SERIAL1234567"}):
            with mock.patch.object(disp, "PHONE_SERIAL_ENV", "SERIAL1234567"):
                self.assertTrue(disp._parece_telefono("SERIAL1234567"))
                self.assertFalse(disp._parece_telefono("OTROSERIAL"))

    def test_el_serial_declarado_llega_desde_el_env_de_la_config(self) -> None:
        """Ponerlo en `bridge/.env` tiene que funcionar.

        Se comprobó que no: `dispositivos` lo leía de `os.environ`, y nadie
        exporta el `.env`, así que la variable documentada no hacía nada. Y
        pydantic mapea `phone_serial` a `PHONE_SERIAL`, no a `AEGIS_PHONE_SERIAL`,
        así que tampoco bastaba con declararlo en `Settings` sin alias.
        """
        with mock.patch.object(disp, "PHONE_SERIAL_ENV", ""), \
                mock.patch("app.config.get_settings",
                           return_value=mock.Mock(phone_serial="SERIAL1234567")):
            self.assertEqual(disp.phone_serial_configurado(), "SERIAL1234567")
            self.assertTrue(disp._parece_telefono("SERIAL1234567"))

    def test_el_informe_no_dice_que_es_tu_telefono_lo_que_no_lo_es(self) -> None:
        """Un informe que contradice a la tool que lo acompaña es peor que nada.

        `estado_humano` ponía «tu teléfono: <el primero que no sea emulador>» y
        un segundo después `resolver('telefono')` decía que tu teléfono no
        aparecía. Los dos mensajes no pueden ser verdad a la vez, y se leía el
        primero.
        """
        usb = disp.Device(serial="SERIAL1234567", state="device")
        with mock.patch.object(disp, "dispositivos", return_value=[usb, EMULADOR]), \
                mock.patch.object(disp, "PHONE_SERIAL_ENV", ""), \
                mock.patch("app.config.get_settings",
                           return_value=mock.Mock(phone_serial="")):
            texto = disp.estado_humano()
        self.assertIn("OTRO", texto)
        self.assertIn("no identificado", texto)
        self.assertNotIn("tu teléfono: SERIAL1234567", texto)

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
        """La puerta en verde: el APK verificado y el sello cuadrando.

        Analyze, tests y humo **no** se falsean: ya no pasan por aquí, se pasan
        al compilar (`verificar_binario`), y esta clase no va de eso. Lo que se
        falsea es lo que la puerta de instalar sí mira: que el binario tenga el
        `.verificado`. La resolución del teléfono y el resto se dejan correr de
        verdad, porque son parte de lo que este test mide: el contrato entre la
        puerta y quien la usa.
        """
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(deploy, "apk_verificado", return_value=True))
        stack.enter_context(
            mock.patch.object(deploy, "apk_sin_verificar", return_value=""))
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


class TestLaIpDelPuenteEnElTelefono(_Piso):
    """El APK del teléfono necesita una IP, y a veces la de la tailnet no vale.

    Se comprobó en la máquina real: el teléfono **ping** a la IP de la tailnet
    sin respuesta porque Tailscale no corre ahí, mientras que por la LAN sí llega.
    Sin declarar la IP de la LAN, la puerta decía «el teléfono NO llega» con el
    teléfono perfectamente conectado: la misma clase de fallo que A-046.
    """

    def test_la_ip_declarada_gana_a_tailscale(self) -> None:
        # Una IP de la LAN es una declaración legítima: el móvil puede no tener
        # sesión de Tailscale. Lo que no vale es una IP que no sea de esta
        # máquina, que es un valor caducado (ver `test_una_ip_caducada_no_manda`).
        with mock.patch.dict(os.environ, {"AEGIS_BRIDGE_TAILNET_IP": "192.168.0.50"}), \
                mock.patch("app.config.get_settings",
                           return_value=mock.Mock(bridge_tailnet_ip="")), \
                mock.patch.object(disp, "_es_de_esta_maquina", return_value=True):
            self.assertEqual(disp.tailnet_ip(), "192.168.0.50")

    def test_tambien_llega_desde_el_env_de_la_config(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("app.config.get_settings",
                           return_value=mock.Mock(bridge_tailnet_ip="192.168.0.50")), \
                mock.patch.object(disp, "_es_de_esta_maquina", return_value=True):
            self.assertEqual(disp.tailnet_ip(), "192.168.0.50")


class TestElApkCorrespondeAlCodigo(_Piso):
    """La puerta tiene que poder decir «este binario es viejo».

    ## El fallo medido que esto previene
    Se aprobó e instaló en el teléfono un APK de dos días antes del código que se
    estaba tocando. Todo lo que la puerta comprobaba era cierto —la huella
    casaba, era un binario verificado— y aun así lo instalado no era lo que se
    creías. Es A-016 con otro disfraz: **una puerta que comprueba una cosa y
    responde por otra**.
    """

    def setUp(self) -> None:
        super().setUp()
        # Aquí el sello **no** se falsea: es la única clase que lo comprueba, y con
        # el falseo del piso afirmaría que un APK desactualizado está al día.
        self._parchea_sello(real=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-sello-"))

    def _proyecto(self, tmp: Path) -> Path:
        """Un proyecto Flutter mínimo, con un APK dentro de `build/`."""
        raiz = tmp / "mobile"
        (raiz / "lib").mkdir(parents=True)
        (raiz / "build" / "app" / "outputs" / "flutter-apk").mkdir(parents=True)
        (raiz / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
        (raiz / "lib" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
        return raiz / "build" / "app" / "outputs" / "flutter-apk" / "app-debug.apk"

    def test_sin_sello_no_se_afirma_nada(self) -> None:
        """Un APK compilado a mano queda sin comprobar, no «verificado»."""
        apk = self._proyecto(self.tmp)
        apk.write_bytes(b"x")
        self.assertEqual(deploy.apk_desactualizado(apk), "")

    def test_sello_al_day_no_dice_nada(self) -> None:
        apk = self._proyecto(self.tmp)
        apk.write_bytes(b"x")
        deploy.escribir_sello(apk)
        self.assertEqual(deploy.apk_desactualizado(apk), "")

    def test_cambio_de_codigo_lo_detecta(self) -> None:
        apk = self._proyecto(self.tmp)
        apk.write_bytes(b"x")
        deploy.escribir_sello(apk)
        (self.tmp / "mobile" / "lib" / "main.dart").write_text("void main() {}\n//x\n",
                                                              encoding="utf-8")
        motivo = deploy.apk_desactualizado(apk)
        self.assertIn("no corresponde al código", motivo)
        self.assertIn("build_apk", motivo)

    def test_un_toque_sin_cambio_no_da_falso_positivo(self) -> None:
        """Con comparar solo fechas, un `touch` bloquearía la instalación.

        Medido: un fichero de `lib/` tenía `mtime` nueva sin cambiar de
        contenido, y el guard por fecha se negativesó. Con firma no pasa, porque
        lo que se mira es el contenido y el tamaño.
        """
        apk = self._proyecto(self.tmp)
        apk.write_bytes(b"x")
        deploy.escribir_sello(apk)
        f = self.tmp / "mobile" / "lib" / "main.dart"
        f.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        import os
        os.utime(f, (f.stat().st_atime + 500, f.stat().st_mtime + 500))
        self.assertEqual(deploy.apk_desactualizado(apk), "")

    def test_un_apk_fuera_de_un_proyecto_no_se_juzga(self) -> None:
        self.assertEqual(deploy.apk_desactualizado(Path(__file__)), "")
