"""La autonomía: qué hace Aegis solo y qué tiene que preguntar.

## El caso que todo esto previene
Aegis tiene 18 herramientas deterministas. La pregunta que faltaba era *¿qué
puede hacer sin preguntarme?*. Sin respuesta hay dos opciones y las dos son
malas: no dejarle hacer nada (y entonces es un buscapersonas) o dejarle todo (y
entonces la confianza es un acto de fe que se gasta la primera vez que se
equivoca).

Aquí la autonomía es una **lista explícita** en tres niveles, y lo que se
comprueba es que la lista se cumple en los dos sentidos: que Aegis **no** hace
lo que no debe, y que **sí** hace lo que puede. Un test que solo mirara el
segundo lado pasaría con un sistema que no puede escribir nunca.

## Por qué los tests miran el almacén, no el global
`decide()` recibe el almacén como argumento justamente para que un test pueda
montar el escenario completo —proyecto marcado o sin marcar— sin tocar el estado
de producción. Un test que usara el global de verdad podría dejar a este equipo
sin permiso para escribir y nadie lo vería hasta que Aegis se callara.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import entorno  # noqa: E402
from app import autonomy  # noqa: E402
from app.autonomy import AutonomiaError, Decision  # noqa: E402
from app.main import exigir_token  # noqa: E402


def app_routes():
    from app.main import app
    from fastapi.routing import APIRoute
    return [r for r in app.routes if isinstance(r, APIRoute)]


class _Piso(unittest.TestCase):
    """Cada test con su almacén y sus ficheros tocados.

    `_TOCADOS` es memoria del módulo: si no se limpia, un test que dejó un
    fichero "tocado" hace que el siguiente no pida permiso por ser la primera
    vez. El fallo aparece en el test equivocado, que es la forma más difícil de
    depurar.
    """

    ## Por qué un fichero propio y no `mobile/lib/app.dart`
    ##
    ## Porque la regla de reescritura **mide el fichero de verdad**: mira
    ## cuántas líneas tiene hoy y las compara con las que llegarían. Usando un
    ## fichero real del repo, el test dépendía de cuánto mide ese fichero, y
    ## dejó de pasar el día que `app.dart` pasó de 121 líneas — sin que nadie
    ## tocara este test. Un test que se rompe porque el código grew es un test
    ## midiendo el código en vez de la regla.
    ##
    ## El fixture tiene tres líneas porque lo que se prueba es «una escritura
    ## normal no es una reescritura», y eso tiene que ser cierto hoy y dentro de
    ## un año.
    _RUTA = "mobile/test/autonomia_fixture.dart"

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="aegis-autonomia-")
        self.a = autonomy._Almacen(Path(self.tmp) / "autonomia.sqlite3")
        autonomy.forgetting_tocados()
        # Se escribe dentro del proyecto declarado, que es lo que la whitelist
        # exige. Vive en el árbol de trabajo a propósito: la regla lo resuelve
        # contra el disco, no contra un doble.
        objetivo = Path(__file__).resolve().parents[2] / self._RUTA
        objetivo.parent.mkdir(parents=True, exist_ok=True)
        objetivo.write_text("// fixture de un test\n// una\n// dos\n")
        self.addCleanup(objetivo.unlink, True)
        self.addCleanup(autonomy.forgetting_tocados)

    def tearDown(self) -> None:
        autonomy.forgetting_tocados()


class TestLasTresNiveles(_Piso):
    """La clasificación tiene que ser completa y sin huecos.

    ## Por qué una tool desconocida es `requiere_ok`
    Una tool que no está en ninguna lista cae en `requiere_ok`. Con una tool
    nueva, el fallo seguro es **preguntar**: un nivel por defecto permisivo
    concede permisos a medida que se añaden herramientas, sin que nadie lo decida.
    """

    def test_todas_las_tools_estan_clasificadas(self):
        """Toda tool —de las dos clases— tiene nivel, y ningún nivel sobra.

        Hay dos clases y por eso hay dos registros: las tools MCP (`LIBRES` /
        `CON_PERMISO` / `REQUIERE_OK`) y las del camino rápido
        (`NIVELES_CAMINO_RAPIDO`), que son funciones que el router llama tras
        pasar por `decide()`. Comprobarlas por separado es lo que permite que
        el segundo registro exista sin que este test tenga que mentir.
        """
        from app.autopilot import allowed_tools
        from app.intents import INTENTS

        reales = allowed_tools()
        clasificadas = (autonomy.LIBRES | autonomy.CON_PERMISO
                        | autonomy.REQUIERE_OK)
        self.assertEqual(reales - clasificadas, set(),
                         "tools sin nivel: nunca se sabria si preguntan")
        self.assertEqual(clasificadas - reales, set(),
                         "niveles de tools que ya no existen")

    def test_las_tools_del_camino_rapido_tienen_nivel_y_existen(self) -> None:
        """Igual que el anterior, para la otra clase.

        Y además: cada tool que **escribe** un intent tiene que estar declarada.
        Un intent de escritura con nivel por defecto sería `requiere_ok` —que
        funciona— pero por accidente, no porque alguien lo pensara.
        """
        from app.intents import INTENTS

        declaradas = set(autonomy.NIVELES_CAMINO_RAPIDO)
        # Las tools que los intents declaran, sea cual sea su `escribe`.
        usadas = {i.tool for i in INTENTS if i.tool}
        sin_nivel = usadas - declaradas
        # Las lecturas pueden no declarar nada (heredan `requiere_ok` y no
        # escriben), pero las que escriben, no.
        escritos = {i.tool for i in INTENTS if i.escribe and i.tool}
        self.assertEqual(set(), escritos - declaradas,
                         f"ints que escriben sin nivel declarado: {escritos - declaradas}")
        for nombre, nivel in autonomy.NIVELES_CAMINO_RAPIDO.items():
            self.assertIn(nivel, ("libre", "con_permiso", "requiere_ok"),
                          f"{nombre} tiene nivel '{nivel}', que no existe")

    def test_ningun_nivel_se_solapa(self):
        for a, b, nombre in ((autonomy.LIBRES, autonomy.CON_PERMISO, "libres/con_permiso"),
                             (autonomy.LIBRES, autonomy.REQUIERE_OK, "libres/requiere_ok"),
                             (autonomy.CON_PERMISO, autonomy.REQUIERE_OK, "con_permiso/requiere_ok")):
            self.assertEqual(a & b, set(), f"solape en {nombre}: {a & b}")

    def test_una_tool_nueva_pregunta(self):
        self.assertEqual(autonomy.nivel_de("tool_del_futuro"), "requiere_ok")

    def test_el_nivel_no_depende_del_proyecto(self):
        # El nivel lo decide el NOMBRE. Un nivel que dependiera de "cómo estamos
        # hoy" cambiaría entre el paso 2 y el 3 del mismo run, y una puerta que
        # se mueve sola no es una puerta.
        self.assertEqual(autonomy.nivel_de("db_migrate"), "requiere_ok")
        self.a.marcar("compra-unida")
        self.assertEqual(autonomy.nivel_de("db_migrate"), "requiere_ok")


class TestModoSolo(_Piso):
    """En `solo` no se escribe ni con el proyecto marcado."""

    def setUp(self):
        super().setUp()
        self.a.set_modo("solo")
        self.a.marcar("aegis")

    def test_escribir_esta_negocado_aunque_estea_marcado(self):
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertFalse(d.ok)
        self.assertIn("solo", d.motivo)
        self.assertIsNone(d.peticion, "no debe abrir una peticion que va a negarse")

    def test_leer_si_se_puede(self):
        d = autonomy.decide("aegis_read_file", {"path": self._RUTA},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertTrue(d.ok)


class TestProyectoSinMarcar(_Piso):
    """Sin marcar, de solo lectura. Y la razón lo dice."""

    def test_escribir_en_no_marcado_no_pide_permiso_lo_dice(self):
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertFalse(d.ok)
        self.assertIsNone(d.peticion,
                          "no hay peticion: no es una duda, es un no")
        self.assertIn("sin marcar", d.motivo)

    def test_leer_si_se_puede_siempre(self):
        """Leer el proyecto es parte de entenderlo, y una puerta que cierra la
        lectura solo produce resistencia sin."""
        d = autonomy.decide("aegis_read_file", {"path": self._RUTA},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertTrue(d.ok)

    def test_marcado_y_autorizado(self):
        self.a.marcar("aegis")
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a)
        # La primera vez sobre un fichero pide permiso, pero por ser la primera
        # vez: la peticion tiene que existir.
        self.assertFalse(d.ok)
        self.assertIsNotNone(d.peticion)
        self.assertIn("Primera vez", d.motivo)

    def test_la_segunda_vez_no_vuelve_a_preguntar(self):
        """El círculo completo: pide una vez, se le concede, y ya no molesta.

        Esto es lo que hace que "confiar este equipo a Aegis" sea Sustainable en
        el tiempo. Si volviera a preguntar en cada intento, la respuesta correcta
        sería dejarlo sin marcar, y la autonomía sería nominal.
        """
        self.a.marcar("aegis")
        args = {"path": self._RUTA, "content": "x"}
        primera = autonomy.decide("aegis_write_file", args, run_id="r1",
                                  paso=1, almacen_=self.a)
        self.assertFalse(primera.ok)
        token = self.a.resolver(primera.peticion, "aprobar")["token"]
        concedida = autonomy.decide("aegis_write_file", args, run_id="r1",
                                    paso=1, almacen_=self.a, token=token)
        self.assertTrue(concedida.ok, concedida.motivo)
        # Y la siguiente, sin token, ya pasa sola.
        d = autonomy.decide("aegis_write_file", args, run_id="r2", paso=1,
                            almacen_=self.a)
        self.assertTrue(d.ok, d.motivo)

    def test_el_token_no_sirve_para_otra_llamada(self):
        """Un permiso es para **una** llamada con **unos** argumentos.

        Ni para otra tool, ni para la misma tool con otros argumentos. Si
        valiera para más, aprobar una escritura aprobaría la siguiente sin haberla
        visto, y eso es exactamente lo que la puerta tiene que impedir.
        """
        self.a.marcar("aegis")
        args = {"path": self._RUTA, "content": "x"}
        primera = autonomy.decide("aegis_write_file", args, run_id="r1",
                                  paso=1, almacen_=self.a)
        token = self.a.resolver(primera.peticion, "aprobar")["token"]

        # Otra tool con el mismo token.
        d1 = autonomy.decide("aegis_patch_file",
                             {"path": self._RUTA, "old": "a", "new": "b"},
                             run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertFalse(d1.ok)
        self.assertIn("aegis_write_file", d1.motivo)

        # La misma tool con otros argumentos: es OTRA escritura y hay que verla.
        p2 = autonomy.decide("aegis_write_file", args, run_id="r2", paso=1,
                             almacen_=self.a)
        t2 = self.a.resolver(p2.peticion, "aprobar")["token"]
        d2 = autonomy.decide("aegis_write_file",
                             {"path": self._RUTA, "content": "otra"},
                             run_id="r2", paso=1, almacen_=self.a, token=t2)
        self.assertFalse(d2.ok)
        self.assertIn("argumentos", d2.motivo)

    def test_el_token_sirve_a_un_run_distinto(self):
        """Aprobar y relanzar crea un run nuevo, y el token tiene que servir.

        La primera versión ataba el token al `run_id`, así que el token se
        consumía en un run y el siguiente —con otro id— volvía a pedir permiso
        para siempre. La fila decía "aprobada" y no pasaba nada: el fallo más
        silencioso posible.
        """
        self.a.marcar("aegis")
        args = {"path": self._RUTA, "content": "x"}
        primera = autonomy.decide("aegis_write_file", args, run_id="run_viejo",
                                  paso=1, almacen_=self.a)
        token = self.a.resolver(primera.peticion, "aprobar")["token"]
        nuevo = autonomy.decide("aegis_write_file", args, run_id="run_nuevo",
                                paso=1, almacen_=self.a, token=token)
        self.assertTrue(nuevo.ok, nuevo.motivo)

    def test_un_token_inventado_no_abre_nada(self):
        self.a.marcar("aegis")
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a, token="inventado")
        self.assertFalse(d.ok)
        self.assertIn("ya se usó", d.motivo)

    def test_sin_proyecto_no_escribe(self):
        self.a.marcar("aegis")
        d = autonomy.decide("aegis_write_file", {"content": "x"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertFalse(d.ok)
        self.assertIn("proyecto", d.motivo)


class TestSiemprePregunta(_Piso):
    """El nivel 3 pide OK en todos los modos, incluso en `pleno`.

    ## Por qué `pleno` no significa "sin preguntar"
    Un modo que dispense de la cola no sería autonomía con dientes: sería
    confianza a ciegas. "Pleno" significa "también lo de fuera, si lo apruebas".
    """

    def test_pleno_sigue_preguntando(self):
        self.a.set_modo("pleno")
        for tool, args in (("db_migrate", {"project": "compra-unida"}),
                           ("neon_branch", {"project": "portafolio"}),
                           ("install_apk", {"target": "telefono"}),
                           ("build_apk", {})):
            d = autonomy.decide(tool, args, run_id="r1", paso=1, almacen_=self.a)
            self.assertFalse(d.ok, f"{tool} no ha preguntado")
            self.assertIsNotNone(d.peticion, tool)

    def test_el_motivo_dice_que_y_por_que(self):
        d = autonomy.decide("db_migrate", {"project": "compra-unida"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertIn("migrar la base", d.motivo)
        self.assertIn("compra-unida", d.motivo)
        # Por qué es especial esta: un revert de git no lo deshace.
        self.assertIn("revert", d.motivo)

    def test_install_dice_que_no_se_abre(self):
        """Lo que hay que aprobar sin surprises: instalar no es lanzar."""
        d = autonomy.decide("install_apk", {"target": "telefono"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertIn("NO se abrirá", d.motivo)
        self.assertIn("telefono", d.motivo)

    def test_reintentar_es_la_misma_peticion(self):
        """Antes este test decía lo contrario: que cada intento creaba una fila.

        Y era lo que había, y por eso el móvil llegó a enseñar **31 tarjetas
        idénticas** de la misma llamada. Lo primero que hace un agente al recibir
        un «no» es reintentar lo mismo, así que cada reintento era una tarjeta
        más y la cola no tenía techo.

        Ahora lo correcto es lo de aquí: el reintento del mismo run, con la misma
        tool y los mismos argumentos, **devuelve la petición que ya está
        pendiente**. Es la misma decisión esperando a la misma persona, y que
        aparezca una vez es más honesto que aparecer 31 — 31 tarjetas invitan a
        contestarlas una por una, que es trabajo inventado.

        La dedup se explica entera en `pedir()` y tiene sus tests en
        `tests/test_cola_aprobaciones.py`.
        """
        p1 = autonomy.decide("db_migrate", {"project": "compra-unida"},
                             run_id="r1", paso=1, almacen_=self.a).peticion
        p2 = autonomy.decide("db_migrate", {"project": "compra-unida"},
                             run_id="r1", paso=2, almacen_=self.a).peticion
        self.assertEqual(p1, p2)

    def test_otros_runs_si_son_peticiones_distintas(self):
        """Aprobar uno no debe aprobar el otro sin que te enteres."""
        p1 = autonomy.decide("db_migrate", {"project": "compra-unida"},
                             run_id="r1", paso=1, almacen_=self.a).peticion
        p2 = autonomy.decide("db_migrate", {"project": "compra-unida"},
                             run_id="r2", paso=1, almacen_=self.a).peticion
        self.assertNotEqual(p1, p2)


class TestBaseRoja(_Piso):
    """Un verificador en rojo antes de empezar detiene el run.

    ## Por qué
    Si no sabes qué fallaba antes de tocar nada, el rojo deja de servir de
    referencia: cualquier cosa que hagas después parece mejorar o empeorar
    respecto a un punto que nadie conoce.
    """

    def setUp(self):
        super().setUp()
        self.a.marcar("aegis")

    def test_rojo_deteniene_la_escritura(self):
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a,
                            estado_base={"alias": "aegis", "rojo": True,
                                         "detalle": "3 tests rojos"})
        self.assertFalse(d.ok)
        self.assertIn("3 tests rojos", d.motivo)

    def test_verde_deja_pasar(self):
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a,
                            estado_base={"alias": "aegis", "rojo": False})
        self.assertIsNotNone(d.peticion)
        self.assertIn("Primera vez", d.motivo,
                      "con la base verde solo debe pedir por ser la primera vez")

    def test_sin_estado_base_no_inventa_rojo(self):
        """Sin medida no hay veredicto. Un `rojo` supuesto frenaría a Aegis
        siempre, y un freno permanente es un freno que nadie mira."""
        d = autonomy.decide("aegis_write_file",
                            {"path": self._RUTA, "content": "x"},
                            run_id="r1", paso=1, almacen_=self.a)
        self.assertIsNotNone(d.peticion)
        self.assertNotIn("verificador", d.motivo)


class TestEscrituraDestructiva(_Piso):
    """Reescribir un archivo no es arreglarlo."""

    def test_borrar_muchas_lineas_pregunta(self):
        self.a.marcar("aegis")
        # Primero, la primera vez sobre el fichero.
        ruta = Path(self.tmp)
        with mock.patch("app.autonomy.tocado_alguna_vez", return_value=True), \
             mock.patch("app.mcp_ops._safe_resolve") as res:
            # La ruta del objetivo sale del repo donde se ejecuta el test, no de
            # la máquina donde se escribió. `decide` la resuelve a proyecto para
            # comprobar que está marcado, así que una ruta de otro sitio da
            # «sin marcar» y el test falla por un motivo que no es el suyo.
            res.return_value = entorno.RAIZ / "mobile" / "lib" / "app.dart"
            with mock.patch.object(Path, "exists", return_value=True), \
                 mock.patch.object(Path, "read_text", return_value="x\n" * 1000):
                d = autonomy.decide(
                    "aegis_write_file",
                    {"path": self._RUTA, "content": "y\n" * 10},
                    run_id="r1", paso=1, almacen_=self.a)
        self.assertFalse(d.ok)
        self.assertIsNotNone(d.peticion)
        self.assertIn("990", d.motivo)

    def test_un_cambio_pequeno_no_pregunta(self):
        self.a.marcar("aegis")
        with mock.patch("app.autonomy.tocado_alguna_vez", return_value=True), \
             mock.patch("app.mcp_ops._safe_resolve") as res:
            # La ruta del objetivo sale del repo donde se ejecuta el test, no de
            # la máquina donde se escribió. `decide` la resuelve a proyecto para
            # comprobar que está marcado, así que una ruta de otro sitio da
            # «sin marcar» y el test falla por un motivo que no es el suyo.
            res.return_value = entorno.RAIZ / "mobile" / "lib" / "app.dart"
            with mock.patch.object(Path, "exists", return_value=True), \
                 mock.patch.object(Path, "read_text", return_value="x\n" * 100):
                d = autonomy.decide(
                    "aegis_write_file",
                    {"path": self._RUTA, "content": "y\n" * 99},
                    run_id="r1", paso=1, almacen_=self.a)
        self.assertTrue(d.ok, d.motivo)


class TestAprobacionDeUnSoloUso(_Piso):
    """El token es de un solo uso, y la denegación guarda el motivo."""

    def _pedir(self):
        d = autonomy.decide("db_migrate", {"project": "compra-unida"},
                            run_id="r1", paso=1, almacen_=self.a)
        return d.peticion

    def test_aprobar_devuelve_token(self):
        pid = self._pedir()
        p = self.a.resolver(pid, "aprobar")
        self.assertEqual(p["estado"], "aprobada")
        self.assertTrue(p["token"])

    def test_el_token_se_gasta_una_vez(self):
        pid = self._pedir()
        token = self.a.resolver(pid, "aprobar")["token"]
        self.assertIsNotNone(self.a.gastar(token))
        self.assertIsNone(self.a.gastar(token),
                          "un token reusado convertiría la cola en una puerta corriente")

    def test_gastar_un_token_inventado(self):
        self.assertIsNone(self.a.gastar("no-existe"))

    def test_aprobar_dos_veces_falla(self):
        pid = self._pedir()
        self.a.resolver(pid, "aprobar")
        with self.assertRaises(AutonomiaError) as cm:
            self.a.resolver(pid, "aprobar")
        self.assertIn("aprobada", str(cm.exception))

    def test_denegar_guarda_el_motivo_y_se_lee(self):
        """El ciclo completo: denegar **con por qué** es lo que hace que la
        confianza crezca. Sin motivo, denegar es solo un "no" que no se puede
        aplicar a la siguiente vez."""
        pid = self._pedir()
        self.a.denegar_con_motivo(pid, "compra-unida solo lee, todavía no migra")
        with mock.patch.object(autonomy, "almacen", lambda: self.a):
            resumen = autonomy.resume_denegaciones()
        self.assertIn("compra-unida", resumen)
        self.assertIn("solo lee", resumen)

    def test_sin_denegaciones_el_resumen_no_inventa(self):
        # Se apunta el global al almacén del test: `resume_denegaciones` existe
        # para inyectarse en el prompt, y el prompt lo compone el bucle real.
        with mock.patch.object(autonomy, "almacen", lambda: self.a):
            self.assertEqual(autonomy.resume_denegaciones(), "",
                             "un resumen vacío debe estar vacío, no decir 'nada'")

    def test_el_motivo_de_denegacion_usa_el_almacen_del_test(self):
        """`resume_denegaciones` lee el global, así que el test monta el suyo.

        Es la costura fea del módulo y se anota aquí para que no se lea como un
        descuido: la función existe para inyectarse en el prompt, y el prompt lo
        compone el bucle, que sí usa el almacén real.
        """
        pid = self._pedir()
        self.a.denegar_con_motivo(pid, "prueba de costura")
        with mock.patch.object(autonomy, "almacen", lambda: self.a):
            self.assertIn("costura", autonomy.resume_denegaciones())


class TestElTokenNoSeQuemaPorUnDesajuste(_Piso):
    """Un permiso que no se puede usar es un permiso que hay que volver a pedir.

    ## El fallo que esto previene
    `decide()` gastaba el token **antes** de comprobar que la llamada era la
    aprobada. Medido con `project_create`: el modelo pedía el alta con el
    verificador como objeto en una llamada y como dos cadenas en la siguiente;
    el token se gastaba en el intento que no encajaba, y el permiso quedaba
    inservible. Tres intentos, tres aprobaciones, ninguna escritura.

    Ahora se **mira** antes de cobrar: un desajuste devuelve el motivo y deja el
    permiso vivo.
    """

    def _aprobar(self, tool="project_create", args=None):
        pid = autonomy.decide(tool, args or {"alias": "acme"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        return pid, self.a.resolver(pid, "aprobar")["token"]

    def test_el_desajuste_no_gasta_el_permiso(self):
        _, token = self._aprobar()
        d = autonomy.decide("project_create", {"alias": "otro"},
                            run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertFalse(d.ok)
        # El motivo lo dice, porque si no parece un fallo del puente.
        self.assertIn("otra llamada", d.motivo)
        self.assertIn("No lo he gastado", d.motivo)
        # Y el permiso sigue ahí para cuando el modelo repita la llamada buena.
        self.assertEqual(len(self.a.aprobadas_sin_gastar()), 1)
        self.assertIsNotNone(self.a.gastar(token))

    def test_otra_tool_no_gasta_el_permiso(self):
        _, token = self._aprobar()
        d = autonomy.decide("build_apk", {"alias": "acme"},
                            run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertFalse(d.ok)
        self.assertEqual(len(self.a.aprobadas_sin_gastar()), 1)

    def test_si_coincide_se_gasta_y_pasa(self):
        _, token = self._aprobar()
        d = autonomy.decide("project_create", {"alias": "acme"},
                            run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertTrue(d.ok, d.motivo)
        self.assertEqual(self.a.aprobadas_sin_gastar(), [])

    def test_mirar_no_es_gastar(self):
        _, token = self._aprobar()
        self.assertIsNotNone(self.a.por_token(token))
        self.assertIsNotNone(self.a.por_token(token))
        self.assertEqual(len(self.a.aprobadas_sin_gastar()), 1,
                         "mirar dos veces no puede gastar el token")
        self.assertIsNone(self.a.por_token("inventado"))

    def test_gastado_avisa_para_que_el_run_no_lo_repita(self):
        """El veredicto dice que gastó el token, y el bucle deja de mandarlo.

        Sin esto, tras un alta correcta el run seguía pasando el mismo token en
        cada paso y todo lo demás moría con "ese permiso ya se usó" — medido: el
        paso 2 del alta fue un `ficha_read` que es de las tools libres, y se
        negó por un permiso que ya no tenía nada que ver con ella.
        """
        _, token = self._aprobar()
        d = autonomy.decide("project_create", {"alias": "acme"},
                            run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertTrue(d.uso_token, "el bucle no puede saber que hay que soltarlo")
        # Y sin token, una tool libre se evalúa por su nivel de verdad.
        d2 = autonomy.decide("ficha_read", {"alias": "acme"},
                             run_id="r2", paso=1, almacen_=self.a)
        self.assertTrue(d2.ok, d2.motivo)
        self.assertFalse(d2.uso_token)

    def test_un_token_que_no_casa_no_se_gasta(self):
        """Y por tanto sigue vivo para el paso en el que sí case."""
        _, token = self._aprobar()
        d = autonomy.decide("project_create", {"alias": "otro"},
                            run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertFalse(d.uso_token)
        d2 = autonomy.decide("project_create", {"alias": "acme"},
                             run_id="r1", paso=2, almacen_=self.a, token=token)
        self.assertTrue(d2.ok, d2.motivo)


class TestEjecutarLoAprobado(_Piso):
    """Ejecutar la llamada aprobada, sin modelo en medio.

    ## Por qué no es solo "relanzar"
    El token valida la llamada, no el run. Relanzar obliga a que el modelo vuelva
    a emitir **la misma** tool con **los mismos** argumentos, y medido con
    `project_create` eso pasaba de cuatro intentos en uno. Aquí se ejecuta lo que
    está en la fila: lo que leíste antes de decir que sí.

    ## Lo que se comprueba
    Que ejecuta lo aprobado, que **gasta** el permiso, que no ejecuta una tool que
    no es de nivel 3 (sería saltarse su propia puerta) y que deja rastro.

    ## Y por qué aquí se espera a que termine
    `/ejecutar` responde **ya** y ejecuta en un hilo (A-066): una tool de nivel 3
    puede ser la puerta completa del despliegue —analyze, tests y humo— y eso son
    minutos, así que con la respuesta esperando el móvil se cansaba a los 10 s y
    pintaba «No pude ejecutar» con el token ya gastado y el trabajo a medias.

    Los tests **no** accordingly-adaptan el contrato asserting `ok`/`result` en la
    respuesta: affirmarían el bug. Afirman lo que de verdad importa — que el
    efecto ocurre — esperando a su efecto, y que la respuesta dice `en_curso`.
    """

    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        from app import alta as alta_mod
        from app import fichas as fichas_mod
        from app import main as main_mod
        from app import projects as projects_mod
        import tempfile
        from pathlib import Path as _P

        # Un workspace de mentira. Sin esto el test creaba un proyecto de verdad
        # en ~/Workspace: ejecutar una aprobación **es** escribir, y eso en un
        # test deja basura que luego parece un fallo del alta (A-057).
        ws = _P(tempfile.mkdtemp())
        (ws / "apps").mkdir()
        (ws / "registro").mkdir()
        for mod, attr, valor in ((alta_mod, "REGISTRO_DIR", ws / "registro"),
                                 (fichas_mod, "FICHAS_DIR", ws / "fichas"),
                                 (fichas_mod, "PRIVADAS_DIR", ws / "priv"),
                                 (projects_mod, "REGISTRO_DIR", ws / "registro")):
            patcher = mock.patch.object(mod, attr, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = mock.patch("app.config.get_settings", return_value=mock.Mock(
            workspace_dir=str(ws), workspace_areas="apps,web,mobile"))
        settings.start()
        self.addCleanup(settings.stop)
        codigo = {a: p for a, p in projects_mod.PROJECTS.items()
                  if a not in projects_mod._DATOS}
        projects_mod.PROJECTS.clear()
        projects_mod._DATOS.clear()
        self.addCleanup(lambda: (projects_mod.PROJECTS.clear(),
                                 projects_mod.PROJECTS.update(codigo),
                                 projects_mod._DATOS.clear()))
        self.ws = ws

        self._antes = autonomy.ALMACEN
        autonomy.ALMACEN = self.a
        self.addCleanup(lambda: setattr(autonomy, "ALMACEN", self._antes))
        self.mod = main_mod
        self.client = TestClient(main_mod.app)
        self.cab = {"X-Aegis-Token": main_mod.settings.aegis_api_key}

    def _pedir(self, tool="project_create", args=None):
        pid = autonomy.decide(tool, args or {"alias": "acme", "area": "apps",
                                             "kind": "producto"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.a.resolver(pid, "aprobar")
        return pid

    def _esperar(self, condicion, segundos=15):
        """Espera a que el hilo de la ejecución llegue a su efecto.

        Sin esto los tests afirmarían o bien `ok` en una respuesta que ya no lo
        trae, o bien «no pasó nada», que tampoco es cierto: la ejecución va en
        segundo plano y llega. Se espera **al efecto**, no al hilo.
        """
        import time as _t
        fin = _t.time() + segundos
        while _t.time() < fin:
            if condicion():
                return True
            _t.sleep(0.05)
        return False

    def _ejecutar(self, pid):
        r = self.client.post(f"/aprobaciones/{pid}/ejecutar", headers=self.cab)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_ejecuta_la_llamada_aprobada(self):
        pid = self._pedir()
        cuerpo = self._ejecutar(pid)
        self.assertEqual(cuerpo["tool"], "project_create")
        # La respuesta dice que **arrancó**, y solo eso. Este es el contrato: un
        # `ok` aquí mentiría sobre un trabajo que todavía no ha terminado.
        self.assertEqual(cuerpo["estado"], "en_curso")
        # Se ejecutó DE VERDAD: el alta se ve en el registro del workspace de
        # mentira. Afirmar sobre el texto de la respuesta solo probaría la cadena.
        alta = self.ws / "registro" / "acme.json"
        self.assertTrue(self._esperar(alta.exists),
                        "la llamada aprobada no llegó a ejecutarse en segundo plano")
        self.assertEqual(json.loads(alta.read_text(encoding="utf-8"))["alias"],
                         "acme")

    def test_una_denegacion_de_la_tool_no_se_pinta_como_hecho(self):
        """La tool dice que no y devuelve texto, sin lanzar. Si esto se pintara
        como 'hecho', estaríamos repitiendo el falso éxito de A-016."""
        pid = self._pedir(args={"alias": "otro", "area": "/etc", "kind": "producto"})
        import tempfile
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp())
        with mock.patch.object(self.mod, "_runs_dir", lambda: tmp):
            self._ejecutar(pid)
            rastro = tmp / f"aprobacion-{pid}.jsonl"
            self.assertTrue(self._esperar(rastro.exists),
                            "la ejecución no dejó rastro")
            cuerpo = json.loads(rastro.read_text(encoding="utf-8")
                                .strip().splitlines()[-1])["payload"]
        # El veredicto sale del rastro, que es lo que el móvil acaba leyendo.
        self.assertNotEqual(cuerpo.get("fin"), "task.failed",
                            "una denegación de la tool no puede cerrarse como hecha")

    def test_el_permiso_se_gasta_y_no_se_repite(self):
        pid = self._pedir()
        self.assertEqual(self.client.post(
            f"/aprobaciones/{pid}/ejecutar", headers=self.cab).status_code, 200)
        r2 = self.client.post(f"/aprobaciones/{pid}/ejecutar", headers=self.cab)
        self.assertEqual(r2.status_code, 409)
        self.assertIn("ya se usó", r2.json()["detail"])

    def test_una_peticion_pendiente_no_se_ejecuta(self):
        pid = autonomy.decide("project_create", {"alias": "acme"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        r = self.client.post(f"/aprobaciones/{pid}/ejecutar", headers=self.cab)
        self.assertEqual(r.status_code, 409)

    def test_una_tool_que_no_es_de_nivel_3_no_pasa(self):
        """Ejecutar por aquí una tool normal sería saltarse la puerta que decidió
        su nivel, y esa puerta existe."""
        p = self.a.pedir(run_id="r1", paso=1, tool="ficha_read",
                         args={"alias": "acme"}, motivo="m")
        self.a.resolver(p, "aprobar")
        r = self.client.post(f"/aprobaciones/{p}/ejecutar", headers=self.cab)
        self.assertEqual(r.status_code, 400)
        self.assertIn("nivel 3", r.json()["detail"])

    def test_un_hilo_que_murie_avisa_en_vez_de_desaparecer(self):
        """El fallo que casi no se ve: una excepción en el hilo de la ejecución.

        Pasó al escribir esto: la función usaba `ToolNotAllowed` sin importarlo y
        moría con `NameError` **después** de gastar el permiso y de responder al
        móvil. El cliente tenía un «en curso», no pasaba nada, y ningún test se
        enteró porque todos miraban la respuesta HTTP — que era correcta.

        Así que se comprueban las dos cosas que un hilo sí puede hacer aunque
        reviente: dejar el rastro y avisar al teléfono.
        """
        import tempfile
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp())
        pid = self._pedir()
        with mock.patch.object(self.mod, "_runs_dir", lambda: tmp), \
             mock.patch.object(self.mod, "_ejecutar_aprobacion_en_segundo_plano",
                               side_effect=RuntimeError("el hilo reventó")), \
             mock.patch("app.deploy.avisar_fallo_telefono") as avisar:
            r = self.client.post(f"/aprobaciones/{pid}/ejecutar", headers=self.cab)
            self.assertEqual(r.status_code, 200, r.text)
            # La respuesta sigue siendo correcta: el fallo es del hilo, no de la
            # puerta. Por eso no puedeNbajarse a un 500.
            self.assertEqual(r.json()["estado"], "en_curso")
            ruta = tmp / f"aprobacion-{pid}.jsonl"
            self.assertTrue(self._esperar(ruta.exists),
                            "un hilo que murió no dejó rastro: el gesto se pierde")
            self.assertTrue(self._esperar(lambda: avisar.called),
                            "un hilo que murió no avisó: nadie se entera")
            aviso = avisar.call_args[0][1]
            self.assertIn("el hilo reventó", aviso)

    def test_deja_rastro_en_el_jsonl(self):
        import json as _json
        import tempfile
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp())
        with mock.patch.object(self.mod, "_runs_dir", lambda: tmp):
            pid = self._pedir()
            self._ejecutar(pid)
            # El rastro lo escribe el hilo, así que puede no estar todavía: se
            # espera a que exista en vez de leerlo a la carrera.
            ruta = _P(tmp) / f"aprobacion-{pid}.jsonl"
            self.assertTrue(self._esperar(ruta.exists),
                            "la ejecución en segundo plano no dejó JSONL")
            lineas = ruta.read_text(encoding="utf-8").strip().splitlines()
        eventos = [_json.loads(x)["event"] for x in lineas]
        self.assertIn("tool.completed", eventos)
        self.assertIn("task.done", eventos)
        # El run al que pertenecía la petición queda dicho: sin esto, el JSONL
        # parece de otro sitio.
        self.assertTrue(any(_json.loads(x)["at_run"] == "r1" for x in lineas))


class TestElPermisoNoSePierde(_Piso):
    """Aprobar tiene que poder cerrarse, incluso desde otra app o más tarde.

    El token solo vivía en la respuesta del POST: la app lo descartaba, y si se
    cerraba entre "aprobar" y "relanzar" ya no había dónde recuperarlo. Eso es un
    permiso que se cobra y luego se tira. Aquí se comprueba que la cola lo
    devuelve mientras no se haya gastado, y que desaparece en cuanto se gasta.
    """

    def _aprobar(self, tool="db_migrate", args=None):
        pid = autonomy.decide(tool, args or {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        return pid, self.a.resolver(pid, "aprobar")["token"]

    def test_una_aprobada_sin_gastar_sigue_en_la_cola(self):
        pid, token = self._aprobar()
        self.assertEqual([p["id"] for p in self.a.pendientes()], [])
        lista = self.a.aprobadas_sin_gastar()
        self.assertEqual([p["id"] for p in lista], [pid])
        self.assertEqual(lista[0]["token"], token)
        self.assertEqual(lista[0]["tool"], "db_migrate")

    def test_al_gastarse_deja_de_salir(self):
        _, token = self._aprobar()
        self.a.gastar(token)
        self.assertEqual(self.a.aprobadas_sin_gastar(), [])

    def test_las_pendientes_siguen_sin_token(self):
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.assertNotIn("token", self.a.pendientes()[0])
        self.assertEqual(self.a.aprobadas_sin_gastar(), [])
        del pid

    def test_un_permiso_viejo_no_se_ofrece(self):
        """Caduca. Un botón de relanzar sobre algo que nadie recuerda aprobar
        es ruido, y la lista crecería sola si no caducara."""
        _, token = self._aprobar()
        # Envejecido: se resolvió hace tres días.
        self.a._c.execute(
            "UPDATE aprobaciones SET resuelto=datetime('now','-3 days')")
        self.a._c.commit()
        self.assertEqual(self.a.aprobadas_sin_gastar(), [])
        # El canje sigue siendo válido si alguien lo guardó: caducar es no
        # ofrecerlo, no romper un permiso ya concedido.
        self.assertIsNotNone(self.a.gastar(token))

    def test_el_endpoint_expone_las_dos_listas(self):
        from fastapi.testclient import TestClient
        from app import main as main_mod
        _, token = self._aprobar()
        _, token2 = self._aprobar(args={"project": "portafolio"})
        self.assertTrue(token and token2)
        with mock.patch.object(autonomy, "ALMACEN", self.a), \
                mock.patch.object(main_mod, "autonomy", lambda: self.a):
            cliente = TestClient(main_mod.app)
            r = cliente.get("/aprobaciones",
                            headers={"X-Aegis-Token": main_mod.settings.aegis_api_key})
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertEqual(len(cuerpo["aprobadas"]), 2)
        self.assertEqual(cuerpo["pendientes"], [])
        # Lo que hace posible relanzar: el token viene en la lista.
        self.assertTrue(all(p["token"] for p in cuerpo["aprobadas"]))


class TestColaVisibleDesdeElMovil(_Piso):
    """Lo que el móvil ve tiene que ser suficiente para decidir."""

    def _pedir(self):
        return autonomy.decide("db_migrate", {"project": "compra-unida"},
                               run_id="r1", paso=1, almacen_=self.a).peticion

    def test_pendientes_traen_el_motivo(self):
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=3, almacen_=self.a).peticion
        pend = self.a.pendientes("r1")
        self.assertEqual(len(pend), 1)
        p = pend[0]
        self.assertEqual(p["id"], pid)
        self.assertEqual(p["paso"], 3)
        self.assertEqual(p["proyecto"], "compra-unida")
        self.assertIn("migrar la base", p["motivo"])
        self.assertIn("project", p["argumentos"])

    def test_resuelta_no_sale_entre_las_pendientes(self):
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.a.resolver(pid, "aprobar")
        self.assertEqual(self.a.pendientes("r1"), [])

    def test_una_peticion_de_run_terminado_caduca(self):
        """Si el móvil la toca tarde, el token no sirve de nada: el run ya
        terminó. Se marca `caducada` en vez de borrarse, para que siga
        consta que existió."""
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.assertEqual(self.a.limpiar_pendientes_de("r1"), 1)
        self.assertEqual(self.a.pendientes("r1"), [])
        self.assertEqual(self.a.buscar(pid)["estado"], "caducada")

    def test_una_peticion_caducada_no_se_puede_aprobar(self):
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.a.limpiar_pendientes_de("r1")
        with self.assertRaises(AutonomiaError):
            self.a.resolver(pid, "aprobar")

    def test_otra_decision_no_se_acepta(self):
        pid = self._pedir()
        with self.assertRaises(AutonomiaError):
            self.a.resolver(pid, "quiza")


class TestModoInvalido(_Piso):
    def test_modo_que_no_existe_no_se_guarda(self):
        with self.assertRaises(AutonomiaError) as cm:
            self.a.set_modo("invasor")
        self.assertIn("permiso", str(cm.exception))
        self.assertNotEqual(self.a.modo(), "invasor")

    def test_desmarcar_un_proyecto_no_marcado(self):
        self.assertFalse(self.a.desmarcar("nunca-existio"))


if __name__ == "__main__":
    unittest.main()

class TestElCicloMedido(_Piso):
    """El recorrido entero, medido, porque es el que da la confianza.

    ## Qué comprueba
    Que un `db_migrate` **no** se ejecuta, que la cola queda con el motivo, que
    denegar con razón la guarda, y que la razón llega al prompt del siguiente
    run. La última parte es la importante: sin ella, la columna
    `razon_denegacion` es un registro del bridge y no una memoria del agente, y
    denegar con motivo sería un gesto que nadie lee.
    """

    def test_migrar_se_pregunta_y_no_se_ejecuta(self):
        from unittest import mock
        with mock.patch("app.mcp_ops.db_query") as _:
            with mock.patch("app.autopilot._execute") as exec_:
                d = autonomy.decide("db_migrate", {"project": "compra-unida"},
                                    run_id="r1", paso=1, almacen_=self.a)
        self.assertFalse(d.ok)
        # Lo que no se ejecuta es lo que hace la puerta funcionar: `decide` se
        # llama ANTES de `_execute`, no después como informe.
        exec_.assert_not_called()

    def test_el_motivo_llega_al_prompt_siguiente(self):
        from app.autopilot import build_system_prompt
        pid = autonomy.decide("db_migrate", {"project": "compra-unida"},
                              run_id="r1", paso=1, almacen_=self.a).peticion
        self.a.denegar_con_motivo(pid, "compra-unida solo lee por ahora")
        with mock.patch.object(autonomy, "almacen", lambda: self.a):
            prompt = build_system_prompt("", "compra-unida", "", enfoque="")
        self.assertIn("compra-unida solo lee por ahora", prompt)
        self.assertIn("No lo vuelvas a proponer", prompt)

    def test_sin_denegaciones_el_prompt_no_crece(self):
        from app.autopilot import build_system_prompt
        with mock.patch.object(autonomy, "almacen", lambda: self.a):
            prompt = build_system_prompt("", "compra-unida", "", enfoque="")
        self.assertNotIn("Lo que ya me dijiste que no", prompt)


class TestBaseMedida(_Piso):
    """La línea base: se mide antes de escribir, y no se inventa."""

    def test_proyecto_sin_verificador_no_es_rojo(self):
        """`None` es "no pude mirar", no "está mal".

        Confundirlos frenaría a Aegis de forma permanente y sin causa. Un freno
        permanente es un freno que nadie mira.

        El proyecto se declara aquí, sin verificador y con el registro vacío:
        antes se usaba `data-sending`, que en un clon ajeno no existe y daba
        «no está en el registro» — un motivo distinto del que se quiere probar.
        """
        import tempfile
        from pathlib import Path
        from unittest import mock
        from app import projects
        from app.projects import Project
        from app.autonomy import medir_base
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Project(alias="sin-verificador", root=Path(tmp), strategy="psql")
            with mock.patch.dict(projects.PROJECTS, {"sin-verificador": cfg},
                                 clear=True):
                m = medir_base("sin-verificador")
        self.assertIsNone(m["rojo"])
        self.assertIn("verificador", m["detalle"])

    def test_una_base_que_empeora_se_dice(self):
        from app.autonomy import empeora
        antes = {"alias": "trazeurs", "problemas": 452}
        despues = {"alias": "trazeurs", "problemas": 460}
        self.assertIn("452", empeora(antes, despues))
        self.assertIn("460", empeora(antes, despues))

    def test_una_base_que_mejora_no_se_dice(self):
        from app.autonomy import empeora
        self.assertEqual(empeora({"problemas": 460}, {"problemas": 452}), "")

    def test_sin_cifras_no_se_compara(self):
        """Decir "empeoró" sin números es una conjetura, y una conjetura que
        frena el trabajo molesta más de lo que ayuda."""
        from app.autonomy import empeora
        self.assertEqual(empeora({"problemas": None}, {"problemas": 5}), "")
        self.assertEqual(empeora({"rojo": True}, {"rojo": False}), "")
        self.assertEqual(empeora(None, {"rojo": False}), "")


class TestElRunSeEscribeEnDisco(unittest.TestCase):
    """Un run de autopilot tiene que existir fuera de la memoria del proceso.

    ## El fallo que esto previene
    Se añadió la caída al disco (`GET /autopilot/{id}` reconstruye desde el
    JSONL) y parecía funcionar... hasta que se probó con un run real: los JSONL
    los escribía `relay`, que solo ve los runs de **Hermes**. Los de autopilot no
    escribían ninguno. O sea, que la única copia seguía siendo el dict en
    memoria, y la "persistencia" era una promesa.

    Es A-016 por el camino del almacenamiento: un endpoint que reconstruye desde
    un fichero que nadie escribe devuelve 404 con toda la aplomb del mundo.
    """

    def setUp(self) -> None:
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-runs-"))
        import app.main as m
        self._main = m
        self._dir_real = m._runs_dir
        m._runs_dir = lambda: self.tmp

    def tearDown(self) -> None:
        self._main._runs_dir = self._dir_real

    def _run(self, fin="sin_tools", tools=("projects_list",)):
        return {
            "model": "qwen2.5:7b",
            "steps": len(tools),
            "fin": fin,
            "answer": "listo",
            "trace": [{"step": i + 1, "tool": t, "ok": True}
                      for i, t in enumerate(tools)],
        }

    def test_el_jsonl_se_escribe(self):
        self._main._escribir_jsonl_de_autopilot("autopilot_test", "aegis", self._run())
        f = self.tmp / "autopilot_test.jsonl"
        self.assertTrue(f.exists(), "el run no dejó rastro en disco")

    def test_el_evento_terminal_es_del_vocabulario(self):
        """`task.max_steps` no es un evento terminal: quien lo lea no sabe que
        el run acabó. El motivo va en el payload."""
        import json as _json
        for fin, esperado in (("sin_tools", "task.done"),
                              ("max_steps", "task.done"),
                              ("failed", "task.failed"),
                              ("esperando_ok", "task.stopped")):
            self._main._escribir_jsonl_de_autopilot(f"r_{fin}", "aegis",
                                                    self._run(fin=fin))
            lineas = [x for x in (self.tmp / f"r_{fin}.jsonl")
                      .read_text(encoding="utf-8").splitlines() if x.strip()]
            ultimo = _json.loads(lineas[-1])
            self.assertEqual(ultimo["event"], esperado, fin)
            self.assertEqual(ultimo["payload"]["fin"], fin)

    def test_los_pasos_se_cuentan_en_ambos_formatos(self):
        """Hermes emite `tool.started` y autopilot solo `tool.completed`.
        Contar solo uno dejaba la mitad de los runs con cero pasos, que se lee
        como "no hizo nada"."""
        import json as _json
        self._main._escribir_jsonl_de_autopilot("r_completed", "aegis", self._run())
        f = self.tmp / "r_completed.jsonl"
        # Se reescribe a mano con el otro esquema para comprobar los dos.
        solo_started = self.tmp / "r_started.jsonl"
        solo_started.write_text("\n".join([
            _json.dumps({"at": "x", "run_id": "r_started", "event": "task.created",
                         "agent": "w", "at_run": "", "payload": {}}),
            _json.dumps({"at": "x", "run_id": "r_started", "event": "tool.started",
                         "agent": "w", "at_run": "",
                         "payload": {"tool": "projects_list"}}),
            _json.dumps({"at": "x", "run_id": "r_started", "event": "task.done",
                         "agent": "w", "at_run": "", "payload": {}}),
        ]), encoding="utf-8")
        self.assertEqual(self._main._resumir_run(f)["pasos"], 1)
        self.assertEqual(self._main._resumir_run(solo_started)["pasos"], 1)

    def test_el_lector_reconstruye_el_estado(self):
        import json as _json
        self._main._escribir_jsonl_de_autopilot(
            "r_leer", "aegis", self._run(fin="esperando_ok", tools=("db_migrate",)))
        st = self._main._autopilot_desde_disco("r_leer")
        self.assertEqual(st.status, "stopped")
        self.assertEqual(st.fin, "esperando_ok")

    def test_un_run_inexistente_es_404_no_excepcion(self):
        import fastapi
        with self.assertRaises(fastapi.HTTPException) as cm:
            self._main._autopilot_desde_disco("no_existe")
        self.assertEqual(cm.exception.status_code, 404)


class TestLaPuertaDeLoNuevo(unittest.TestCase):
    """Lo nuevo exige token; lo viejo se queda como estaba.

    ## Por qué no se cierra todo de golpe
    Cambiar la auth de los endpoints que ya existen rompería la app el día que se
    active, y un sistema que hay que reconfigurar antes de poder usarlo es un
    sistema que nadie configura. La regla es: **lo nuevo nace cerrado**.

    ## Por qué esto importa más de lo que parece
    Lo que hay detrás de esta puerta no es "ver una traza". Es dar permiso de
    escritura sobre los proyectos, denegar una aprobación de despliegue y leer
    las notas. Sin clave, cualquiera que llegue a la red privada puede letting
    Aegis escribir en tu código.
    """

    def setUp(self) -> None:
        import app.main as m
        self._main = m
        import app.config as cfg
        self._cfg = cfg

    def _con_clave(self, valor: str):
        return mock.patch.object(self._main.settings, "aegis_api_key", valor)

    def test_sin_clave_configurada_no_exige(self):
        with self._con_clave(""):
            self._main.exigir_token(None)

    def test_sin_cabecera_con_clave_configurada_falla(self):
        import fastapi
        with self._con_clave("secreto"):
            with self.assertRaises(fastapi.HTTPException) as cm:
                self._main.exigir_token(None)
        self.assertEqual(cm.exception.status_code, 401)

    def test_cabecera_incorrecta_falla(self):
        import fastapi
        with self._con_clave("secreto"):
            with self.assertRaises(fastapi.HTTPException):
                self._main.exigir_token("otro")

    def test_cabecera_correcta_pasa(self):
        with self._con_clave("secreto"):
            self._main.exigir_token("secreto")

    def test_el_401_dice_que_hay_que_hacer(self):
        """Un 401 sin explicación obliga a buscar el motivo a mano. El mensaje
        dice que se reinstale, que es lo que toca."""
        import fastapi
        with self._con_clave("secreto"):
            with self.assertRaises(fastapi.HTTPException) as cm:
                self._main.exigir_token(None)
        self.assertIn("X-Aegis-Token", cm.exception.detail)
        self.assertIn("reinstalarlo", cm.exception.detail)

    def test_todas_las_rutas_nuevas_estan_cerradas(self):
        """Que una ruta nueva se cuelgue sin token es un fallo silencioso hasta
        que alguien se da cuenta. Se comprueba ruta por ruta."""
        cerradas = {"/memoria", "/runs", "/notas", "/tareas",
                    "/autonomy", "/aprobaciones"}
        vistas = 0
        for r in app_routes():
            ruta = getattr(r, "path", "")
            if any(ruta == c or ruta.startswith(c + "/") for c in cerradas):
                vistas += 1
                # La dependencia vive en `dependant.dependencies`, y lo que se
                # compara es el `.call`: en la versión de FastAPI de aquí,
                # `Dependant` no expone `.dependency`.
                deps = [d.call for d in r.dependant.dependencies]
                self.assertIn(exigir_token, deps, f"{ruta} no exige token")
        self.assertGreater(vistas, 10, "no se encontraron las rutas nuevas")


class TestElTokenVuelveAlBridge(unittest.TestCase):
    """El círculo entero: pedir → aprobar → volver con el token → escribir.

    ## El fallo que esto previene
    La cola emitía el token y `/aprobaciones` lo devolvía, pero **`AutopilotIn`
    no tenía campo `token`**: no había por dónde meterlo. La aprobación quedaba en la
    fila como "aprobada" y el siguiente run volvía a pedir permiso para siempre.
    Es el fallo más silencioso posible: todo lo demás funcionaba, la fila decía
    "aprobada", y el paso no avanzaba.

    Se comprueba aquí con el store de verdad, no con un mock: el punto es que la
    fila y el token estén en el mismo sitio y que gastar uno marque la fila.
    """

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        self.a = autonomy._Almacen(Path(tempfile.mkdtemp()) / "a.sqlite3")
        self._antes = autonomy.ALMACEN
        autonomy.ALMACEN = self.a

    def tearDown(self) -> None:
        autonomy.ALMACEN = self._antes

    def test_el_placeholder_es_menor_que_el_de_verdad(self):
        """Sanidad: si `decide` aceptara cualquier token, el test de abajo
        pasaría sin comprobar nada."""
        p = self.a.pedir(run_id="r1", paso=1, tool="db_migrate",
                        args={"project": "compra-unida"}, motivo="m")
        token = self.a.resolver(p, "aprobar")["token"]
        d = autonomy.decide("db_migrate", {"project": "compra-unida"},
                            run_id="r1", paso=1, almacen_=self.a,
                            token="inventado")
        self.assertFalse(d.ok, "un token inventado abrió la puerta")
        d2 = autonomy.decide("db_migrate", {"project": "compra-unida"},
                             run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertTrue(d2.ok, d2.motivo)

    def test_tras_gastar_el_token_la_fila_queda_gastada(self):
        p = self.a.pedir(run_id="r1", paso=1, tool="db_migrate",
                        args={"project": "compra-unida"}, motivo="m")
        token = self.a.resolver(p, "aprobar")["token"]
        autonomy.decide("db_migrate", {"project": "compra-unida"},
                        run_id="r1", paso=1, almacen_=self.a, token=token)
        self.assertEqual(self.a.buscar(p)["estado"], "gastada")

    def test_autopilot_in_tiene_token(self):
        """El campo existe. Sin él, el círculo no cierra por mucho que el store
        esté bien: el token no tiene por dónde pasar."""
        from app.main import AutopilotIn
        body = AutopilotIn(prompt="x", token="abc")
        self.assertEqual(body.token, "abc")


class TestElTokenViajaEnElAPK(unittest.TestCase):
    """El token se compila dentro del APK, y su valor **no** sale del mensaje.

    ## Por qué esto importa más de lo que parece
    El MCP de `aegis-ops` corre como proceso aparte del bridge. Si leyera la
    clave del `settings` del bridge por referencia, en ese proceso valdría `""`,
    el APK saldría sin token, y la app **abriría, pintaría y fallaría solo en las
    secciones nuevas** con un 401. Ese es el fallo que más se parece a "la app
    va fallando" y el que más cuesta encontrar, porque la mitad funciona.

    ## Por qué el valor no se imprime
    La cola del agente es un historial: lo que sale por ella acaba en logs y en
    el prompt de runs futuros. Un secreto devuelto por una tool es un secreto en
    la historia del repositorio.
    """

    def test_mcp_ops_ve_la_clave(self):
        """El proceso del MCP lee su propia configuración, no la del bridge."""
        from app import mcp_ops
        self.assertTrue(hasattr(mcp_ops, "settings"),
                        "build_apk usaría settings sin importar y el nombre "
                        "no existiría en ese proceso")
        self.assertTrue(hasattr(mcp_ops.settings, "aegis_api_key"))

    def test_el_valor_no_aparece_en_el_mensaje_de_build(self):
        from app import mcp_ops
        if not mcp_ops.settings.aegis_api_key:
            self.skipTest("no hay clave puesta en este entorno")
        secreto = mcp_ops.settings.aegis_api_key
        # Se comprueba sobre el código que compone el comando, no sobre una
        # ejecución real: un test que compilara un APK tardaría minutos y solo
        # mediría una vez lo que esta comprobación mide siempre.
        import inspect
        fuente = inspect.getsource(mcp_ops.build_apk)
        self.assertIn("AEGIS_TOKEN", fuente)
        # El f-string es lo correcto (el valor tiene que acabar en el comando),
        # pero no puede haber un return ni un f-string con la clave suelta.
        for linea in fuente.splitlines():
            code = linea.strip()
            if code.startswith(("return ", "f\"", "\"aviso")) and secreto in linea:
                self.fail(f"la clave se devuelve en el mensaje: {code[:60]}")


class TestAdbConnectDiceLaVerdad(unittest.TestCase):
    """`adb_connect` no puede decir "ya conectado" sin mirar al teléfono.

    ## El bug que esto previene
    La versión anterior contaba dispositivos conectados y, si encontraba alguno,
    respondía "ya conectado". Como el emulador está siempre levantado —es donde
    van todas las pruebas— eso significaba que **nunca intentaba conectar el
    teléfono**: la tool informaba de algo que no había comprobado, y el
    teléfono seguía sin verse. A-016 con forma de mensaje de tool.

    ## Por qué el fallo cuela
    El mensaje era cierto sobre *algún dispositivo*. Solo que no sobre el que
    importaba. Es el mismo patrón que el guardarraíl muerto de A-028: un control
    que dice que comprueba algo que no comprueba.
    """

    def test_con_el_emulador_arriba_no_dice_ya_conectado(self):
        from app import mcp_ops
        from app import dispositivos as disp
        emulador = disp.Device(serial="emulator-5554", state="device")
        with mock.patch.object(disp, "telefono", return_value=None), \
             mock.patch.object(disp, "dispositivos", return_value=[emulador]), \
             mock.patch.object(mcp_ops, "_puertos_mdns", return_value=[]):
            salida = mcp_ops.adb_connect()
        self.assertNotIn("ya conectado", salida,
                         "dijo que el teléfono estaba conectado viendo solo el emulador")
        self.assertIn("mDNS", salida)

    def test_sin_mdns_explica_las_tres_causas(self):
        """Un "no encuentro el teléfono" sin decir por qué obliga a buscar; con
        las tres causas, la persona sabe qué mirar."""
        from app import mcp_ops
        from app import dispositivos as disp
        with mock.patch.object(disp, "telefono", return_value=None), \
             mock.patch.object(mcp_ops, "_puertos_mdns", return_value=[]):
            salida = mcp_ops.adb_connect()
        self.assertIn("pantalla", salida)
        self.assertIn("inalámbrica", salida)
        self.assertIn("misma red", salida)

    def test_el_telefono_ya_conectado_si_esta_de_verdad(self):
        from app import mcp_ops
        from app import dispositivos as disp
        tel = disp.Device(serial="adb-x._adb-tls-connect._tcp", state="device")
        with mock.patch.object(disp, "telefono", return_value=tel), \
             mock.patch.object(mcp_ops, "_adb") as adb:
            salida = mcp_ops.adb_connect()
        self.assertIn("ya está conectado", salida)
        adb.assert_not_called()

    def test_mdns_devuelve_host_y_puerto_sin_duplicados(self):
        """adb anuncia el mismo teléfono dos veces, con el contador en medio del
        serial. Sin quitarlo, se intenta dos veces el mismo puerto."""
        from app import mcp_ops
        salida = (
            "adb-SERIAL1234567-tkpktJ (2)\t_adb-tls-connect._tcp\t192.168.0.5:46119\n"
            "adb-SERIAL1234567-tkpktJ\t_adb-tls-connect._tcp\t192.168.0.5:46119\n"
        )
        proc = mock.Mock(stdout=salida, returncode=0, stderr="")
        from app import dispositivos as disp
        # La salida está simulada, así que el `adb` real no hace falta: lo que se
        # comprueba aquí es el parseo y la deduplicación, no que la máquina tenga
        # un SDK de Android instalado. Sin este parche, en una máquina sin SDK
        # `_puertos_mdns` devuelve `[]` antes de mirar la salida, y el test falla
        # por la ausencia de la herramienta en vez de por su motivo.
        with mock.patch.object(mcp_ops, "_run", return_value=proc), \
             mock.patch.object(disp, "adb_ausente", return_value=""):
            puertos = mcp_ops._puertos_mdns()
        self.assertEqual(puertos, [("192.168.0.5", "46119")])


class ArgsEfectivas(unittest.TestCase):
    """Lo que se guarda en una aprobación tiene que poder revisarse.

    ## El fallo que fijan estos tests
    Un 7B pide `build_apk` sin argumentos —medido dos veces seguidas—. La
    petición se guardaba con `args: null`: la pantalla enseñaba `build_apk` y
    nada más, sin `target`, así que no se podía saber si se publicaba para el
    emulador o para el teléfono. Y no era solo cosmetico: el ejecutor aplicaba
    los valores por defecto igual, así que aprobar concedía el permiso para una
    **otra** llamada. El token valida *la llamada*; una llamada que no se puede
    ver no se puede validar.
    """

    def _tool_build_apk(self):
        from app.mcp_ops import mcp
        return mcp._tool_manager.get_tool("build_apk")

    def test_rellena_lo_que_el_modelo_no_dijo_con_el_default_de_la_firma(self):
        from app.autopilot import _args_efectivas
        efectivas = _args_efectivas(self._tool_build_apk(), {})
        self.assertEqual(efectivas["target"], "emulador")
        self.assertIs(efectivas["release"], True)

    def test_lo_que_el_modelo_dijo_manda(self):
        from app.autopilot import _args_efectivas
        efectivas = _args_efectivas(self._tool_build_apk(), {"target": "telefono"})
        self.assertEqual(efectivas["target"], "telefono")

    def test_un_argumento_que_la_tool_no_declara_no_sobrevive_en_el_registro(self):
        # Si sobrevive, el registro hace creer que va a hacer algo que en
        # realidad se ignoraría.
        from app.autopilot import _args_efectivas
        efectivas = _args_efectivas(self._tool_build_apk(), {"destino": "lmfi.xyz"})
        self.assertNotIn("destino", efectivas)

    def test_una_tool_desconocida_no_inventa_argumentos(self):
        from app.autopilot import _args_efectivas
        self.assertEqual(_args_efectivas(None, {"target": "telefono"}), {"target": "telefono"})

    def test_lo_que_manda_el_autopilot_lo_misma_aprobacion_lo_enseña(self):
        """Extremo a extremo: la aprobación pendiente lleva los argumentos Effective.

        Es el contrato entero en un test — nada deDefaults, nada de null — porque
        las dos mitades pueden romperse por separado y seguir de acuerdo.
        """
        from app.autopilot import _args_efectivas

        # Ruta propia, siempre: `_Almacen()` sin argumentos escribe en la base
        # **real**, y un test que deja una aprobación pendiente ahí se cuela en
        # la cola de verdad. Ya pasó con este mismo fichero.
        al = autonomy._Almacen(Path(tempfile.mkdtemp()) / "autonomia.sqlite3")
        pid = al.pedir(run_id="r1", paso=1, tool="build_apk",
                       args=_args_efectivas(self._tool_build_apk(), {}),
                       motivo="compila")
        pendiente = [p for p in al.pendientes() if p["id"] == pid][0]
        self.assertEqual(json.loads(pendiente["argumentos"])["target"], "emulador")
        self.assertTrue(pid)

    def test_build_apk_es_de_nivel_3_y_se_pregunta_siempre(self):
        from app.autonomy import REQUIERE_OK, nivel_de
        self.assertIn("build_apk", REQUIERE_OK)
        self.assertEqual(nivel_de("build_apk"), "requiere_ok")
