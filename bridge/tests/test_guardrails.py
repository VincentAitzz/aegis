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
