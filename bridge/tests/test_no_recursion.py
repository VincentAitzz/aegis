"""Ningún test puede lanzar la suite que lo contiene.

## El incidente

El 2026-10-14, `tests/test_cola_real.py`tenía un test que comprobaba que la suite
no escribiera en las bases de producción. Para comprobarlo, lanzaba la suite:

```python
subprocess.run([sys.executable, "-m", "unittest", "discover",
                "-s", str(RAIZ / "tests"), "-q"], ...)
```

Ese `discover` encuentra **este directorio entero**, que incluye
`test_cola_real.py`, cuyo test lanza otro `discover`… y así hasta que la máquina
se queda sin memoria.

Lo midió el kernel, no yo:

```
22:23  app-com.microsoft.VSCode.scope: 11.8G memory peak, 11.2G swap peak
       systemd-oomd killed 480 process(es) in this unit
       Failed with result 'oom-kill'
22:46  app-com.microsoft.VSCode.scope:  7.8G memory peak,  7.3G swap peak
       systemd-oomd killed 466 process(es) in this unit
```

El editor se cerraba solo mientras yo corría la suite. Y lo que aparecía en tu
pantalla no era «un test ha fallado», sino **«El kernel de Linux ha cerrado
Visual Studio Code porque el sistema está bajo de memoria»**.

## Por qué esto merece su propio fichero de tests

Porque **el modo de fallo no es «un test falla», es «la máquina muere»**. Ningún
otro mecanismo te avisa: no hay assertion, no hay traceback, no hay nada en el
informe de la suite. Solo un proceso que se cae en el sistema.

Y porque la mitad de los ficheros del repo mencionan `discover` **en un
docstring o en un comentario**. Un `grep` daría cinco falsos positivos y nadie
lo arreglaría —o se desactivaría el guardarraíl, que es peor.

Por eso esto usa **`ast`**: solo ve **código**. Un `discover` en un comentario no
existe para el parser, que es exactamente lo que se quiere.

## Lo que se considera peligroso

Un `subprocess` (o `os.system`) cuya lista de argumentos contenga `discover` y
apunte al directorio de tests. No valen:

- `discover -s tests/test_x.py` — un solo fichero, no puede contenerse;
- `discover` sobre otro directorio — no es esta suite;
- `discover` en un docstring — no es código.

## Y la excepción, que existe y hay que decir

`tests/test_cola_real.py` **sí** lanza la suite, con una lista explícita de
módulos que excluye el suyo. Está permitido y está declarado abajo, con su
motivo. Lo que este test vigila es que esa excepción siga siendo la única y siga
siendo **estructuralmente** incapable de recursionar.
"""

import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TESTS = RAIZ / "tests"

#: El único fichero autorizado a lanzar la suite, y con qué forma.
#:
#: `test_cola_real` comprueba que la suite no contamine producción, y para eso
#: tiene que correrla. Lo hace con una **lista explícita de módulos** que
#: excluye el suyo, calculada antes de lanzarse: no puede recursionar ni aunque
#: alguien añada un `test_*.py` nuevo.
PERMITIDO = {
    "test_cola_real.py": "lanza la suite para comprobar el aislamiento; "
                         "con lista explícita de módulos que excluye el suyo",
}


class TestNingunTestLanzaLaSuite(unittest.TestCase):
    def _codigo_de(self, ruta: Path) -> ast.Module | None:
        try:
            return ast.parse(ruta.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _destinos_de_s(texto: str) -> list[str]:
        """Los valores que aparecen detrás de un `-s` en un comando.

        ## Por qué tokenizar y no un regex
        El intento con `re` falló con la forma más común de todas: la comilla
        de cierre pegada a la coma. `-s', '/ruta/tests', '-q'` es el comando
        real de la lista, y un patrón con `+?` perezoso se quedaba en el primer
        carácter del mundo. Tokenizar por espacios y quitar comillas no tiene
        ese problema porque no depende de qué venga después.

        Se acepta `-s ruta` y `-s=ruta`. No se acepta `--start-directory`: es
        de `pytest`, y `pytest` no es el runner de este repo.
        """
        limpio = texto.replace("'", " ").replace('"', " ")
        limpio = limpio.replace(",", " ").replace("=", " ")
        piezas = limpio.split()
        destinos = []
        for i, p in enumerate(piezas[:-1]):
            if p in ("-s", "s") and i + 1 < len(piezas):
                destinos.append(piezas[i + 1])
        return destinos

    def _lanza_la_suite(self, arbol: ast.Module) -> bool:
        """True si el módulo lanza `unittest discover` sobre **`tests/` entero**.

        ## Por qué se mira el valor de `-s` y no la palabra «tests»
        La primera versión buscaba cualquier argumento que contuviera `tests` o
        el nombre del repo, y daba **falso positivo** con
        `discover -s tests/test_x.py`: un solo fichero no puede contenerse a sí
        mismo, así que no es el caso peligroso. Un falso positivo en un
        guardarraíl es peor que no tenerlo, porque o se desactivan las
        excepciones a mano o se deja de mirar el aviso.

        ## Y por qué se lee el texto y no la lista de argumentos
        Porque el comando se pasa de dos formas y las dos son reales: una
        **lista** —`subprocess.run([sys.executable, …, "discover", "-s",
        "tests"])`— y un **string** con shell —`subprocess.run("python -m
        unittest discover -s tests", shell=True)`—. La primera versión solo
        miraba `nodo.args`, que en el segundo caso es **un único argumento con
        todo el comando dentro**, y se le escapaba justo la forma más
        peligrosa.
        """
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            func = nodo.func
            nombre = ""
            if isinstance(func, ast.Attribute):
                base = (ast.unparse(func.value)
                        if isinstance(func.value, (ast.Attribute, ast.Name))
                        else "")
                nombre = f"{base}.{func.attr}" if base else func.attr
            if not any(k in nombre for k in
                       ("run", "call", "check_output", "Popen", "system",
                        "popen", "check_call")):
                continue
            texto = " ".join(ast.unparse(a) for a in nodo.args)
            if "discover" not in texto:
                continue
            for destino in self._destinos_de_s(texto):
                if destino == "TESTS" or destino.endswith("/tests") \
                        or destino == "tests":
                    return True
                try:
                    if Path(destino).resolve() == TESTS.resolve():
                        return True
                except (OSError, ValueError):
                    continue
        return False

    def test_ningun_test_lanza_la_suite(self):
        """El guardarraíl, sobre todos los ficheros de `tests/`."""
        culpables: list[str] = []
        for ruta in sorted(TESTS.glob("test_*.py")):
            if ruta.name == Path(__file__).name:
                continue
            if ruta.name in PERMITIDO:
                continue
            arbol = self._codigo_de(ruta)
            if arbol is None:
                continue
            if self._lanza_la_suite(arbol):
                culpables.append(ruta.name)
        self.assertEqual(
            culpables, [],
            f"estos ficheros lanzan la suite que los contiene: {culpables}.\\n\\n"
            f"Un test que hace `discover -s tests` ejecuta el conjunto que "
            f"incluye el propio fichero, y ese fichero lanza otro `discover`: "
            f"es recursión infinita. Medido el 2026-10-14: el cgroup de VS Code "
            f"llegó a 11,8 GB con 480 procesos muertos y systemd-oomd cerró el "
            f"editor.\\n\\n"
            f"Si lo que necesitas es correr la suite, lanza una lista "
            f"explícita de módulos, o usa `bin/test`.")

    def test_la_excepcion_esta_declarada(self):
        """La lista de permitidos no puede crecer sin que se note.

        Añadir un nombre aquí es una decisión: significa «este fichero puede
        lanzar la suite y lo hace de una forma que no recursiona». Que el test
        falle si la lista tiene algo que no está en el código es lo que impide
        que se convierta en un «lo doy por bueno» silencioso.
        """
        existen = {p.name for p in TESTS.glob("test_*.py")}
        faltan = sorted(set(PERMITIDO) - existen)
        self.assertEqual(faltan, [],
                         f"la lista de permitidos nombra ficheros que ya no "
                         f"existen: {faltan}. Si se renombraron, corrígela: "
                         f"una excepción que nombra algo inexistente es una "
                         f"excepción que nadie revisa")

    def test_la_excepcion_no_puede_recursionar(self):
        """Y la excepción tiene que seguir siendo estructuralmente segura.

        Comprueba que `test_cola_real.py` calcula sus módulos de una lista que
        **no incluye el suyo**. Si alguien lo cambia a `discover` otra vez, esto
        falla antes de que la máquina se caiga.
        """
        ruta = TESTS / "test_cola_real.py"
        self.assertTrue(ruta.exists(), "el fichero autorizado no existe")
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn("_modulos_sin_yo", texto,
                      "test_cola_real ha perdido la lista explícita de "
                      "módulos. Con `discover` recursiona.")
        self.assertNotIn('"discover"', texto,
                         "test_cola_real vuelve a usar `discover`: recursiona")

    def test_no_discover_en_comentarios(self):
        """Lo que este fichero protege de sí mismo.

        Un `grep` por `discover` en `tests/` da varios documentario —este
        docstring entre ellos—. Si el guardarraíl se escribiera con `grep`
        tendría que mantener una lista de excepciones que grows con cada
        comentario nuevo, y acabaría desactivado.

        Por eso `ast`. Este test es la demostración de que funciona: dice
        `discover` cuatro veces en este mismo fichero y aun así el guardarraíl
        tiene que darlo por bueno.
        """
        arbol = self._codigo_de(TESTS / "test_cola_real.py")
        self.assertIsNotNone(arbol)
        # `test_cola_real` está permitido, así que se comprueba el otro lado:
        # que el detector NO ve lo que está en los docstrings.
        self.assertFalse(self._lanza_la_suite(arbol),
                         "el detector está leyendo los docstrings: el "
                         "guardarraíl daría falsos positivos y nadie lo "
                         "arreglaría")

    def test_detecta_un_discover_real(self):
        """El otro lado: el detector **sí** ve un `discover` de verdad.

        Un guardarraíl que no se ha probado contra lo que caza, no está
        probado. Este caso se escribe en un temporal y se pasa por el mismo
        detector.
        """
        codigo = (
            "import subprocess, sys\n"
            f"subprocess.run([sys.executable, '-m', 'unittest', 'discover',\n"
            f"                '-s', {str(TESTS)!r}, '-q'])\n")
        import ast as _ast
        arbol = _ast.parse(codigo)
        metodo = self._lanza_la_suite
        with self.subTest("debe detectarlo"):
            self.assertTrue(metodo(arbol))

        codigo_limpio = (
            "import subprocess, sys\n"
            f"subprocess.run([sys.executable, '-m', 'unittest', 'discover',\n"
            f"                '-s', {str(TESTS / 'test_x.py')!r}, '-q'])\n"
        )
        with self.subTest("un solo fichero no es la suite"):
            self.assertFalse(_ast.parse(codigo_limpio) is not None
                             and metodo(_ast.parse(codigo_limpio)))


if __name__ == "__main__":
    unittest.main()