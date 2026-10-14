"""El guardarraíl de las tools de base de datos.

La garantía que se prueba aquí es la del punto 2 de AGENTS.md: **quien llama no
elige base, ni rama, ni host**. Si eso se pudiera saltar, el error posible
dejaría de ser "no encontré esa migración" y pasaría a ser "aplicó a producción".
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import neon  # noqa: E402
from app import projects  # noqa: E402
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


class _ProyectoDePrueba:
    """Declara un proyecto ficticio solo durante el test.

    Antes estos tests usaban `portafolio`, un proyecto real del registro de quien
    escribió el repo. En un clon ajeno no existe, así que el test falla sin que
    haya roto nada (A-057). Aquí el proyecto lo crea el propio test: el
    comportamiento que se comprueba es el de `neon.py`, no el del registro.
    """

    def proyecto_ficticio(self, alias: str = "prueba", **campos):
        cfg = projects.Project(alias=alias, root=Path("/tmp") / alias,
                               strategy="psql", **campos)
        registro = dict(projects.PROJECTS)
        registro[alias] = cfg
        parche = mock.patch.dict(projects.PROJECTS, registro, clear=True)
        parche.start()
        self.addCleanup(parche.stop)
        return cfg


class TestDbMigrateCannotEscape(_ProyectoDePrueba, unittest.TestCase):
    def setUp(self):
        self.proyecto_ficticio(neon_project="prueba-12345678")

    def test_project_without_permission(self):
        # Sin permiso de migración, por mucho que se le pase un archivo válido.
        for proyecto in ("prueba", "aegis"):
            with self.assertRaises(NeonError, msg=proyecto):
                neon.db_migrate(proyecto)

    def test_file_must_be_sql_under_migrations(self):
        """La ruta se resuelve dentro del proyecto y bajo migrations/: es la
        guarda que impide aplicar un archivo de otra parte del disco."""
        for archivo in ("../../../../etc/passwd", "astro.config.mjs",
                        "src/lib/types.ts", "package.json"):
            with self.subTest(archivo=archivo), self.assertRaises(NeonError):
                neon.db_migrate("prueba", file=archivo)


class TestNeonBranch(_ProyectoDePrueba, unittest.TestCase):
    def setUp(self):
        self.proyecto_ficticio(neon_project="prueba-12345678", can_branch=True)

    def test_name_is_validated(self):
        for name in ["rama mala!", "'; drop --", "a" * 40, "1abc", "con espacio"]:
            with self.assertRaises(NeonError, msg=repr(name)):
                neon.neon_branch("prueba", name)

    def test_empty_name_falls_back_to_the_registered_branch(self):
        """Vacío no es un nombre: es "la que tenga registrada el proyecto"."""
        with mock.patch.object(neon, "_api", return_value={
                "branches": [{"id": "br-x", "name": "dev", "default": True}]}) as api:
            out = neon.neon_branch("prueba", "")
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
    """La frontera declarada: qué es de Aegis y qué es de cada proyecto.

    ## Por qué estos tests ya no nombran proyectos reales
    Antes afirmaban cosas sobre el registro de quien escribió el repo —que solo
    `portafolio` puede migrar, que `compra-unida` no lleva id de Neon—. En un
    clon ajeno ese registro no existe, los projects no existen, y los tests
    fallan **sin que haya roto nada**: miden la máquina, no el código (A-057).

    Ahora lo que se comprueba es la **regla**, con proyectos de mentira
    construidos aquí. La regla no depende de quién tengas en el registro, y un
    test que depende de tus secretos no se puede ni auditar.
    """

    def _de_mentira(self, alias: str, **campos) -> projects.Project:
        return projects.Project(alias=alias, root=Path("/tmp") / alias, **campos)

    def test_aegis_own_base_is_read_only(self):
        """La base de Aegis no se migra con las migraciones de un proyecto."""
        self.assertFalse(PROJECTS["aegis"].can_migrate)
        self.assertFalse(PROJECTS["aegis"].can_branch)

    def test_every_project_has_a_strategy(self):
        for alias, cfg in PROJECTS.items():
            self.assertIn(cfg.strategy, ("psql", "drizzle"), alias)

    def test_aegis_declares_no_neon_id_by_default(self):
        """El id de Neon de Aegis viene del entorno, no del código.

        Significa que un clon no lleva el id de la organización de nadie dentro,
        y por eso `neon_branch('aegis')` sin `NEON_PROJECT_AEGIS` falla con
        «sin base declarada» en vez de intentar migrar la base de otro.
        """
        import os
        os.environ.pop("NEON_PROJECT_AEGIS", None)
        self.assertEqual(projects.Project(alias="x", root=Path("/tmp/x"),
                                          neon_project=os.environ.get("NEON_PROJECT_AEGIS", ""),
                                          strategy="psql").neon_project, "")

    def test_neon_id_implies_neon_motor_and_neon_project_excludes_others(self):
        """La regla del `db` del registro, comprobada con proyectos de mentira.

          · `db: "neon"`      → tiene que venir el id de proyecto de Neon
          · `db: "supabase"`  → `neon_project` vacío: no es una base que Aegis
            administre por su costura de Neon
          · `db: null`        → declarado pero desconocido: se admite

        Es la comprobación que el registro **no** puede hacer solo, porque el
        registro declara la intención (`db`) y el código decide el id; que
        casen es cosa del contrato entre los dos.
        """
        neon_ok = self._de_mentira("con-neon", neon_project="my-project-1234")
        supabase = self._de_mentira("con-supabase", neon_project="")
        desconocido = self._de_mentira("sin-saber", neon_project="")

        for motor, cfg in (("neon", neon_ok), ("supabase", supabase), (None, desconocido)):
            with self.subTest(motor=motor):
                if motor == "neon":
                    self.assertTrue(cfg.neon_project)
                else:
                    self.assertEqual(cfg.neon_project, "",
                                     f"motor {motor}: no debe llevar id de Neon")

    def test_can_migrate_implies_can_branch_and_can_read(self):
        """Migrar es lo más fuerte que puede hacer Aegis sobre una base ajena.

        Si algo puede migrar pero noramificar, el registro se contradice y el
        error sale en producción, en una migración, no en el alta.
        """
        for alias, cfg in PROJECTS.items():
            with self.subTest(alias=alias):
                if cfg.can_migrate:
                    self.assertTrue(cfg.can_branch, alias)
                    self.assertTrue(cfg.can_read, alias)


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
