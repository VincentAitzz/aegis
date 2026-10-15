"""Un plan: lo que Aegis está trabajando, y por qué.

## Por qué este módulo existe

El 2026-10-14 se midió cómo se piden las cosas de verdad, sobre 500 prompts
reales del usuario (4 semanas, 6 proyectos):

| patrón | % |
|---|---|
| **continuar** — `procede`, `continua`, `dale` | **19 %** |
| corregir — `no,`, `pero`, `prefiero` | 12 % |
| aprobar — `apruebo`, `confirmo` | 6 % |

Y se comprobó qué hacía Aegis con eso:

```
'procede'   -> (no casa con ningún intent)
'continua'  -> (no casa con ningún intent)
```

**El 19 % de los prompts reales no llegaba a ningún sitio.** Caía a T1, que es
el modelo sin herramientas, y el modelo no tenía con qué continuar porque
**no existía el objeto «lo que Aegis está trabajando»**. No estaba en `intents`,
ni en la cola de aprobaciones —que es por *tool*—, ni en `tareas`, que tiene
estado pero no prioridad.

Eso es lo que este módulo añade. No es «una lista de cosas que hacer»: es el
**único sitio donde vive la respuesta a «en qué está Aegis ahora»**, que es la
pregunta que un plan con prioridad necesita para encajar uno nuevo con el que ya
se está ejecutando.

## Por qué vive aquí y no en `notas.py`

Porque `tareas` no sirve, y por una razón concreta: una tarea tiene `estado` y
un `para`, y **no tiene prioridad**. La prioridad no es un campo más, es lo que
permite que un plan nuevo se mida contra el que está en curso. Añadirla a
`tareas` obligaría a que el esquema de tu agenda personal supiera de planes, y a
que `GET /tareas` empezara a devolver cosas que no son tareas.

También porque **el plan tiene una historia**: de dónde salió, si reformuló a
otro, qué evidencia sostiene que está hecho. `tareas` borra, `notas` son tuyas.
Un plan es de Aegis, y por eso tiene tabla propia y no se mezcla con tu agenda.

## La regla que no se negocia

`cerrado` **no** significa «el modelo dijo que terminó». Significa **hay un
cierre con evidencia** (ver `app/cierre.py`), y si no, el plan no se cierra.

Es la misma regla que A-016 y que `veredicto.py`, por tercera vez: el estado
sale de la traza, nunca del texto.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from . import entorno

#: Los estados, y qué significa cada uno. El orden importa: es el orden en el que
#: un plan avanza, y un plan solo puede saltar **hacia atrás** (a `bloqueado`) o
#: de vuelta a `reformulado`.
ESTADOS = (
    "en_cola",       # recibido, con su prioridad; todavía no se ha tocado
    "en_curso",      # Aegis lo está trabajando ahora
    "reformulado",   # otro plan lo cambió; se propone otro, no se aplica solo
    "bloqueado",     # no puede seguir sin algo: un OK, una respuesta
    "cerrado",       # terminado, con cierre con evidencia
)

#: Estados en los que un plan ocupa a Aegis. **Uno solo a la vez**: es lo que
#: hace que «reformular lo que se está ejecutando» tenga un sujeto.
OCUPAN = ("en_curso",)

#: Prioridad por defecto. El 50 es el punto neutro deliberado: suben y bajan
#: los dos, y un plan nuevo al 50 no desplaza al que está corriendo sin que
#: alguien lo piense.
PRIORIDAD_POR_DEFECTO = 50


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class PlanError(ValueError):
    """Lo que se pidió no tiene sentido. El mensaje dice cómo pedirlo."""


_ESQUEMA = """
CREATE TABLE IF NOT EXISTS planes (
    id TEXT PRIMARY KEY,
    objetivo TEXT NOT NULL,
    proyecto TEXT NOT NULL DEFAULT '',
    prioridad INTEGER NOT NULL DEFAULT 50,
    criterios TEXT NOT NULL DEFAULT '[]',
    estado TEXT NOT NULL DEFAULT 'en_cola',
    run_id TEXT NOT NULL DEFAULT '',
    -- La reformulación: qué plan cambia a este, y por qué. Sin esto, «Aegis
    -- reformuló» es una afirmación sin rastro, y la invariante de auditar dice
    -- que cualquier acción tiene que poder explicarse después.
    reformula_a TEXT NOT NULL DEFAULT '',
    reformula_motivo TEXT NOT NULL DEFAULT '',
    -- El enlace al cierre. `cerrado` sin esto es una palabra, no un hecho.
    cierre TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_planes_estado ON planes(estado, prioridad DESC);
CREATE INDEX IF NOT EXISTS idx_planes_proyecto ON planes(proyecto, estado);
"""


class Planes:
    """El almacén. Una instancia por proceso, como el resto."""

    def __init__(self, ruta: Optional[Path] = None) -> None:
        base = ruta or Path(os.environ.get(
            "AEGIS_PLANES_DB", str(entorno.datos("aegis", "planes.sqlite3"))))
        self.ruta = Path(base)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.ruta, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.executescript(_ESQUEMA)
        self._c.commit()

    # -- crear -------------------------------------------------------------
    def crear(self, objetivo: str, *, proyecto: str = "",
              prioridad: int = PRIORIDAD_POR_DEFECTO,
              criterios: Optional[list[str]] = None) -> dict[str, Any]:
        """Deja un plan en la cola. No lo ejecuta: solo lo anota.

        Se anota **antes** de hacer nada, no después. Es lo que permite que un
        plan exista aunque Aegis se caiga al empezar, y es lo que hace que
        «en mi ausencia» signifique algo: hay un registro de lo que se iba a
        hacer desde el segundo en que se decidió.
        """
        if not objetivo.strip():
            raise PlanError("un plan necesita un objetivo")
        if not 0 <= prioridad <= 100:
            raise PlanError(f"la prioridad va de 0 a 100; me diste {prioridad}")
        pid = f"plan-{uuid.uuid4().hex[:8]}"
        ahora = _ahora()
        self._c.execute(
            "INSERT INTO planes(id, objetivo, proyecto, prioridad, criterios,"
            " estado, creado, actualizado) VALUES(?,?,?,?,?,?,?,?)",
            (pid, objetivo.strip(), proyecto.strip(), int(prioridad),
             json.dumps(criterios or [], ensure_ascii=False), "en_cola",
             ahora, ahora))
        self._c.commit()
        return self.plan(pid) or {}

    # -- leer --------------------------------------------------------------
    def plan(self, pid: str) -> Optional[dict[str, Any]]:
        row = self._c.execute("SELECT * FROM planes WHERE id=?", (pid,)).fetchone()
        return _plan_dict(row) if row else None

    def planes(self, estado: str = "", proyecto: str = "",
               limite: int = 100) -> list[dict[str, Any]]:
        where, args = [], []
        if estado:
            if estado not in ESTADOS:
                raise PlanError(f"estado desconocido: {estado}. "
                                f"Los que hay: {', '.join(ESTADOS)}")
            where.append("estado=?")
            args.append(estado)
        if proyecto:
            where.append("proyecto=?")
            args.append(proyecto)
        sql = "SELECT * FROM planes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Orden de trabajo: lo que está corriendo va primero, luego por
        # prioridad de mayor a menor, y dentro a antigüedad. La antigüedad es el
        # desempate porque a igual prioridad, lo que espera desde antes espera
        # más —y encolar por antigüedad es lo único que no deja a nadie
        # para atrás sin que alguien lo decida.
        sql += (" ORDER BY CASE estado WHEN 'en_curso' THEN 0 ELSE 1 END,"
                " prioridad DESC, creado ASC LIMIT ?")
        args.append(limite)
        return [_plan_dict(r) for r in self._c.execute(sql, args).fetchall()]

    def en_curso(self) -> Optional[dict[str, Any]]:
        """El plan que Aegis está trabajando ahora, o `None`.

        Que sea **uno solo** no es una comodidad: es lo que permite decir «esto
        se replanifica» con un sujeto. Con dos en curso, la reformulación
        tendría que decidir a cuál de los dos, y esa decisión no tiene criterio.
        """
        row = self._c.execute(
            "SELECT * FROM planes WHERE estado='en_curso'"
            " ORDER BY actualizado DESC LIMIT 1").fetchone()
        return _plan_dict(row) if row else None

    def siguiente(self) -> Optional[dict[str, Any]]:
        """El plan con el que Aegis debería trabajar ahora: el de más prioridad
        que no está corriendo."""
        row = self._c.execute(
            "SELECT * FROM planes WHERE estado IN ('en_cola','reformulado')"
            " ORDER BY prioridad DESC, creado ASC LIMIT 1").fetchone()
        return _plan_dict(row) if row else None

    # -- mover -------------------------------------------------------------
    def tomar(self, pid: str, *, run_id: str = "") -> dict[str, Any]:
        """Pasa un plan a `en_curso`.

        **Suelta el que hubiera en curso**, y por eso es el sitio donde vive la
        regla de los dos planes: si algo ya estaba corriendo, quien llama tiene
        que saber qué se dejó. Se devuelve con `sustituido` puesto para que el
        cierre pueda contarlo como cambio drástico, que es lo que es.
        """
        p = self.plan(pid)
        if p is None:
            raise PlanError(f"no encontré el plan {pid}")
        # Idempotente: tomar el plan que ya está en curso **no** es un error,
        # es un no-op. Hace falta porque con autonomía `tomar()` se puede llamar
        # dos veces —el plan se toma al encolarse y otra vez al empezar el run—,
        # y que la segunda fuera un error convertiría un reintento normal en un
        # fallo. La comprobación va **antes** del estado, porque el plan que ya
        # está en curso tiene un estado que la comprobación de abajo rechaza.
        if p["estado"] in OCUPAN:
            return dict(p, sustituido=None)
        if p["estado"] not in ("en_cola", "reformulado"):
            raise PlanError(f"el plan {pid} está en '{p['estado']}' y no se "
                            f"puede tomar; tiene que estar en cola o reformulado")
        anterior = self.en_curso()
        ahora = _ahora()
        if anterior:
            # No se borra ni se marca hecho: **vuelve a la cola**, con la
            # prioridad que tenía. Abandonar trabajo no es cancelarlo, y la
            # diferencia se ve después en el informe.
            self._c.execute(
                "UPDATE planes SET estado='en_cola', actualizado=? WHERE id=?",
                (ahora, anterior["id"]))
        self._c.execute(
            "UPDATE planes SET estado='en_curso', run_id=?, actualizado=?"
            " WHERE id=?", (run_id, ahora, pid))
        self._c.commit()
        nuevo = self.plan(pid) or {}
        nuevo["sustituido"] = anterior["id"] if anterior else None
        nuevo["sustituido_objetivo"] = anterior["objetivo"] if anterior else ""
        return nuevo

    def bloquear(self, pid: str, motivo: str) -> dict[str, Any]:
        """Un plan se atasca y hay que decirlo.

        Un plan que no puede seguir **no se queda en `en_curso`**: ocuparía la
        plaza y el siguiente plan no empezaría nunca. Se mueve, se anota por
        qué, y el siguiente entra. Sin motivo no se bloquea: un bloqueo sin
        explicación es un plan perdido con otro nombre.
        """
        if not motivo.strip():
            raise PlanError("bloquear un plan necesita un motivo: es lo único "
                            "que va a poder leer quien lo encuentre parado")
        self._c.execute(
            "UPDATE planes SET estado='bloqueado', reformula_motivo=?,"
            " actualizado=? WHERE id=?", (motivo.strip(), _ahora(), pid))
        self._c.commit()
        return self.plan(pid) or {}

    def cerrar(self, pid: str, *, cierre: str) -> dict[str, Any]:
        """Cierra un plan. **Requiere el cierre**, y no es un detalle.

        Sin `cierre` el estado `cerrado` sería la palabra del modelo diciendo que
        acabó, que es exactamente el falso éxito de A-016 con otro nombre. Aquí
        el enlace al informe es obligatorio, de modo que `cerrado` siempre
        significa «hay cinco apartados con lo que pasó y con su evidencia».
        """
        if not cierre.strip():
            raise PlanError("cerrar un plan necesita el cierre con la evidencia. "
                            "Si no hay nada que contar, el plan no está cerrado: "
                            "está mal hecho, y eso también es un resultado")
        self._c.execute(
            "UPDATE planes SET estado='cerrado', cierre=?, actualizado=?"
            " WHERE id=?", (cierre.strip(), _ahora(), pid))
        self._c.commit()
        return self.plan(pid) or {}

    def reformular(self, pid: str, *, nuevo_objetivo: str,
                   motivo: str) -> dict[str, Any]:
        """Cambia el objetivo de un plan y **anota por qué**.

        Se usa en dos direcciones, y por eso `nuevo_objetivo` puede ser el
        mismo: reformular hacia abajo y hacia arriba. Lo que no puede ser es
        vacío, porque un plan sin objetivo no se puede revisar después.
        """
        if not nuevo_objetivo.strip():
            raise PlanError("reformular sin objetivo nuevo no es reformular")
        if not motivo.strip():
            raise PlanError("una reformulación necesita su motivo: es lo único "
                            "que distingue esto de cambiar de opinión")
        p = self.plan(pid)
        if p is None:
            raise PlanError(f"no encontré el plan {pid}")
        # Un plan que se está **ejecutando** sigue ejecutándose. Cambiarle el
        # objetivo no es pararlo: es lo que se pidió —«reformular de ser
        # necesario el plan que esta ejecutandose»—. La primera versión le
        # ponía `reformulado` a todo el mundo, y eso sacaba el plan de
        # `en_curso`, liberaba la plaza y dejaba que otro plan empezara encima:
        # reformular por petición era, de hecho, una forma de **interrumpir**.
        #
        # `reformulado` queda para lo que no estaba corriendo, que sí espera a
        # que se le tome.
        estado = p["estado"] if p["estado"] in OCUPAN else "reformulado"
        self._c.execute(
            "UPDATE planes SET objetivo=?, estado=?,"
            " reformula_motivo=?, actualizado=? WHERE id=?",
            (nuevo_objetivo.strip(), estado, motivo.strip(), _ahora(), pid))
        self._c.commit()
        return self.plan(pid) or {}

    def prioritario_sobre(self, pid: str) -> bool:
        """¿Este plan tiene más prioridad que el que está en curso?

        La comparación que decide si hay que replanificar. Un plan nuevo con la
        misma prioridad **no** desplaza al que ya está: se encola detrás. Solo
        una prioridad estrictamente mayor lo saca, y quien lo saca se queda sin
        trabajo hasta que el otro termine —que también es un coste, y por eso la
        regla es `>` y no `>=`.
        """
        actual = self.en_curso()
        if actual is None or actual["id"] == pid:
            return False
        propio = self.plan(pid)
        if propio is None:
            return False
        return int(propio["prioridad"]) > int(actual["prioridad"])


_INSTANCIA: Planes | None = None


def planes(ruta: Optional[Path] = None) -> Planes:
    """La instancia del proceso, o una explícita para tests."""
    global _INSTANCIA
    if ruta is not None:
        return Planes(ruta)
    if _INSTANCIA is None:
        _INSTANCIA = Planes()
    return _INSTANCIA


def _plan_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["criterios"] = json.loads(d.get("criterios") or "[]")
    except ValueError:
        d["criterios"] = []
    return d