"""El guardarraíl de las tools de base de datos.

La garantía que se prueba aquí es la del punto 2 de AGENTS.md: **quien llama no
elige base, ni rama, ni host**. Si eso se pudiera saltar, el error posible
dejaría de ser "no encontré esa migración" y pasaría a ser "aplicó a producción".
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import neon  # noqa: E402
from app.projects import PROJECTS  # noqa: E402  (fuente única)
from app.neon import NeonError  # noqa: E402


class TestDbQueryIsReadOnly(unittest.TestCase):
    def test_rejects_writes(self):
        for sql in ["update pagos set amount = 0",
                    "delete from pagos",
                    "insert into pagos (id) values ('x')",
                    "drop table pagos",
                    "truncate pagos",
                    "alter table pagos add column x int"]:
            with self.assertRaises(NeonError, msg=sql):
                neon.db_query("aegis", sql)

    def test_rejects_multiple_statements(self):
        with self.assertRaises(NeonError):
            neon.db_query("aegis", "select 1; drop table pagos")

    def test_rejects_unknown_project(self):
        with self.assertRaises(NeonError):
            neon.db_query("no-existe", "select 1")


class TestDbMigrateCannotEscape(unittest.TestCase):
    def test_project_without_permission(self):
        # compra-unida: journal de drizzle desfasado; aegis: base propia
        for proyecto in ("compra-unida", "aegis"):
            with self.assertRaises(NeonError, msg=proyecto):
                neon.db_migrate(proyecto)

    def test_file_must_be_sql_under_migrations(self):
        """La ruta se resuelve dentro del proyecto y bajo migrations/: es la
        guarda que impide aplicar un archivo de otra parte del disco."""
        with self.assertRaises(NeonError):
            neon.db_migrate("portafolio", file="../../../../etc/passwd")
        with self.assertRaises(NeonError):
            neon.db_migrate("portafolio", file="astro.config.mjs")
        with self.assertRaises(NeonError):
            neon.db_migrate("portafolio", file="src/lib/types.ts")
        with self.assertRaises(NeonError):
            neon.db_migrate("portafolio", file="package.json")


class TestNeonBranch(unittest.TestCase):
    def test_name_is_validated(self):
        for name in ["rama mala!", "'; drop --", "a" * 40, "1abc", "con espacio"]:
            with self.assertRaises(NeonError, msg=repr(name)):
                neon.neon_branch("portafolio", name)

    def test_empty_name_falls_back_to_the_registered_branch(self):
        """Vacío no es un nombre: es "la que tenga registrada el proyecto"."""
        with mock.patch.object(neon, "_api", return_value={
                "branches": [{"id": "br-x", "name": "dev", "default": True}]}) as api:
            out = neon.neon_branch("portafolio", "")
        self.assertIn("'dev' ya existía", out)
        # Listó las ramas (GET) y no creó ninguna (POST). El método va como
        # posicional cuando es el default, así que hay que mirar args y kwargs.
        metodos = [c.kwargs.get("method") or (c.args[1] if len(c.args) > 1 else "GET")
                   for c in api.call_args_list]
        self.assertEqual(metodos, ["GET"])

    def test_project_without_permission(self):
        with self.assertRaises(NeonError):
            neon.neon_branch("aegis")


class TestRegistryBoundary(unittest.TestCase):
    """La frontera declarada: qué es de Aegis y qué es de cada proyecto."""

    def test_only_portafolio_can_migrate(self):
        pueden = [a for a, c in PROJECTS.items() if c.can_migrate]
        self.assertEqual(pueden, ["portafolio"])

    def test_aegis_own_base_is_read_only(self):
        """La base de Aegis no se migra con las migraciones de un proyecto."""
        self.assertFalse(PROJECTS["aegis"].can_migrate)
        self.assertFalse(PROJECTS["aegis"].can_branch)

    def test_every_project_has_a_strategy(self):
        for alias, cfg in PROJECTS.items():
            self.assertIn(cfg.strategy, ("psql", "drizzle"), alias)

    def test_only_projects_with_a_database_declare_one(self):
        """`trazeurs` y `recepcion-persa` no tienen Neon: su id va vacío a propósito."""
        for alias, cfg in PROJECTS.items():
            if alias in ("trazeurs", "recepcion-persa"):
                self.assertEqual(cfg.neon_project, "", alias)
            else:
                self.assertTrue(cfg.neon_project, alias)

    def test_neon_ids_are_project_ids_not_endpoint_names(self):
        """Regresión de A-005: `young-waterfall-…` es el endpoint de compra-unida,
        no su proyecto. El id real se descubrió listando la organización."""
        self.assertEqual(PROJECTS["compra-unida"].neon_project, "el-proyecto-de-neon-del-cliente")


class TestLibpqEnv(unittest.TestCase):
    """La URL no puede viajar en la línea de comandos: aparece en `ps`."""

    def test_url_becomes_pg_variables(self):
        with mock.patch.object(neon, "connection_uri", return_value=(
                "postgresql://demo:p%40ssw0rd@ep-x.sa-east-1.aws.neon.tech/neondb"
                "?sslmode=require&channel_binding=require")):
            env = neon._libpq_env("aegis")
        self.assertEqual(env["PGHOST"], "ep-x.sa-east-1.aws.neon.tech")
        self.assertEqual(env["PGDATABASE"], "neondb")
        self.assertEqual(env["PGUSER"], "demo")
        self.assertEqual(env["PGPASSWORD"], "p@ssw0rd")   # percent-decoded
        self.assertEqual(env["PGSSLMODE"], "require")
        self.assertNotIn("AEGIS_DB_URI", env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
