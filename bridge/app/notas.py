"""Tus cosas: notas, tareas y recordatorios.

## Por qué no van a la memoria del agente
`app/memory` guarda *episodios de runs*: cosas que Aegis aprendió haciendo. Eso
se inyecta al prompt del siguiente run, y solo lo que se resolvió de verdad
(A-016: tres episodios falsos bajaban el tool calling de 7/8 a 0/8).

Una nota tuya no es un episodio. Si vivieran ahí, "borrar una nota" tocaría la
memoria del modelo y "un episodio" terminaría concediéndote un permiso. Son dos
cosas con dos vidas distintas, y por eso van en dos almacenes.

## Por qué SQLite
Es lo que ya usa el grafo conceptual: sin dependencias, y una copia de seguridad
es un fichero. Las alternativas eran Postgres —que ya existe, pero obliga a una
llamada a la API de Neon por cada nota que pintas en una lista— o markdown en el
repo —legible a mano, y el móvil escribiría en el árbol de trabajo de tus
proyectos—.

## Por qué no hay notas en la base de memoria
Lo mismo de antes, dicho de otra forma: `episodic` y `graph` leen de
`data/memory/`. Este módulo escribe en `data/aegis/`. Borrar una nota no toca
nada de lo que el agente recuerda.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

#: Estados de una tarea. `hecha` no se borra: es el registro de que pasó.
ESTADOS = ("pendiente", "hecha", "descartada", "aplazada")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL DEFAULT '',
    cuerpo TEXT NOT NULL DEFAULT '',
    proyecto TEXT NOT NULL DEFAULT '',
    etiquetas TEXT NOT NULL DEFAULT '[]',
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tareas (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    notas TEXT NOT NULL DEFAULT '',
    proyecto TEXT NOT NULL DEFAULT '',
    para TEXT NOT NULL DEFAULT '',
    creada TEXT NOT NULL,
    hecha TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'pendiente'
);
CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas(estado, para);
"""

#: Qué sale de `tareas()` cuando no pides un estado. Lo hecho es historia, y una
#: lista donde todo está hecho no ayuda a decidir qué hacer ahora. Es una
#: constante con nombre y no un literal suelto: el "por defecto" de una lista es
#: una decisión de producto, y las decisiones de producto se leen.
POR_DEFECTO = ("pendiente", "aplazada")


class NotasError(ValueError):
    """Lo que se pidió no tiene sentido. El mensaje dice cómo pedirlo."""


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Agenda:
    """El almacén. Una instancia por proceso, como el resto."""

    def __init__(self, ruta: Optional[Path] = None) -> None:
        base = ruta or Path(os.environ.get(
            "AEGIS_AGENDA_DB",
            os.path.expanduser("~/Workspace/aegis/bridge/data/aegis/notas.sqlite3")))
        self.ruta = Path(base)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.ruta, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.executescript(_ESQUEMA)
        self._c.commit()

    # -- notas --------------------------------------------------------------
    def nota_crear(self, *, titulo: str = "", cuerpo: str = "",
                   proyecto: str = "",
                   etiquetas: Optional[list[str]] = None) -> dict[str, Any]:
        if not titulo.strip() and not cuerpo.strip():
            raise NotasError("una nota necesita al menos un título o un cuerpo")
        nid = f"nota-{uuid.uuid4().hex[:8]}"
        ahora = _ahora()
        self._c.execute(
            "INSERT INTO notas(id, titulo, cuerpo, proyecto, etiquetas, creado, actualizado)"
            " VALUES(?,?,?,?,?,?,?)",
            (nid, titulo.strip(), cuerpo, proyecto.strip(),
             json.dumps(etiquetas or [], ensure_ascii=False), ahora, ahora))
        self._c.commit()
        return self.nota(nid) or {}

    def nota(self, nid: str) -> Optional[dict[str, Any]]:
        row = self._c.execute("SELECT * FROM notas WHERE id=?", (nid,)).fetchone()
        return _nota_dict(row) if row else None

    def notas(self, proyecto: str = "", limite: int = 100) -> list[dict[str, Any]]:
        if proyecto:
            rows = self._c.execute(
                "SELECT * FROM notas WHERE proyecto=? ORDER BY actualizado DESC LIMIT ?",
                (proyecto, limite)).fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM notas ORDER BY actualizado DESC LIMIT ?",
                (limite,)).fetchall()
        return [_nota_dict(r) for r in rows]

    def nota_borrar(self, nid: str) -> bool:
        cur = self._c.execute("DELETE FROM notas WHERE id=?", (nid,))
        self._c.commit()
        return cur.rowcount > 0

    # -- tareas -------------------------------------------------------------
    def tarea_crear(self, *, titulo: str, notas: str = "", proyecto: str = "",
                    para: str = "") -> dict[str, Any]:
        if not titulo.strip():
            raise NotasError("una tarea necesita un título")
        tid = f"tarea-{uuid.uuid4().hex[:8]}"
        self._c.execute(
            "INSERT INTO tareas(id, titulo, notas, proyecto, para, creada, estado)"
            " VALUES(?,?,?,?,?,?,?)",
            (tid, titulo.strip(), notas, proyecto.strip(), para.strip(),
             _ahora(), "pendiente"))
        self._c.commit()
        return self.tarea(tid) or {}

    def tarea(self, tid: str) -> Optional[dict[str, Any]]:
        row = self._c.execute("SELECT * FROM tareas WHERE id=?", (tid,)).fetchone()
        return _tarea_dict(row) if row else None

    def tareas(self, estado: str = "", proyecto: str = "",
               limite: int = 100) -> list[dict[str, Any]]:
        where, args = [], []
        if estado:
            where.append("estado=?")
            args.append(estado)
        else:
            where.append(f"estado IN ({','.join('?' * len(POR_DEFECTO))})")
            args.extend(POR_DEFECTO)
        if proyecto:
            where.append("proyecto=?")
            args.append(proyecto)
        # Las que tienen fecha van primero, y por fecha: lo que ya pasó es lo
        # que hay que mirar hoy.
        sql = ("SELECT * FROM tareas WHERE " + " AND ".join(where) +
               " ORDER BY CASE WHEN para='' THEN 1 ELSE 0 END, para ASC,"
               " creada DESC LIMIT ?")
        args.append(limite)
        return [_tarea_dict(r) for r in self._c.execute(sql, args).fetchall()]

    def tarea_actualizar(self, tid: str, **campos: Any) -> dict[str, Any]:
        campos = {k: v for k, v in campos.items() if v is not None}
        if not campos:
            raise NotasError("no hay nada que actualizar")
        if "estado" in campos and campos["estado"] not in ESTADOS:
            raise NotasError(f"estado '{campos['estado']}' no existe; usa {list(ESTADOS)}")
        if campos.get("estado") == "hecha":
            campos["hecha"] = _ahora()
        sets = ", ".join(f"{k}=?" for k in campos)
        cur = self._c.execute(f"UPDATE tareas SET {sets} WHERE id=?",
                              [*campos.values(), tid])
        self._c.commit()
        if cur.rowcount == 0:
            raise NotasError(f"no hay ninguna tarea con id '{tid}'")
        return self.tarea(tid) or {}

    def tarea_borrar(self, tid: str) -> bool:
        cur = self._c.execute("DELETE FROM tareas WHERE id=?", (tid,))
        self._c.commit()
        return cur.rowcount > 0

    def vencidas(self, ahora: str = "") -> list[dict[str, Any]]:
        """Tareas con fecha, sin hacer, cuya fecha ya pasó.

        Es lo único que el planificador puede lanzar por su cuenta. Una tarea
        **sin** fecha no entra nunca: "sin fecha" quiere decir "cuando pueda", no
        "ahora". Un planificador que tratara las sin fecha como vencidas sería
        un planificador que dispara en cada pasada.
        """
        ref = ahora or _ahora()
        rows = self._c.execute(
            "SELECT * FROM tareas WHERE estado='pendiente' AND para!='' AND para<=? "
            "ORDER BY para ASC", (ref,)).fetchall()
        return [_tarea_dict(r) for r in rows]


def _nota_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["etiquetas"] = json.loads(d.get("etiquetas") or "[]")
    except ValueError:
        d["etiquetas"] = []
    return d


def _tarea_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


_AGENDA: Optional[Agenda] = None


def agenda() -> Agenda:
    global _AGENDA
    if _AGENDA is None:
        _AGENDA = Agenda()
    return _AGENDA


def init_agenda() -> Agenda:
    global _AGENDA
    _AGENDA = Agenda()
    return _AGENDA

# -- Lo que vence ---------------------------------------------------------------

def _fecha_de(para: str):
    """`AAAA-MM-DD` -> datetime al final de ese día. None si no es una fecha.

    Se compara contra el **fin** del día y no contra las 00:00 porque "para el
    martes" quiere decir "antes de que sea Wednesday", y si no, una tarea del día
    se ve vencida desde la medianoche.
    """
    import datetime as _dt
    try:
        return _dt.datetime.fromisoformat(f"{para}T23:59:59")
    except (ValueError, TypeError):
        return None


def vencen_dentro(horas: int = 24) -> list[dict[str, Any]]:
    """Tareas cuya fecha vence pronto o ya pasó, más las ya vencidas.

    Es lo que el planificador recorre para **avisar**. Lo que puede **lanzar**
    son solo las ya vencidas (`Agenda.vencidas`): una tarea que vence en tres
    días todavía no es un hecho.
    """
    import datetime as _dt
    limite = _dt.datetime.now() + _dt.timedelta(hours=horas)
    fuera: list[dict[str, Any]] = []
    for t in agenda().tareas(limite=50):
        f = _fecha_de(t.get("para") or "")
        if f is not None and f <= limite:
            fuera.append(t)
    fuera.extend(agenda().vencidas())
    # Sin duplicados: `vencidas()` puede devolver tareas que ya están en la
    # primera pasada, y recordarle dos veces lo mismo a alguien es justo el
    # ruido que hace que deje de mirar los avisos.
    vistos: set[str] = set()
    return [t for t in fuera if not (t["id"] in vistos or vistos.add(t["id"]))]
