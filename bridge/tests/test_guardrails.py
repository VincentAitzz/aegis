"""Agujeros de seguridad del guardarraíl: secretos y rutas prohibidas.

Los dos que se cerraron juntos el 2026-09-27, cuando Aegis pasó a manejar
credenciales de Neon:

  1. el escaneo no detectaba URLs de base de datos ni bearer/JWT, así que
     `DATABASE_URL=postgresql://user:clave@host` pasaba limpio;
  2. `.dev.vars` era legible y escribible por el agente, y es donde `wrangler dev`
     guarda los secrets del Worker.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path  # noqa: E402

from app.mcp_ops import _no_secrets, _safe_resolve  # noqa: E402


class TestSecretScanner(unittest.TestCase):
    """Cada caso es un secreto que ANTES pasaba limpio."""

    def test_blocks_database_urls(self):
        for linea in [
            'DATABASE_URL="postgresql://demo:Sup3rS3cr3t@ep-x.sa-east-1.aws.neon.tech/neondb"',
            "REDIS_URL=redis://:ClaveSecreta99@cache.internal:6379/0",
            "MONGO_URL=mongodb+srv://user:ClaveConSecreto123@cluster0.x.mongodb.net/db",
            "MYSQL_URL=mysql://root:SecretoTotal123@db.internal:3306/app",
        ]:
            with self.assertRaises(ValueError, msg=linea):
                _no_secrets(linea)

    def test_blocks_neon_api_key(self):
        with self.assertRaises(ValueError):
            _no_secrets("NEON_API_KEY=napi_5xK2mQ7pR8vT1wY4zA6bC3d")

    def test_blocks_bearer_and_jwt(self):
        with self.assertRaises(ValueError):
            _no_secrets("Authorization: Bearer abc.def.ghi")
        with self.assertRaises(ValueError):
            _no_secrets('t = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27u"')

    def test_blocks_api_key_even_with_the_word_example(self):
        """La regresión: el filtro de placeholders buscaba la palabra suelta y una
        key real de AWS contiene EXAMPLE en medio."""
        with self.assertRaises(ValueError):
            _no_secrets('api_key = "AKIAIOSFODNN7EXAMPLEX"')

    def test_allows_templates(self):
        """Una plantilla tiene que poder escribirse: su trabajo es existir."""
        for linea in [
            "AEGIS_API_KEY_V2=cambiar-por-una-aleatoria-de-32-bytes",
            "DATABASE_URL=postgresql://<user>:<pass>@host/neondb",
            "PORTAL_TOKEN_PEPPER=xxxxxxxxxxxxxxxxxxxx",
            "SECRET_KEY=changeme",
            "FLOW_API_KEY=tus-datos-aqui",
            'FLOW_API_KEY="tus datos aqui"',
            "SECRET_KEY=placeholder",
        ]:
            _no_secrets(linea)  # no debe lanzar

    def test_allows_ordinary_code(self):
        for linea in [
            "const color = Color(0xFF2EFFA0); brand = 0xFF2EFFA0;",
            "select count(*) from information_schema.tables where table_schema='public';",
            "# la clave se rota por nombre versionado (AEGIS_API_KEY_V3)",
            "CREATE TABLE pagos (id UUID PRIMARY KEY, amount INTEGER);",
        ]:
            _no_secrets(linea)  # no debe lanzar

    def test_never_echoes_the_secret(self):
        """El mensaje dice qué vio, nunca el valor: el veto llega a un log."""
        secreto = "postgresql://demo:Sup3rS3cr3t@ep-x.neon.tech/neondb"
        with self.assertRaises(ValueError) as ctx:
            _no_secrets(f'DATABASE_URL="{secreto}"')
        self.assertNotIn("Sup3rS3cr3t", str(ctx.exception))


class TestElFiltroNoSeComeElCodigo(unittest.TestCase):
    """El guardarraíl de secretos no puede impedir leer el código de Aegis.

    ## Lo que pasó
    Los patrones incluían `token\\s*[=:]\\s*\\S+` y `password\\s*[=:]\\s*\\S+`,
    para cazar una credencial asignada a una variable. En un fichero de texto
    funciona. En **código** no: `token: str` es una anotación de tipo y
    `token = ""` es un literal vacío, y los dos son secretos según ese patrón.

    Medido el 2026-10-04: `aegis_read_file` denegaba `app/mcp_ops.py`,
    `app/main.py`, `app/autopilot.py`, `app/autonomy.py`, `app/deploy.py` y ocho
    ficheros de `tests/`. Un guardarraíl que no deja al agente abrir el fichero
    donde vive el guardarraíl no protege: estorba. Y estorbando manda al modelo
    a otra parte — en el run de ese día, 7 pasos sin escribir nada y una petición
    de `deploy_smoke` que nadie había pedido—.
    """

    #: Ficheros que siguen denegados, y está bien: llevan fixtures que **tienen**
    #: que parecer credenciales, porque son lo que prueba que el filtro salta.
    #: Se listan uno a uno para que añadir uno nuevo sea una decisión y no un
    #: olvido.
    CON_FIXTURES = {
        "test_guardrails.py": "las URLs de BD, el bearer, el JWT y el AKIA de este test",
        "test_neon.py": "una connection string de Neon con contraseña real-forma",
        "test_autopilot.py": "un `token = sk-…` que el parser de tool-calls tiene que ver",
        "test_fichas.py": "un `API_KEY=sk-live-…` que el veto de escritura tiene que ver",
    }

    def _ficheros(self) -> list[Path]:
        raiz = Path(__file__).resolve().parent.parent
        return sorted(list((raiz / "app").glob("*.py"))
                      + list((raiz / "tests").glob("*.py"))
                      + list((raiz / "bin").glob("*.py")))

    def test_el_codigo_del_repositorio_es_legible(self):
        """El que se rompe de verdad: se aplica al contenido ENTERO.

        Con el patrón viejo, un único `token: str` en cualquier línea de un
        fichero de 1.500 líneas volvía el fichero entero ilegible. Un test por
        línea no lo habría visto nunca.
        """
        denegados = {}
        for f in self._ficheros():
            if f.name in self.CON_FIXTURES:
                continue      # los tiene otro test, y denies: son fixtures
            try:
                _no_secrets(f.read_text(encoding="utf-8"))
            except ValueError as exc:
                denegados[f.name] = str(exc)
        self.assertEqual(
            {}, denegados,
            "el escaneo de secretos vuelve a tapar el código: "
            + repr(denegados))

    def test_los_ficheros_con_fixtures_siguen_denegados(self):
        """Lo contrario del anterior: para que nadie los 'arregle' quitando el filtro."""
        for nombre, motivo in self.CON_FIXTURES.items():
            f = Path(__file__).resolve().parent / nombre
            with self.assertRaises(ValueError, msg=f"{nombre} debería seguir denegado"):
                _no_secrets(f.read_text(encoding="utf-8"))

    def test_una_credencial_asignada_sigue_saltando(self):
        """Lo que el patrón genérico tiene que seguir cazando.

        `nombre = valor` es una forma, no un secreto. Se afinó, no se quitó: si
        alguien lo borra, la protección de un `.env` o de un YAML se va con él.
        """
        for linea in [
            'password = "Xk39dmQa7ZpRt4"',           # corta: una contraseña real lo es
            'api_key = "aB3dEfGh1jKlMn0pQrSt"',
            'secret_key = "Zx91kLmQw84nRtYu"',
            'access_token = "Qq7wErTy1234UiOpAsDf"',
            'NEON_API_KEY=napi_5xK2mQ7pR8vT1wY4zA6bC3d',
            'Authorization: Bearer abc.def.ghi',
        ]:
            with self.assertRaises(ValueError, msg=f"pasó limpio: {linea}"):
                _no_secrets(linea)

    def test_el_codigo_de_python_no_es_una_credencial(self):
        """Las formas que llenaban un repo de `token` y `password`."""
        for linea in [
            "def decide(token: str, api_key: Optional[str] = None) -> None:",
            "    token = \"\"",
            "    token = uuid.uuid4().hex[:16]",
            '    headers = {"X-Aegis-Token": TOKEN}',
            '    self._c.execute("INSERT INTO aprobaciones(token=?)", (t,))',
            "    neon_api_key: str = \"\"",
            "    password: str",
            "# AEGIS_API_KEY_V3 se rota por nombre versionado",
            'api_key = "clave-de-prueba"',   # sin dígitos: es una plantilla
        ]:
            _no_secrets(linea)  # no debe lanzar


class TestDeniedPaths(unittest.TestCase):
    def test_dev_vars_is_off_limits_everywhere(self):
        for alias in ("portafolio", "aegis"):
            for nombre in (".dev.vars", ".dev.vars.local", ".dev.varsrc"):
                with self.assertRaises(ValueError, msg=f"{alias}/{nombre}"):
                    _safe_resolve(f"{alias}/{nombre}")

    def test_env_files_still_blocked(self):
        for p in ("portafolio/.env", "portafolio/.env.local", "bridge/.env"):
            with self.assertRaises(ValueError):
                _safe_resolve(p)

    def test_generated_areas_blocked(self):
        for p in ("portafolio/node_modules/x.js", "portafolio/dist/client/x.js",
                  "aegis/mobile/build/x.dart"):
            with self.assertRaises(ValueError):
                _safe_resolve(p)

    def test_source_still_writable(self):
        self.assertTrue(str(_safe_resolve("portafolio/src/lib/db.ts")).endswith("db.ts"))


class TestPythonSyntaxGuard(unittest.TestCase):
    """Hasta 2026-09-27 los `.py` no se validaban: un `def` perdido pasó como
    escritura correcta. El guardarraíl es lo único que separa "el agente lo
    escribió" de "el agente lo rompió"."""

    def test_broken_python_is_rejected(self):
        import tempfile
        from app.mcp_ops import _syntax_ok

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("from dataclasses import dataclass\n\n"
                     "def bien(x: int) -> int:\n    return x\n\n"
                     "esto_no_es_python(x: str) -> int:\n    pass\n")
            path = fh.name
        ok, detail = _syntax_ok(Path(path))
        self.assertFalse(ok)
        self.assertIn("línea", detail)
        Path(path).unlink()

    def test_valid_python_is_accepted(self):
        import tempfile
        from app.mcp_ops import _syntax_ok

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("from pathlib import Path\n\ndef raiz(p: str) -> Path:\n    return Path(p)\n")
            path = fh.name
        ok, _ = _syntax_ok(Path(path))
        self.assertTrue(ok)
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestEscriturasConcurrentes(unittest.TestCase):
    """Dos escritores sobre el mismo fichero: uno no puede pisar al otro.

    ## El fallo que esto evita
    `_write_guarded` hacia `target.write_text()` y, si la sintaxis quedaba mal,
    volvia a escribir el `before` **que ese run habia leido**. Con dos runs sobre
    el mismo fichero, la secuencia mas dano era esta:

    1. el run A lee `before = v0`;
    2. el run B lee `before = v0`;
    3. B escribe `v1` y termina con `ok`;
    4. A escribe su version y falla la comprobacion de sintaxis;
    5. A revierte escribiendo `v0`.

    El fichero acababa con la version que A queria borrar, el trabajo de B estaba
    perdido, y B habia reportado `ok`. Sin error en ninguna parte: la perdida era
    invisible hasta que alguien miraba el fichero y notaba que le faltaba algo.

    ## Lo que arregla
    Un `threading.Lock` de modulo alrededor del ciclo completo
    leer -> escribir -> comprobar -> revertir. Entre el `before` que se lee y el
    `after` que se escribe no cabe nadie, y las escrituras pasan por
    `os.replace` sobre un temporal, que es atomico.
    """

    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir,
                                                             ignore_errors=True))
        self.target = self.dir / "modulo.py"
        self.target.write_text("V0 = 0\n", encoding="utf-8")

    def test_la_escritura_es_atomica_para_quien_la_mira(self):
        """Nunca hay un fichero a medias, ni aunque se lea en medio.

        `os.replace` sobre un temporal del mismo directorio hace que un lector vea
        el contenido viejo entero o el nuevo entero. Con `write_text` a pelo, un
        lector que pase en el instante justo ve el fichero vacio o truncado.
        """
        import threading
        from app import mcp_ops

        seguir = threading.Event()
        vistos = []

        def _lector():
            while not seguir.is_set():
                try:
                    vistos.append(self.target.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    vistos.append("ILEGIBLE")

        lector = threading.Thread(target=_lector)
        lector.start()
        try:
            for i in range(80):
                mcp_ops._escritura_atomica(self.target, f"# {i}\nV = {i}\n")
        finally:
            seguir.set()
            lector.join(timeout=5)

        self.assertTrue(vistos, "el lector no llego a leer nada")

        # Lo que el lector puede ver es: el contenido original, o uno de los
        # que se escribieron. Cualquier otra cosa es un fichero a medias. Ojo con
        # la comprobacion: al principio se busco una marca en el texto y fallaba
        # con el contenido original, que es un fichero **entero**. La invariante
        # no es "no esta vacio" sino "es exactamente uno de los completos".
        original = "V0 = 0\n"
        completos = {original} | {f"# {i}\nV = {i}\n" for i in range(80)}
        a_medias = [t for t in vistos if t not in completos]
        self.assertEqual([], a_medias, f"un lector vio ficheros a medias: {a_medias[:3]}")
        self.assertEqual([], list(self.dir.glob("*.tmp")), "temporales sin limpiar")

    def test_el_lock_cubre_el_ciclo_entero_incluida_la_comprobacion(self):
        """La propiedad se comprueba directamente, en vez de provocar una carrera.

        ## Por qué no una carrera con dos hilos
        Se intentaron dos, y **pasaban con y sin lock**. Con el GIL y dos
        `mock.patch.object` sobre el mismo global, el segundo sobrescribe al
        primero y al salir restaura el valor original: `_syntax_ok` volvía a ser la
        de verdad, que devuelve True para un `.py` válido, y el test se daba por
        bueno sin haber comprobado nada.

        Un test que no puede fallar no mide nada, y uno de concurrencia que no
        puede fallar es peor que no tener, porque da sensación de cobertura (A-081).
        Lo que importa no es que dos hilos se peleen, sino que entre el `before` que
        se lee y el `after` que se escribe no cabe nadie. Eso se mira.
        """
        from app import mcp_ops

        observado = {}

        def _mira(path):
            observado["durante_el_check"] = mcp_ops._ESCRITURA.locked()
            return True, ""

        real = mcp_ops._syntax_ok
        mcp_ops._syntax_ok = _mira
        try:
            mcp_ops._write_guarded(self.target, "V0 = 1\n", "V0 = 0\n")
        finally:
            mcp_ops._syntax_ok = real

        self.assertTrue(observado.get("durante_el_check"),
                        "la comprobación de sintaxis queda FUERA del lock, que es "
                        "el hueco exacto que el segundo run necesita: escribe entre "
                        "que este comprueba, y este revierte encima.")

    def test_el_lock_se_suelta_si_algo_explota(self):
        """Un lock que no se suelta es un puente levadizo, no una puerta.

        Con el `with` dentro de la función, una excepción del formateador no puede
        dejar el sistema bloqueado para siempre: lo que se escribe es pequeño, pero
        «para siempre» en un lock de módulo es todo el sistema de ficheros.
        """
        from app import mcp_ops

        self.assertFalse(mcp_ops._ESCRITURA.locked(), "arranca cogido")
        mcp_ops._write_guarded(self.target, "V0 = 2\n", "V0 = 0\n")
        self.assertFalse(mcp_ops._ESCRITURA.locked(), "se quedó cogido tras un ok")

        def _explota(path):
            raise RuntimeError("el formateador se cayó")

        real = mcp_ops._syntax_ok
        mcp_ops._syntax_ok = _explota
        try:
            with self.assertRaises(RuntimeError):
                mcp_ops._write_guarded(self.target, "V0 = 3\n", "V0 = 2\n")
        finally:
            mcp_ops._syntax_ok = real
        self.assertFalse(mcp_ops._ESCRITURA.locked(),
                         "una excepción dejó el lock cogido para siempre")

