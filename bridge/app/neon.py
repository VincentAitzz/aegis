"""Neon desde el Bridge: una credencial, N proyectos.

Por qué el Bridge y no cada proyecto: la topología de las bases (proyecto, rama de
desarrollo, compute) es **de Aegis**, y cada proyecto solo la consume. Duplicar la
connection string en tres `.env` es la forma segura de que una quede apuntando a
producción por accidente.

La contraseña **no se guarda en ningún archivo de Aegis**: se pide a Neon cuando
hace falta y se entrega por entorno al comando que la usa. Lo único que vive en
`bridge/.env` es `NEON_API_KEY`.

Las operaciones pasan por `psql` (ya instalado) y las migraciones son archivos
`.sql`. Sin driver nuevo: el Bridge corre en el host, donde hay TCP, así que no
necesita el driver WebSocket que obliga a los Workers.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx


log = logging.getLogger("aegis.bridge.neon")

API = "https://console.neon.tech/api/v2"
PSQL = shutil.which("psql") or "/usr/bin/psql"


class NeonError(RuntimeError):
    """Fallo hablando con la API de Neon o con la base."""


def api_key() -> str:
    key = os.environ.get("NEON_API_KEY", "")
    if not key:
        raise NeonError(
            "falta NEON_API_KEY. Va en bridge/.env (gitignored), nunca en el repo "
            "ni en un mensaje."
        )
    return key


def _api(path: str, method: str = "GET", body: Optional[dict] = None,
         params: Optional[dict[str, str]] = None) -> dict[str, Any]:
    try:
        r = httpx.request(method, f"{API}{path}", json=body, params=params,
                          headers={"Authorization": f"Bearer {api_key()}"}, timeout=30.0)
    except httpx.HTTPError as exc:  # noqa: BLE001
        raise NeonError(f"no pude hablar con Neon: {exc}") from exc
    if r.status_code >= 400:
        scoped = re.search(r'subject_project_id:"([^"]+)"', r.text)
        raise NeonError(f"{method} {path} → {r.status_code} {r.text[:200]}"
                        + (f" (proyecto: {scoped.group(1)})" if scoped else ""))
    return r.json()


def config(project: str):
    """El registro es de `app/projects.py`: aquí no hay una segunda copia."""
    from .projects import project as _project
    try:
        return _project(project)
    except ValueError as exc:
        raise NeonError(str(exc)) from exc


def connection_uri(project: str, *, pooled: bool = True) -> str:
    """URL de la rama de desarrollo de un proyecto registrado.

    Sin caché en disco, a propósito: la contraseña vive en Neon, no en un archivo
    que alguien pueda commitear.
    """
    cfg = config(project)
    pid, branch = cfg.neon_project, cfg.branch
    if not pid:
        raise NeonError(f"el registro no tiene proyecto Neon para '{project}'")
    branches = _api(f"/projects/{pid}/branches?limit=100").get("branches", [])
    br = next((b for b in branches if b["name"] == branch), None)
    if not br:
        raise NeonError(
            f"la rama '{branch}' de '{project}' no existe. Créala con "
            f"neon_branch(project='{project}') o en la consola de Neon.")
    # Los params van como dict: interpolarlos a mano mete `%20` y Neon responde 400.
    res = _api(f"/projects/{pid}/connection_uri", params={
        "branch_id": br["id"], "database_name": "neondb",
        "role_name": "neondb_owner", "pooled": str(pooled).lower(),
    })
    uri = res.get("uri")
    if not uri:
        raise NeonError(f"Neon no devolvió uri para {project}/{branch}")
    return uri


def _libpq_env(project: str) -> dict[str, str]:
    """Traduce la URL de Neon a variables libpq.

    La URL NO se pasa como argumento de psql: con argumentos, la contraseña
    aparece en `ps` para cualquier usuario de la máquina y en el log del proceso
    si el comando falla. Con variables PG* tampoco queda en la línea de comandos.
    """
    from urllib.parse import parse_qs, unquote, urlparse

    uri = urlparse(connection_uri(project))
    q = parse_qs(uri.query)
    env = {
        "PGHOST": uri.hostname or "",
        "PGPORT": str(uri.port or 5432),
        "PGDATABASE": unquote((uri.path or "/neondb").lstrip("/")),
        "PGUSER": unquote(uri.username or ""),
        "PGPASSWORD": unquote(uri.password or ""),
        "PGSSLMODE": q.get("sslmode", ["require"])[0],
        "PGCONNECT_TIMEOUT": "10",
    }
    return env


def psql(sql: str, *, project: str, timeout: int = 300) -> tuple[int, str]:
    """Ejecuta SQL contra la rama de desarrollo del proyecto.

    `ON_ERROR_STOP=1`: aborta al primer error, que es lo que hace segura una
    migración a medias.
    """
    env = dict(os.environ, **_libpq_env(project))
    env.pop("AEGIS_DB_URI", None)
    proc = subprocess.run([PSQL, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
                          capture_output=True, text=True, env=env, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def root_of(project: str) -> Path:
    from .projects import project as _project
    return _project(project).root


# ── superficie para el agente ──────────────────────────────────────────────
# Tres tools. Menos es más: un modelo de 6 GB rinde peor con muchas tools que con
# una que hace bien una cosa, y leer la base es lo que más poder concede.


def db_query(project: str, sql: str, limit_rows: int = 200) -> str:
    """Lee datos de la rama de DESARROLLO de un proyecto. Solo SELECT/WITH.

    Es la herramienta de verificación: los invariantes se comprueban contra la
    base real, no contra un documento. No muta nada, y por eso no pide
    confirmación.
    """
    cfg = config(project)
    if not cfg.can_read:
        raise NeonError(f"'{project}' no tiene lectura habilitada")
    stmt = sql.strip().rstrip(";").strip()
    if not (stmt.lower().startswith("select") or stmt.lower().startswith("with")):
        raise NeonError("db_query solo lee: la sentencia debe empezar por SELECT o WITH")
    if ";" in stmt:
        raise NeonError("una sola sentencia por llamada (sin ';')")
    code, out = psql(f"select * from ({stmt}) as _q limit {int(limit_rows)}", project=project)
    if code != 0:
        raise NeonError(f"la consulta falló: {out[:300]}")
    return out or "(0 filas)"


def db_migrate(project: str, file: Optional[str] = None) -> str:
    """Aplica las migraciones de un proyecto contra su rama de DESARROLLO.

    Con `file` aplica esa y solo esa; sin él, todas las de `migrations/` en orden
    lexicográfico, parando en la primera que falle.

    La URL sale SIEMPRE de la rama registrada en PROJECTS: quien llama no puede
    elegir proyecto de base de datos, ni rama, ni host. Y `file` se resuelve
    dentro de la raíz del proyecto y bajo `migrations/`. El error posible no es
    "aplicó a producción": es "no encontré esa migración".
    """
    cfg = config(project)
    if not cfg.can_migrate:
        raise NeonError(
            f"'{project}' no tiene migraciones habilitadas"
            + (f" — {cfg.note}" if cfg.note else "")
        )
    if cfg.strategy == "drizzle":
        root = root_of(project)
        proc = subprocess.run(["npm", "run", "db:migrate"], cwd=str(root),
                              capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            raise NeonError(f"db:migrate falló (exit={proc.returncode}): "
                            f"{(proc.stdout + proc.stderr).strip()[:400]}")
        return f"db:migrate aplicado en '{project}' (rama {cfg['branch']}, vía drizzle)"

    root = root_of(project)
    if file:
        # Guarda de ruta: dentro de la raíz, .sql, y bajo migrations/.
        target = (root / file).resolve()
        if not target.is_relative_to(root.resolve()):
            raise NeonError(f"fuera de la raíz del proyecto: {file}")
        if not target.name.endswith(".sql"):
            raise NeonError("solo archivos .sql")
        if "migrations" not in target.relative_to(root.resolve()).parts:
            raise NeonError(f"solo dentro de migrations/: {file}")
        files = [target]
    else:
        files = sorted((root / "migrations").glob("*.sql"))
    if not files:
        raise NeonError(f"no hay migraciones en {root / 'migrations'}")
    applied: list[str] = []
    for f in files:
        if not f.is_file():
            raise NeonError(f"no existe: {f}")
        env = dict(os.environ, **_libpq_env(project))
        proc = subprocess.run([PSQL, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(f)],
                              capture_output=True, text=True, env=env, timeout=900)
        if proc.returncode != 0:
            raise NeonError(
                f"migración fallida en {f.name} (exit={proc.returncode})\n"
                f"aplicadas antes: {', '.join(applied) or 'ninguna'}\n"
                f"{(proc.stdout + proc.stderr).strip()[:400]}")
        applied.append(f.name)
    return (f"aplicadas en '{project}' (rama {cfg.neon_branch}): " + ", ".join(applied))


def neon_branch(project: str, branch: Optional[str] = None) -> str:
    """Crea la rama de desarrollo si falta y dice en qué estado están las ramas."""
    cfg = config(project)
    if not cfg.can_branch:
        raise NeonError(f"'{project}' no tiene habilitado crear ramas")
    name = branch or cfg.neon_branch
    if not re.match(r"^[a-z][a-z0-9-]{0,30}$", name):
        raise NeonError(f"nombre de rama inválido: {name}")
    pid = cfg.neon_project
    branches = _api(f"/projects/{pid}/branches?limit=100").get("branches", [])
    names = [b["name"] for b in branches]
    if name in names:
        return f"'{project}': ramas = {', '.join(names)} | '{name}' ya existía"
    if not branches:
        raise NeonError("el proyecto no tiene ramas de las que clonar")
    parent = next((b for b in branches if b.get("default") or b.get("primary")), branches[0])
    _api(f"/projects/{pid}/branches", "POST", {"branch": {"name": name, "parent": parent["id"]}})
    return f"'{project}': rama '{name}' creada a partir de '{parent['name']}'"
