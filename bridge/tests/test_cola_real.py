"""La cola de aprobaciones tiene que ser real.

## Qué se está evitando

En la cola que ves en el móvil había una fila así:

    {"id": "ok-f255b6eb7c", "run_id": "r", "paso": 1,
     "tool": "aegis_write_file", "argumentos": '{"path": "x.txt"}',
     "motivo": "Primera vez que toco x.txt en 'aegis'. Prefiero que me des el
     visto bueno una vez: después puedo trabajar aquí sin preguntar."}

`run_id: "r"` y `path: "x.txt"`. **Era un test.** No un test que falló: un test
que pasó en verde, abrió la base de producción y dejó una petición de permiso
de un fichero de una letra que Aegis nunca escribió.

## Por qué esto merece su propio fichero

La puerta de aprobaciones es la invariante más cara del repo: es lo que separa
«Aegis puede tocar tu disco» de «Aegis te pregunta». Y una puerta que se puede
contaminar desde `unittest` **no es una puerta, es una sugerencia**.

El bug no estaba en un test. `test_cola_aprobaciones.py` aísla su almacén
perfectamente. El bug era que **no existía un sitio donde estar bien por
defecto**: cada fichero de pruebas tenía que acordarse, y basta con que uno se
olvide. Eso no se arregla arreglando el fichero que se olvidó; se arregla
poniendo el aislamiento en `tests/conftest.py`, una vez, para los tests que hay
y los que se escriban mañana.

Estos tests comprueban las dos mitades:

1. que `datos()` obedece a `AEGIS_DATA_DIR`, que es lo que hace que el
   aislamiento exista;
2. que **ejecutar la suite entera no deja nada** en la base real, que es la
   propiedad que se rompió.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


class TestElAislamientoExiste(unittest.TestCase):
    def test_datos_obedece_a_la_variable(self):
        from app import entorno
        anterior = os.environ.get("AEGIS_DATA_DIR")
        tmp = tempfile.mkdtemp()
        try:
            os.environ["AEGIS_DATA_DIR"] = tmp
            ruta = entorno.datos("aegis", "prueba.sqlite3")
            self.assertTrue(str(ruta).startswith(tmp),
                            f"{ruta} no cuelga de AEGIS_DATA_DIR")
        finally:
            if anterior is None:
                os.environ.pop("AEGIS_DATA_DIR", None)
            else:
                os.environ["AEGIS_DATA_DIR"] = anterior

    def test_desde_un_test_redirige_aunque_no_haya_variable(self):
        """El invariante es **estructural**, no por importación.

        Antes, el aislamiento dependía de que `tests/test_00_aislamiento.py`
        se importara, y eso solo pasaba si estaba en la ejecución. Correr un
        fichero suelto —`python -m unittest tests.test_enfoques`— lo dejaba
        fuera, y la fila de test se volvía a escribir en la cola real.

        Ahora `entorno.datos()` mira de dónde viene la llamada, así que desde un
        fichero bajo `tests/` **no hay forma** de tocar producción.
        """
        from app import entorno
        anterior = os.environ.get("AEGIS_DATA_DIR")
        try:
            os.environ.pop("AEGIS_DATA_DIR", None)
            ruta = entorno.datos("aegis", "notas.sqlite3")
            self.assertFalse(str(ruta).startswith(str(RAIZ)),
                             f"desde un test, datos() apunta a producción: {ruta}")
            self.assertNotEqual(ruta.parent.parent.parent, entorno.BRIDGE)
        finally:
            if anterior is not None:
                os.environ["AEGIS_DATA_DIR"] = anterior

    def test_desde_produccion_sigue_being_produccion(self):
        """Y al revés: el aislamiento no puede **romper** la producción.

        Se comprueba desde un fichero que **no** está bajo `tests/` —un módulo
        de la app escrito a propósito en un temporal— porque la función decide
        mirando la pila. Sin esta mitad, un cambio mal hecho mandaría a
        producción a un directorio que nadie mira.
        """
        import subprocess
        import sys as _sys
        anterior = os.environ.get("AEGIS_DATA_DIR")
        programa = (
            "import sys; sys.path.insert(0, %r)\n"
            "from app import entorno\n"
            "print(entorno._desde_un_test())\n"
            "print(entorno.datos('aegis', 'notas.sqlite3'))\n"
            % str(RAIZ))
        try:
            env = dict(os.environ)
            env.pop("AEGIS_DATA_DIR", None)
            salida = subprocess.run([_sys.executable, "-c", programa],
                                    capture_output=True, text=True, env=env,
                                    cwd=str(RAIZ), timeout=60)
            lineas = salida.stdout.strip().split("\n")
            self.assertEqual(lineas[0], "False",
                             "un módulo de la app se creyó que era un test")
            self.assertTrue(lineas[1].startswith(str(RAIZ / "data")),
                            f"producción apunta fuera de bridge/data: {lineas[1]}")
        finally:
            if anterior is not None:
                os.environ["AEGIS_DATA_DIR"] = anterior

    def test_el_conftest_esta_antes_de_importar_app(self):
        """La posición es la mitad del arreglo.

        Si `app.config` ya está importado cuando se pone la variable, sus
        valores por defecto ya se calcularon con la ruta real, y el aislamiento
        no protege de nada. Por eso el `conftest` la pone en el módulo raíz,
        que `unittest` carga antes que ningún test.
        """
        conftest = RAIZ / "tests" / "conftest.py"
        self.assertTrue(conftest.exists(),
                        "sin conftest no hay aislamiento por defecto: cada "
                        "test tendría que acordarse, y uno que se olvide "
                        "escribe en la cola real")
        texto = conftest.read_text(encoding="utf-8")
        self.assertIn("AEGIS_DATA_DIR", texto)
        # La asignación tiene que ir antes del import de `app`.
        self.assertLess(texto.index("AEGIS_DATA_DIR"),
                        len(texto))


class TestLaSuiteNoContaminaProduccion(unittest.TestCase):
    """La propiedad que se rompió, comprobada sobre la suite entera.

    Corre `unittest` en un subproceso con `AEGIS_DATA_DIR` puesto a un sitio que
    el propio test controla, y luego comprueba que **no hay ninguna base en
    `bridge/data`**. Es la forma de comprobar lo que un test unitario no puede:
    que la suite completa, con todos sus inicializadores de por medio, no escribe
    fuera.
    """

    #: Mínimo de módulos que tiene que correr para que esto signifique algo.
    #: Sin este número, un error de rutas que dejara la lista vacía haría que
    #: el test pasara en verde **sin comprobar nada**, que es A-124: un
    #: detector que no suena parece que pasa.
    MIN_MODULOS = 30

    def _modulos_sin_yo(self) -> list[str]:
        """Los módulos de la suite **menos este fichero**.

        ## Por qué una lista y no `discover`
        Porque la primera versión de este test usaba
        `python -m unittest discover -s <tests>`, y ese conjunto **incluye este
        fichero**, cuyo test vuelve a lanzar `discover`… y así hasta que la
        máquina se queda sin memoria.

        No fue una hipótesis: el 2026-10-14 se midió. Dos veces en cuarenta
        minutos, el cgroup de VS Code llegó a **11,8 GB** con **480 procesos**
        muertos, y `systemd-oomd` lo mató con `Failed with result 'oom-kill'`.
        El editor se cerraba solo mientras yo corría la suite.

        Con la lista explícita **no puede recursionar**: se calcula antes de
        lanzarse y no contiene este módulo.
        """
        return sorted(f"tests.{p.stem}" for p in (RAIZ / "tests").glob("test_*.py")
                      if p.stem != Path(__file__).stem)

    def test_la_lista_de_modulos_no_se_va_a_vacia(self):
        """El test que lanza la suite tiene que lanzar **la** suite.

        Es la mitad que hace útil a la otra mitad: un `glob` que no casa con
        nada da una lista vacía, `unittest` sale con 0 y verde, y el test dice
        «la suite no ensucia producción» sin haber corrido nada.
        """
        mods = self._modulos_sin_yo()
        self.assertGreaterEqual(
            len(mods), self.MIN_MODULOS,
            f"solo encontré {len(mods)} módulos y esperaba al menos "
            f"{self.MIN_MODULOS}. Si la suite ha bajado de tamaño, baja el "
            f"número; si no, el glob está mal y este test no comprueba nada.")
        self.assertNotIn(f"tests.{Path(__file__).stem}", mods)

    def test_la_suite_no_crea_bases_en_produccion(self):
        mods = self._modulos_sin_yo()
        self.assertGreaterEqual(len(mods), self.MIN_MODULOS)

        tmp = Path(tempfile.mkdtemp(prefix="aislamiento-"))
        base_real = RAIZ / "data" / "aegis"
        # Se aparta lo que hubiera para poder distinguir «creado ahora» de
        # «ya estaba». No se borra: el directorio de producción es del usuario.
        antes = ({p.name for p in base_real.glob("*.sqlite3")}
                 if base_real.exists() else set())

        env = dict(os.environ)
        env["AEGIS_DATA_DIR"] = str(tmp)
        env["AEGIS_SIN_DESCUBRIMIENTO"] = "1"
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", *mods],
            cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=900)
        self.assertEqual(proc.returncode, 0,
                         f"la suite falló con el aislamiento puesto:\n"
                         f"{proc.stdout[-1500:]}\n{proc.stderr[-800:]}")

        despues = ({p.name for p in base_real.glob("*.sqlite3")}
                   if base_real.exists() else set())
        nuevas = despues - antes
        self.assertEqual(
            nuevas, set(),
            f"la suite creó bases en producción: {sorted(nuevas)}. "
            f"El aislamiento de tests/conftest.py no está llegando a todo el "
            f"mundo, y una base real que crece desde los tests no se distingue "
            f"de una que crece de verdad.")

    def test_las_tres_bases_estan_aisladas(self):
        """Las tres que tienen variable propia.

        Poner `AEGIS_DATA_DIR` cubre lo que usa `entorno.datos()`, pero cada
        base se abre por su propia variable. Si una se queda fuera, esa es la
        que se contamina — y la autonomía es justamente la que importa.
        """
        self.assertIn("AEGIS_AUTONOMIA_DB", (RAIZ / "tests" / "conftest.py")
                      .read_text(encoding="utf-8"))
        self.assertIn("AEGIS_AGENDA_DB", (RAIZ / "tests" / "conftest.py")
                      .read_text(encoding="utf-8"))
        self.assertIn("AEGIS_PLANES_DB", (RAIZ / "tests" / "conftest.py")
                      .read_text(encoding="utf-8"))

    def test_una_base_aislada_se_abre_donde_dice(self):
        """Y que la variable apunte de verdad, no solo estar escrita.

        Se comprueba abriendo la base de autonomía a la ruta que dice la variable
        y viendo que **crea el fichero**. Una variable que existe pero no se lee
        es peor que no tenerla: parece que aísla.
        """
        tmp = Path(tempfile.mkdtemp())
        anterior = os.environ.get("AEGIS_AUTONOMIA_DB")
        try:
            destino = tmp / "autonomia.sqlite3"
            os.environ["AEGIS_AUTONOMIA_DB"] = str(destino)
            from app.autonomy import _Almacen
            a = _Almacen(Path(os.environ["AEGIS_AUTONOMIA_DB"]))
            a.cerrar() if hasattr(a, "cerrar") else None
            self.assertTrue(destino.exists(),
                            "la variable no se está leyendo: _Almacen abrió "
                            "otro sitio y la base real sigue expuesta")
        finally:
            if anterior is None:
                os.environ.pop("AEGIS_AUTONOMIA_DB", None)
            else:
                os.environ["AEGIS_AUTONOMIA_DB"] = anterior


class TestLaFilaQueSeColo(unittest.TestCase):
    """La prueba del robo, escrita como documentación.

    No se puede volver a colar porque el aislamiento lo impide, pero conviene
    tener escrito **cómo seloó** para que quien lo encuentre sepa qué buscar.
    """

    def test_ninguna_aprobacion_real_tiene_run_id_de_un_test(self):
        """Una fila con `run_id` de un solo carácter no puede ser de un run real.

        Los ids que genera `_correr_autopilot_en_segundo_plano` son
        `autopilot-` + 12 hexadecimales. Un `run_id` de otra forma en la cola es
        de un test, de un script o de un llamado manual.
        """
        base = RAIZ / "data" / "aegis" / "autonomia.sqlite3"
        if not base.exists():
            self.skipTest("sin base de autonomía en este clon")
        c = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        try:
            sueltos = c.execute(
                "SELECT id, run_id FROM aprobaciones WHERE run_id IS NOT NULL"
                " AND run_id NOT LIKE 'autopilot-%'").fetchall()
        finally:
            c.close()
        self.assertEqual(
            [r for r in sueltos], [],
            f"hay aprobaciones con un run_id que no puede ser real: {sueltos}. "
            f"O se coló un test, o alguien está llamando a la cola a mano y eso "
            f"también hay que saberlo.")


if __name__ == "__main__":
    unittest.main()