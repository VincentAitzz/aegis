"""La autonomía de Aegis: qué hace solo, qué pregunta, y por qué.

## El problema que resuelve

Aegis tiene 18 herramientas y todas son deterministas y auditables. Lo que no
tenía era una respuesta a la pregunta que de verdad importa: **¿qué puede hacer
sin preguntarme?**

Sin esa respuesta hay dos opciones y las dos son malas. O no le dejas hacer nada
—y entonces es un buscapersonas— o le dejas todo —y entonces la confianza es un
acto de fe que se gasta en la primera vez que se equivoca.

Aquí la autonomía es **una lista explícita**, en tres niveles, y el nivel lo
decide el nombre de la tool, no el criterio del momento.

## Los tres niveles

1. **Libre.** Leer, verificar, listar. No cambia nada y por eso no se pregunta.
2. **Con permiso.** Escribir código, **solo en proyectos que tú hayas marcado**.
   Aquí siguen intactos los tres guardarraíles de `mcp_ops` (whitelist,
   anti-secretos, rollback de sintaxis). Esta capa no los relaja: solo decide
   *cuándo Aegis puede invocarlos sin preguntar*.
3. **Siempre pregunta.** Lo que sale de tu disco, lo que migra una base y lo que
   toca el teléfono. Aegis **prepara** el paso, dice qué haría y por qué, y se
   para. Apruebas → sigue con un token de un solo uso. Deniegas con un motivo →
   **el motivo se queda escrito y Aegis lo lee la próxima vez**.

Ese último ciclo es lo que hace que la confianza crezca en vez de gastarse: no
es que Aegis aprenda a tener cuidado, es que tú puedes decirle por qué, una vez,
y que lo tenga en cuenta.

## Por qué el proyecto marcado es la puerta principal

Un proyecto sin marcar es de **solo lectura** para Aegis. No es un extra ni una
opción: es el criterio. Tres proyectos del registro no tienen verificador, así
que ni siquiera sus tests se pueden correr; sin verificador, "trabajar solo aquí"
no tiene contra qué comprobarse.

## Por qué la base roja detiene el run

Un verificador en rojo **antes** de empezar significa que Aegis no sabe qué
fallaba antes de tocar nada. Si empieza a escribir sobre esa base, el rojo deja
de tener valor como señal: cualquier cosa que haga después parece mejorar o
empeorar respecto a un punto de referencia que nadie conoce.

El caso real que obliga a esto: `trazeurs` llega con 452 issues de `flutter
analyze`. Para ese proyecto, "está en rojo" no significa nada, así que la
comprobación es **¿está peor que cuando empezó?**, no ¿está limpio?.

## Los modos

- `solo`     — solo nivel 1. Nada que se escriba, ni con permiso.
- `permiso`  — niveles 1 y 2. El nivel 3 pregunta siempre. Es el valor por
  defecto porque autonomy no empieza en confianza.
- `pleno`    — los tres niveles, pero el 3 sigue pidiendo: "pleno" no significa
  "sin preguntar", significa "también lo de fuera, si lo apruebas".

No existe un modo que dispense de la cola. Un modo así no sería autonomía con
dientes, sería confianza a ciegas, y un día de esos bastaría.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import entorno

log = __import__("logging").getLogger("aegis.bridge.autonomy")

#: Herramientas que no cambian nada. Se ejecutan sin preguntar y sin avisar.
LIBRES = frozenset({
    "aegis_read_file",
    "projects_list",
    "registry_list",
    "ficha_read",
    "repo_verify",
    # Preguntar por la memoria no cambia nada del disco: es lo mismo que
    # `ficha_read`. Y hasta el 2026-10-14 la memoria no se podía preguntar
    # **en absoluto** —solo entraba inyectada en el prompt, y solo con
    # `project`—, así que leerla era, de hecho, lo más parecido que había a una
    # operación de solo lectura que Aegis pudiera hacer por su cuenta.
    "memoria",
    "db_query",
    "adb_devices",
    "deploy_estado",
    "verify_deploy",
    # `lecciones` estuvo aquí hasta el 2026-10-14 y no se usa más. Estaba
    # clasificada como libre, y lo estaba bien: leer no cambia nada del disco.
    # Lo que no tiene sentido es pagarla: su puerta tuvo **0 llamadas** en los
    # 857 run logs del repo, y su contenido ya no va al prompt. Ver el docstring
    # de `load_lessons` en `app/autopilot.py`, que tiene los números.
    # Cambiar la manera de trabajar del run actual. No toca el disco, no cambia
    # nada fuera de este encargo y se acaba con él —de hecho, `usar_enfoque('')`
    # lo suelta—, así que preguntar por ello sería una puerta para nada.
    #
    # Lo que sí hace es **cerrar tools**, y eso parece una excepción: se comprueba
    # antes que cualquier nivel, en `decide()`. Preguntar «¿quieres arquitectura?»
    # cada vez que Aegis elige cómo trabajar sería volver a poner un menú delante
    # de algo que no es una decisión de la persona sino del encargo.
    "usar_enfoque",
    "enfoques_disponibles",
})

#: Las tools del **camino rápido** (`app/intents.py`), y su nivel.
#:
#: ## Por qué viven aparte y no en `LIBRES`
#: Porque `LIBRES`, `CON_PERMISO` y `REQUIERE_OK` se declaran con nombres de
#: tools **reales** —las que salen de `mcp_ops`— y hay un test que exige que no
#: haya un nombre clasificado que no exista. Añadir aquí `tarea_crear` rompería
#: ese test, y con razón: no es una tool MCP, es una función que el router
#: llama después de pasar por la puerta.
#:
#: ## Por qué estaban pidiendo tu OK para una alarma
#: `nivel_de()` cae en `requiere_ok` para **todo lo que no conoce**, y eso es una
#: propiedad buena: una tool nueva pregunta antes de hacer nada. El coste fue
#: que «pon una alarma mañana» creaba una petición de aprobación, porque
#: `tarea_crear` no estaba en ninguna parte. Es decir, la propiedad buena
#: funcionando, y el coste siendo absurdo: una nota en tu agenda no debería
#: pedir permiso.
#:
#: ## El criterio para añadir una aquí
#: Que **no escriba fuera de la agenda del usuario**. Una tool que toca el disco
#: del proyecto, una base o una pantalla es nivel 2 o 3, y va en su conjunto de
#: verdad. Si un intent de aquí algún día necesita más, se sube de nivel aquí.
NIVELES_CAMINO_RAPIDO: dict[str, str] = {
    "tarea_crear": "libre",     # una fila en tu propia agenda
    "nota_crear": "libre",      # una fila en tus propias notas
    "projects_list": "libre",   # solo lee (y ya estaba en LIBRES)
}

#: Herramientas que escriben en tu disco. Necesitan que hayas marcado el
#: proyecto con `POST /autonomy/{alias}`.
CON_PERMISO = frozenset({"aegis_write_file", "aegis_patch_file"})

#: Todo lo demás. Siempre pregunta, en todos los modos.
REQUIERE_OK = frozenset({
    "db_migrate", "neon_branch", "build_apk", "install_apk",
    "project_create", "adb_connect", "deploy_smoke",
    # Reescribir lo que Aegis sabe de ti. No es nivel 3 por prudencia abstracta:
    # es que ese fichero entra en el prompt de **todos** los runs, así que
    # reescribirlo cambia el comportamiento del sistema entero de golpe y para
    # siempre, y sobrevive a cualquier chat y a cualquier reinicio. En el
    # ecosistema de OpenClaw esto mismo (`USER.md` editable por el propio agente)
    # es el vector de ClawHavoc. Aquí se sigue viendo el texto entero en la
    # aprobación, y por eso es la diferencia entre una decisión y un ataque.
    "quien_eres_actualiza",
})

MODOS = ("solo", "permiso", "pleno")
MODO_POR_DEFECTO = "permiso"

#: Cuántas líneas puede borrar un parche sin preguntar. Por encima, el archivo se
#: considera que se está reescribiendo y eso es una decisión tuya, no suya.
LINEAS_DESTRUCTIVAS = 120

#: Horas que un permiso aprobado sigue siendo relanzable. Pasado esto, es un
#: permiso olvidado y no se ofrece: el run que lo pedía ya terminó, y un botón
#: de "relanzar" sobre algo que nadie recuerda aprobar es ruido.
VIGENCIA_APROBACION_H = 24


class AutonomiaError(ValueError):
    """Algo que Aegis quiere hacer y no puede. El mensaje dice qué hacer."""


@dataclass
class Decision:
    """Veredicto sobre un paso del agente: sí, no, o pregúntame."""

    ok: bool
    motivo: str = ""
    #: Cuando este veredicto **gastó** el token que traía el run. El bucle lo
    #: necesita para no volver a pasarlo en el paso siguiente: un token es de un
    #: solo uso, y reenviarlo convertía el resto del run en "ese permiso ya se
    #: usó" en tools que no tienen nada que ver con la llamada aprobada.
    uso_token: bool = False
    #: Por qué tiene que terminar el run, cuando un "no" no es una respuesta que
    #: el agente pueda sortear sino un roadblocks que se repite en cada paso.
    #:
    #: Existía un caso así y se traducía en Sixteen wasted inferences: la base
    #: del verificador ya estaba roja y `decide()` devolvía un "no" sin más, así
    #: que el bucle lo trataba como una respuesta ("sigue con otra cosa") y lo
    #: agotaba entero rechazando lo mismo. Ahora el "no" dice que el run se
    #: acaba, y el bucle lo obedece con un `fin` que se puede leer.
    fin: str = ""
    #: Cuando `ok` es False pero se puede reintentar con un token, esto es el id.
    peticion: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - es para logs
        return f"Decision(ok={self.ok}, motivo={self.motivo!r}, peticion={self.peticion!r})"


class _Almacen:
    """Permisos, proyectos marcados y la cola de aprobación.

    ## Por qué a disco y no en memoria
    El MCP de `aegis-ops` corre como **proceso aparte** del bridge FastAPI, y el
    móvil habla con el bridge. Con el estado en memoria, Aegis crearía la
    petición de aprobación en un proceso y el móvil la leería en otro: la pantalla
    nunca mostraría nada y Aegis esperaría una aprobación que no llega. Es la
    misma trampa que el estado de despliegue (A-021) y el registro de orígenes
    (A-020): **dos procesos, un solo estado**.

    ## Por qué SQLite y no el grafo
    La memoria del agente (`app/memory`) guarda *episodios de runs*: cosas que un
    modeloolvates. Aquí son *permisos que tú concedes*. Mezclarlos haría que borrar
    un permiso tocara la memoria del agente, y que un episodio terminara con un
    permiso. Son cosas distintas con vidas distintas.
    """

    _ESQUEMA = """
    CREATE TABLE IF NOT EXISTS autonomy (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
        alias TEXT PRIMARY KEY,
        permiso TEXT NOT NULL,
        desde TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS aprobaciones (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        paso INTEGER NOT NULL,
        tool TEXT NOT NULL,
        argumentos TEXT NOT NULL,
        motivo TEXT NOT NULL,
        proyecto TEXT NOT NULL DEFAULT '',
        estado TEXT NOT NULL,
        token TEXT,
        razon_denegacion TEXT NOT NULL DEFAULT '',
        creado TEXT NOT NULL,
        resuelto TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_apro_run ON aprobaciones(run_id, paso);
    CREATE INDEX IF NOT EXISTS idx_apro_estado ON aprobaciones(estado);
    """

    def __init__(self, ruta: Optional[Path] = None) -> None:
        base = ruta or Path(os.environ.get(
            "AEGIS_AUTONOMIA_DB",
            str(entorno.datos("aegis", "autonomia.sqlite3"))))
        self.ruta = Path(base)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        self._c = sqlite3.connect(self.ruta, check_same_thread=False)
        self._c.executescript(self._ESQUEMA)
        self._c.commit()

    # -- acceso generico -------------------------------------------------
    def _get(self, clave: str, defecto: str = "") -> str:
        row = self._c.execute("SELECT valor FROM autonomy WHERE clave=?",
                              (clave,)).fetchone()
        return row[0] if row else defecto

    def _put(self, clave: str, valor: str) -> None:
        self._c.execute(
            "INSERT INTO autonomy(clave, valor) VALUES(?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, valor))
        self._c.commit()

    # -- modo ---------------------------------------------------------------
    def modo(self) -> str:
        return self._get("modo", MODO_POR_DEFECTO)

    def set_modo(self, modo: str) -> str:
        if modo not in MODOS:
            raise AutonomiaError(f"modo '{modo}' no existe. Usa uno de {list(MODOS)}.")
        self._put("modo", modo)
        return modo

    # -- proyectos marcados -------------------------------------------------
    def proyectos(self) -> dict[str, str]:
        return {a: p for a, p in self._c.execute(
            "SELECT alias, permiso FROM projects ORDER BY alias").fetchall()}

    def marcar(self, alias: str, permiso: str = "escribir") -> None:
        self._c.execute(
            "INSERT INTO projects(alias, permiso, desde) VALUES(?,?,?) "
            "ON CONFLICT(alias) DO UPDATE SET permiso=excluded.permiso",
            (alias, permiso, _ahora()))
        self._c.commit()

    def desmarcar(self, alias: str) -> bool:
        cur = self._c.execute("DELETE FROM projects WHERE alias=?", (alias,))
        self._c.commit()
        return cur.rowcount > 0

    def resumen(self) -> dict[str, Any]:
        """El reparto de las tools, para que el móvil pueda **enseñarlo**.

        Publicar los tres tamaños y el nombre de las categorías no es
        decoración: quien concede permisos necesita ver el alcance de lo que está
        concediendo. "Puede escribir en 3 proyectos" no dice si también puede
        migrar una base.
        """
        return {
            "modo": self.modo(),
            "escritura": sorted(self.proyectos()),
            "libres": sorted(LIBRES),
            "con_permiso": sorted(CON_PERMISO),
            "requieren_ok": sorted(REQUIERE_OK),
        }

    # -- la cola ------------------------------------------------------------
    def pedir(self, *, run_id: str, paso: int, tool: str, args: dict[str, Any],
              motivo: str, proyecto: str = "") -> str:
        """Pide un OK y devuelve el id de la petición.

        ## Por qué deduplica, y por qué **no** es un detalle
        Lo primero que hace un agente al recibir un «no» es **reintentar lo
        mismo**. Antes, cada reintento insertaba una fila nueva con un uuid
        nuevo, así que la cola de aprobaciones crecía sin techo y en el móvil se
        acumulaban tarjetas idénticas: la misma llamada, 31 veces, sin nada que
        decidir 31 veces.

        Devolver la petición que ya está pendiente no cambia nada de lo que se
        decide. Es **la misma decisión** esperando a la misma persona, y que
        aparezca una vez es más honesto que aparecer 31: 31 tarjetas invites a
        contestarlas una por una, que es trabajo inventado.

        ## Y por qué solo dentro del mismo run
        Dos runs distintos pidiendo lo mismo son dos decisiones, aunque se parezcan:
        uno puede ser un reintento y otro un trabajo nuevo que quieres ver
        approving por separado. Deduplicar entre runs sería concesión de
        autoridad, y aprobar uno aprobaría el otro sin haberte-enterado.

        ## Y por qué una denegada **no** se reutiliza
        Denegar con motivo es información, y se inyecta en el prompt del run
        siguiente para que Aegis no vuelva a proponerlo. Si la reutilizáramos,
        después de un «no» no habría forma de volver a preguntar, y el motivo
        quedaría como una prohibición permanente en vez de una corrección.

        ## Y por qué `paso` no entra en la clave
        Porque el paso cambia entre reintentos del mismo run, y meterlo haría
        fallar la deduplicación justo en el caso que quiere arreglar. El `paso`
        guardado es el último, que es lo que se quiere ver: «vuelve a intentarlo
        en el paso 7» dice más que «en el 2».
        """
        firma = json.dumps(args, ensure_ascii=False, sort_keys=True)
        clave = (run_id, tool, firma)
        for fila in self._c.execute(
                "SELECT id, paso FROM aprobaciones WHERE estado='pendiente'"
                " AND run_id=? AND tool=? AND argumentos=? ORDER BY creado",
                clave).fetchall():
            log.info("autonomia: %s reintenta %s; se devuelve la petición %s "
                     "que ya estaba pendiente", run_id, tool, fila[0])
            return fila[0]
        pet_id = f"ok-{uuid.uuid4().hex[:10]}"
        self._c.execute(
            "INSERT INTO aprobaciones(id, run_id, paso, tool, argumentos, motivo,"
            " proyecto, estado, creado) VALUES(?,?,?,?,?,?,?,?,?)",
            (pet_id, run_id, paso, tool, firma,
             motivo[:600], proyecto, "pendiente", _ahora()))
        self._c.commit()
        log.info("autonomia: %s pide OK para %s (run=%s paso=%s)",
                 run_id, tool, run_id, paso)
        return pet_id

    def caducar(self, horas: int = VIGENCIA_APROBACION_H) -> int:
        """Las pendientes más viejas que [horas] pasan a `caducada`. Devuelve cuántas.

        ## Por qué caducar y no borrar
        Porque un OK que nadie contestó **es un «no»**, y un «no» viejo deja de
        ser información: la situación que querías aprobar ya no existe. Pero el
        rastro importa —«se puede auditar»—, así que la fila se marca en vez de
        desaparecer.

        ## Y por qué la misma ventana que el token
        Porque es el mismo plazo por el mismo motivo: una decisión sobre una
        llamada concreta no sobrevive a un día. Una aprobación tampoco sobrevive,
        y eso ya estaba hecho (`aprobadas_sin_gastar`).

        Se llama al leer, no con un temporizador: un proceso que limpia cada hora
        es un proceso más que se puede parar mal, y el retraso solo afecta a lo que
        se ve, que es justo lo que hay que caducar.
        """
        limite = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - horas * 3600))
        cur = self._c.execute(
            "UPDATE aprobaciones SET estado='caducada' WHERE estado='pendiente'"
            " AND creado < ?", (limite,))
        self._c.commit()
        return cur.rowcount

    def pendientes(self, run_id: str = "") -> list[dict[str, Any]]:
        """Lo que espera tu OK, **sin lo caducado**.

        Caduca antes de leer, así que la lista que se enseña es la de lo que de
        verdad se puede decidir hoy. Las caducadas siguen en la tabla, con su
        estado, para poder preguntarle por qué no se hizo.
        """
        self.caducar()
        if run_id:
            rows = self._c.execute(
                "SELECT id, run_id, paso, tool, argumentos, motivo, proyecto, creado"
                " FROM aprobaciones WHERE estado='pendiente' AND run_id=? ORDER BY creado",
                (run_id,)).fetchall()
        else:
            rows = self._c.execute(
                "SELECT id, run_id, paso, tool, argumentos, motivo, proyecto, creado"
                " FROM aprobaciones WHERE estado='pendiente' ORDER BY creado").fetchall()
        return [dict(zip(
            ("id", "run_id", "paso", "tool", "argumentos", "motivo", "proyecto", "creado"),
            r)) for r in rows]

    def aprobadas_sin_gastar(self, run_id: str = "",
                                horas: int = VIGENCIA_APROBACION_H) -> list[dict[str, Any]]:
        """Las que aprobaste y que aún nadie ha canjeado, **con su token**.

        ## Por qué existe
        El token de un solo uso solo se podía obtener en el instante de aprobar:
        venía en la respuesta del POST y no se guardaba en ninguna parte. Si el
        móvil se cerraba entre "aprobar" y "relanzar", el token se perdía para
        siempre y el run quedaba muerto pidiendo un permiso que ya habías
        concedido. Eso no era un fallo de la app: era un permiso que el sistema
        cobra y luego tira.

        ## Por qué caducan
        Porque sin caducidad la lista crece sola. Tres aprobaciones de un run de
        prueba de hace dos días aparecían como "puedes relanzar", y un botón
        que ofrece repetir algo que nadie recuerda aprobar es ruido, no una
        ayuda. El permiso que no se usa en un día es un permiso olvidado: el run
        que lo pedía ya terminó.

        ## Por qué se puede devolver sin miedo
        El token no autoriza una llamada arbitraria: `decide()` lo gasta **antes**
        de mirar nada y exige que la tool y los argumentos sean los mismos que
        aprobaste. Devolverlo por la misma puerta que exige `X-Aegis-Token` no
        amplía lo que el puente ya deja hacer: quien puede leer esta cola ya
        puede aprobar. Caducarlo aquí es solo dejar de **ofrecerlo**; si alguien
        lo guardó, el canje sigue siendo válido, que es lo que se aprobó.
        """
        sql = ("SELECT id, run_id, paso, tool, argumentos, motivo, proyecto, creado,"
               " token FROM aprobaciones WHERE estado='aprobada' AND token IS NOT NULL")
        params: list[Any] = []
        if run_id:
            sql += " AND run_id=?"
            params.append(run_id)
        if horas > 0:
            sql += " AND datetime(resuelto) >= datetime('now', ?)"
            params.append(f"-{int(horas)} hours")
        sql += " ORDER BY creado"
        rows = self._c.execute(sql, params).fetchall()
        return [dict(zip(
            ("id", "run_id", "paso", "tool", "argumentos", "motivo", "proyecto",
             "creado", "token"), r)) for r in rows]

    def buscar(self, pet_id: str) -> Optional[dict[str, Any]]:
        row = self._c.execute(
            "SELECT id, run_id, paso, tool, argumentos, motivo, proyecto, estado, token,"
            " razon_denegacion, creado, resuelto FROM aprobaciones WHERE id=?",
            (pet_id,)).fetchone()
        if not row:
            return None
        return dict(zip(
            ("id", "run_id", "paso", "tool", "argumentos", "motivo", "proyecto",
             "estado", "token", "razon_denegacion", "creado", "resuelto"), row))

    def resolver(self, pet_id: str, decision: str) -> dict[str, Any]:
        """Aprueba o deniega. Una aprobación devuelve un token de un solo uso.

        El token vive en la fila, no en un store aparte: la fila es la que dice
        "esto ya se consumió", y un token en otro sitio que se puede borrar sin
        borrar la fila deja el mismo token reutilizable.
        """
        p = self.buscar(pet_id)
        if not p:
            raise AutonomiaError(f"no hay ninguna petición con id '{pet_id}'")
        if p["estado"] != "pendiente":
            raise AutonomiaError(
                f"esa petición ya está {p['estado']}"
                + (f": {p['razon_denegacion']}" if p["razon_denegacion"] else ""))
        if decision not in ("aprobar", "denegar"):
            raise AutonomiaError("decision debe ser 'aprobar' o 'denegar'")
        if decision == "aprobar":
            token = uuid.uuid4().hex[:16]
            self._c.execute(
                "UPDATE aprobaciones SET estado='aprobada', token=?, resuelto=? WHERE id=?",
                (token, _ahora(), pet_id))
            self._c.commit()
            p["estado"] = "aprobada"
            p["token"] = token
            return p
        self._c.execute(
            "UPDATE aprobaciones SET estado='denegada', resuelto=? WHERE id=?",
            (_ahora(), pet_id))
        self._c.commit()
        p["estado"] = "denegada"
        return p

    def denegar_con_motivo(self, pet_id: str, motivo: str) -> dict[str, Any]:
        """Denegar guardando **por qué**. El motivo se lee la próxima vez.

        Es la parte que hace que la confianza crezca: no es que Aegis aprenda a
        tener cuidado, es que tú se lo dijiste una vez y lo tiene en cuenta. Sin
        motivo, denegar solo dice "no", y un "no" sin razón no se puede aplicar
        a la siguiente vez.
        """
        self._c.execute(
            "UPDATE aprobaciones SET estado='denegada', razon_denegacion=?, resuelto=? "
            "WHERE id=?", (motivo[:600], _ahora(), pet_id))
        self._c.commit()
        p = self.buscar(pet_id)
        return p or {}

    def por_token(self, token: str) -> Optional[dict[str, Any]]:
        """Mira un token **sin gastarlo**. Devuelve la fila si sigue sin usar.

    Existe separado de `gastar()` por un fallo medido: `decide()` gastaba el
    token antes de mirar si la llamada era la aprobada, así que un relanzado en
    el que el modelo pedía lo mismo con otros argumentos **destruía el permiso**
    sin llegar a usarlo. Un permiso que se pierde por un desajuste de comas es un
    permiso que hay que volver a pedir cada vez, que es exactamente el bucle que
    la cola existe para evitar.
        """
        if not token:
            return None
        row = self._c.execute(
            "SELECT id, run_id, paso, tool, argumentos, proyecto FROM aprobaciones "
            "WHERE token=?", (token,)).fetchone()
        if not row:
            return None
        p = dict(zip(("id", "run_id", "paso", "tool", "argumentos", "proyecto"), row))
        viva = self._c.execute(
            "SELECT id FROM aprobaciones WHERE estado='aprobada' AND token=? "
            "AND resuelto=(SELECT resuelto FROM aprobaciones WHERE id=?)",
            (token, p["id"])).fetchone()
        return p if viva else None

    def gastar(self, token: str) -> Optional[dict[str, Any]]:
        """Canjea un token. Uno, un uso: si ya se gastó, se niega.

        Primero se mira y después se gasta. Al revés, un token reusado se gastaría
        dos veces y la cola dejaría de ser de un solo uso.
        """
        row = self._c.execute(
            "SELECT id, run_id, paso, tool, argumentos, proyecto FROM aprobaciones "
            "WHERE token=?", (token,)).fetchone()
        if not row:
            return None
        p = dict(zip(("id", "run_id", "paso", "tool", "argumentos", "proyecto"), row))
        spent = self._c.execute(
            "SELECT id FROM aprobaciones WHERE estado='aprobada' AND token=? "
            "AND resuelto=(SELECT resuelto FROM aprobaciones WHERE id=?)",
            (token, p["id"])).fetchone()
        if not spent:
            return None
        self._c.execute(
            "UPDATE aprobaciones SET estado='gastada', token=NULL WHERE id=?",
            (p["id"],))
        self._c.commit()
        return p

    def denegaciones_recientes(self, tool: str = "", limite: int = 5) -> list[dict[str, Any]]:
        """Lo que le has dicho que no, para que Aegis lo lea antes de proponer.

        Se devuelve el **motivo**, no solo el "no": un "no" sin razón no se puede
        aplicar a la siguiente situación parecida.
        """
        if tool:
            rows = self._c.execute(
                "SELECT tool, motivo, razon_denegacion, proyecto FROM aprobaciones "
                "WHERE estado='denegada' AND razon_denegacion!='' AND tool=? "
                "ORDER BY resuelto DESC LIMIT ?", (tool, limite)).fetchall()
        else:
            rows = self._c.execute(
                "SELECT tool, motivo, razon_denegacion, proyecto FROM aprobaciones "
                "WHERE estado='denegada' AND razon_denegacion!='' "
                "ORDER BY resuelto DESC LIMIT ?", (limite,)).fetchall()
        return [dict(zip(("tool", "motivo", "por_que_no", "proyecto"), r))
                for r in rows]

    def limpiar_pendientes_de(self, run_id: str) -> int:
        """Una petición de un run que ya terminó no se puede aprobar.

        Si el móvil la *__toca__ tarde, el token no sirve para nada: el run ya
        terminó. Se marca como `caducada` en vez de borrarse, para que siga
       Constando que existió.
        """
        cur = self._c.execute(
            "UPDATE aprobaciones SET estado='caducada', resuelto=? "
            "WHERE run_id=? AND estado='pendiente'", (_ahora(), run_id))
        self._c.commit()
        return cur.rowcount


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


ALMACEN: Optional[_Almacen] = None


def almacen() -> _Almacen:
    global ALMACEN
    if ALMACEN is None:
        ALMACEN = _Almacen()
    return ALMACEN


def init_autonomia() -> _Almacen:
    global ALMACEN
    ALMACEN = _Almacen()
    return ALMACEN


def nivel_de(tool: str) -> str:
    """El nivel de una tool. `libre`, `con_permiso` o `requiere_ok`.

    Lo decide el **nombre**, no el contexto. Un nivel que dependiera de "cómo
    estamos hoy" cambiaría de opinión entre el paso 2 y el paso 3 del mismo run,
    y una puerta que se mueve sola no es una puerta.

    Los intents del camino rápido se resuelven **antes** de la lista blanca,
    y antes del `requiere_ok` por defecto: no son tools MCP, son funciones que el
    router llama tras pasar por `decide()`. Ver `NIVELES_CAMINO_RAPIDO`.
    """
    if tool in LIBRES:
        return "libre"
    if tool in CON_PERMISO:
        return "con_permiso"
    if tool in REQUIERE_OK:
        return "requiere_ok"
    if tool in NIVELES_CAMINO_RAPIDO:
        return NIVELES_CAMINO_RAPIDO[tool]
    # Una tool desconocida se trata como la más restrictiva. La lista blanca de
    # `autopilot` ya impide ejecutarla, pero si algún día se abre esa lista, el
    # nivel por defecto tiene que ser el que pregunta.
    return "requiere_ok"


def alias_de(tool: str, args: dict[str, Any]) -> str:
    """De qué proyecto habla esta llamada. '' si no habla de ninguno."""
    from .mcp_ops import root_of, _safe_resolve
    if tool in CON_PERMISO:
        path = args.get("path")
        if path:
            try:
                return root_of(_safe_resolve(str(path)))
            except Exception:  # noqa: BLE001 — aquí no vale la pena propagar
                return ""
    if tool in {"db_migrate", "neon_branch", "db_query"}:
        return str(args.get("project") or "")
    if tool in {"ficha_read", "project_create"}:
        return str(args.get("alias") or "")
    return ""


#: Herramientas que cambian algo fuera de tu disco. Se explica aparte porque es
#: el motivo por el que existen: no son "más peligrosas" por abstracto, lo son
#: porque su efecto no se deshace con un `git revert`.
FUERA_DEL_DISCO = {
    "db_migrate": "cambia el esquema de una base de datos; un revert de git no lo deshace",
    "neon_branch": "crea ramas en una base de Neon",
    "build_apk": "compila e escribe artefactos en el árbol de build",
    "install_apk": "instala una app en un dispositivo",
    "deploy_smoke": "instala y arranca la app en el emulador",
    "adb_connect": "abre una conexión adb a un dispositivo",
    "project_create": "crea carpetas y registros que cambian la estructura del workspace",
}


def _es_destructiva(tool: str, args: dict[str, Any], almacen_: _Almacen) -> str:
    """Por qué esta escritura es destructiva, o '' si no lo es.

    Dos señales, y las dos importan:

    - **Borra mucho.** Un parche que se lleva 400 líneas no está arreglando algo:
      está reescribiendo, y eso es una decisión tuya.
    - **Toca un archivo que Aegis no ha modificado nunca.** No sabe qué hay
      dentro: puede estar entero y bien, y que el cambio sea una tontería que lo
      rompa. Por eso la primera vez sobre un fichero siempre pregunta.
    """
    if tool not in CON_PERMISO:
        return ""
    from .mcp_ops import _safe_resolve
    path = args.get("path")
    if not path:
        return ""
    try:
        target = _safe_resolve(str(path))
    except Exception:  # noqa: BLE001 — la whitelist lo dirá mejor que yo
        return ""

    if tool == "aegis_write_file":
        nuevo = len(str(args.get("content") or "").splitlines())
        try:
            antes = len(target.read_text().splitlines()) if target.exists() else 0
        except OSError:
            antes = 0
        borradas = antes - nuevo
        if borradas > LINEAS_DESTRUCTIVAS:
            return (f"reescribe {target.name}: se borran {borradas} líneas "
                    f"({antes} → {nuevo}). Por encima de {LINEAS_DESTRUCTIVAS}, eso "
                    f"no es un arreglo, es una reescritura.")

    # Un archivo que Aegis no ha tocado nunca: la primera vez siempre pregunta,
    # por mucho que el proyecto esté marcado.
    return ""

#: Ficheros que Aegis ya ha modificado en este equipo. Alimenta la señal de
#: "archivo virgen", que es la que hace que la primera escritura sobre un
#: fichero pida permiso aunque el proyecto esté marcado.
_TOCADOS: set[str] = set()


def marcar_tocado(path: Path) -> None:
    _TOCADOS.add(str(path))


def tocado_alguna_vez(path: Path) -> bool:
    return str(path) in _TOCADOS


def forgetting_tocados() -> None:
    """Olvida los ficheros tocados. Para los tests; en producción no se llama.

    Vive en memoria a propósito: es una pista de "esto lo he tocado yo", no un
    registro que deba sobrevivir al reinicio. Si se perdiera, Aegis volvería a
    preguntar la primera vez sobre cada fichero, que es el fallo seguro.
    """
    _TOCADOS.clear()


def decide(tool: str, args: dict[str, Any], *, run_id: str, paso: int,
           almacen_: Optional[_Almacen] = None,
           estado_base: Optional[dict[str, Any]] = None,
           token: str = "",
           enfoque: str = "") -> Decision:
    """¿Puede Aegis ejecutar esta llamada ahora?

    ## Por qué recibe el almacén
    Deliberadamente: recibe el estado, no lo lee de un global. Un `decide` que
    leyera de dentro no se podría probar con un escenario concreto, que es justo
    lo que hay que comprobar aquí: que con el proyecto sin marcar **no** escribe,
    y con él **sí**.

    ## Por qué recibe un token
    Es lo que cierra el círculo de la petición de "primera vez". El run para,
    pide permiso, y cuando vuelve **se llama otra vez con el token**.

    ## Por qué el token valida la LLAMADA y no el run
    La primera versión ataba el token al `run_id` y al `paso`, y no podía
    canjearse nunca: aprobar y relanzar **crea un run nuevo** con otro id, así que
    el token ya no encajaba y el paso volvía a pedir permiso para siempre. La fila
    decía "aprobada" y el run se paraba igual — el fallo más silencioso posible,
    porque todo lo demás parecía funcionar.

    Lo que la persona aprueba no es un run: es **una llamada con unos
    argumentos**. Por eso se comparan la tool y los argumentos, y no el run. Un
    permiso para `aegis_write_file(path=X)` no autoriza `aegis_write_file(path=Y)`.

    ## Por qué el orden importa
    Se comprueba primero lo que siempre pregunta y solo al final lo que depende
    del permiso, para que el motivo que ve la persona sea el de la razón
    principal y no el de un detalle posterior.
    """
    # El token va primero: es una decisión ya tomada por la persona, y no tiene
    # sentido volver a preguntarle lo que ya respondió.
    #
    # Y se **mira antes de gastarlo**, que es la mitad de A-033. Antes se gastaba
    # aquí y se comparaba después: un relanzado en el que el modelo pedía la misma
    # tool con otros argumentos quemaba el permiso sin haberlo usado, y había que
    # volver a aprobar. Medido con `project_create` y su verificador: tres
    # intentos, tres aprobaciones, ninguna ejecutada. Un permiso que se pierde por
    # un desajuste de argumentos no es un permiso, es un adorno.
    if token:
        a0 = almacen_ or almacen()
        permiso = a0.por_token(token)
        if not permiso:
            return Decision(False, "ese permiso ya se usó, o no existe")
        if permiso["tool"] != tool:
            return Decision(
                False,
                f"ese permiso era para '{permiso['tool']}', no para '{tool}'. "
                "No lo he gastado: sigue esperando su oportunidad.")
        import json as _json
        if _json.loads(permiso["argumentos"] or "{}") != _json.loads(_json.dumps(args)):
            return Decision(
                False,
                f"ese permiso era para otra llamada distinta de {tool}: "
                f"lo que aprobaste fueron unos argumentos que ya no son estos. "
                f"No lo he gastado —aprueba la petición que acabo de dejar— "
                f"pero fijate en la diferencia antes: si no es la que querías, "
                f"deniega con motivo en vez de aprobar.")
        pagada = a0.gastar(token)
        if not pagada:
            # Solo sería posible con dos decisiones a la vez sobre el mismo token,
            # que es justo lo que el de un solo uso impide. Si pasa, se dice en vez
            # de fingir que el permiso está concedido.
            return Decision(False, "ese permiso se gastó en otro sitio a la vez")
        # El permiso era para esta llamada. Concedido significa concedido: si
        # aquí cayera al camino normal, la señal de "archivo virgen" volvería a
        # abrir una petición y la aprobación se habría perdido. Es lo que
        # Midió el test: el token se gasta, la escritura pasa, y la siguiente
        # ya no pregunta.
        from .mcp_ops import _safe_resolve
        try:
            marcar_tocado(_safe_resolve(str(args.get("path") or "")))
        except Exception:  # noqa: BLE001 — sin ruta no hay fichero que marcar
            pass
        return Decision(True, f"aprobado por ti (paso {paso}, {pagada['tool']})",
                        uso_token=True)

    # -- 0. lo que el enfoque activo cierra, antes que nada ----------------
    #
    # ## Por que va **primero**, antes incluso de los niveles
    # Un enfoque se pide para trabajar de otra manera, y parte de esa manera es
    # **no** hacer algo. Si esto se comprobara despues, una tool prohibida pasaria
    # por su nivel normal —que muchas veces es «libre» o «con permiso»— y llegaria
    # al disco. El cierre tiene que ser la primera puerta que mira la llamada.
    #
    # ## Y por que el motivo nombra el enfoque
    # «No puedo escribir» es un ruido: hay tres motivos distintos para no poder y
    # son arreglables de tres maneras. El mensaje dice **cual** es y **que hacer**:
    # un 7B que recibe «no puedes» reintenta lo mismo; uno que recibe «el enfoque
    # arquitectura cierra esto, sueltalo cuando el diseño este cerrado» cambia de
    # comportamiento.
    if enfoque:
        from . import enfoques
        cerradas = enfoques.restringe(enfoque)
        if tool in cerradas:
            return Decision(
                False,
                f"El enfoque '{enfoque}' tiene '{tool}' cerrada. No es una "
                f"recomendación: mientras estés en él no se ejecuta. Si ya "
                f"terminaste de decidir, suelta el enfoque con "
                f"usar_enfoque(nombre='') y vuelve a intentarlo.")

    a = almacen_ or almacen()
    nivel = nivel_de(tool)
    alias = alias_de(tool, args)

    # -- 1. lo que siempre pregunta, en todos los modos --------------------
    if nivel == "requiere_ok":
        fuera = FUERA_DEL_DISCO.get(tool, "")
        motivo = _motivo_de_que_va_a_pedir(tool, args, alias, fuera)
        pid = a.pedir(run_id=run_id, paso=paso, tool=tool, args=args,
                      motivo=motivo, proyecto=alias)
        return Decision(False, motivo, peticion=pid)

    # -- 2. escritura: depende del modo y de que el proyecto esté marcado ---
    if nivel == "con_permiso":
        modo = a.modo()
        if modo == "solo":
            return Decision(
                False,
                f"Estoy en modo 'solo': no escribo en nada. "
                f"Cambia a 'Marcados' en la pestaña Proyectos si quieres que "
                f"toque {alias or 'este proyecto'}.")
        if not alias:
            return Decision(
                False,
                "No sé de qué proyecto es este archivo, así que no lo toco. "
                "Marca el proyecto en la pestaña Proyectos y vuelve a intentarlo.")
        if alias not in a.proyectos():
            return Decision(
                False,
                f"No tengo permiso para escribir en '{alias}'. Está sin marcar: "
                f"márcalo en la pestaña Proyectos y lo hago. Leer sí.")

        # La base en rojo antes de empezar: si no sabes qué fallaba antes de
        # tocar nada, el rojo deja de servir de referencia.
        #
        # Y con `fin`: esto no es una respuesta, es un tope. Antes devolvía un
        # "no" más, el bucle lo leía como «sigue con otra cosa» y el run se
        # consumía entero (16 pasos) rechazando la misma escritura. Se paraba en
        # el primer write, que es justo cuando todavía no has gastado nada.
        if estado_base and estado_base.get("rojo"):
            return Decision(
                False,
                f"El verificador de '{estado_base.get('alias')}' ya estaba en rojo "
                f"cuando empecé ({estado_base.get('detalle', 'sin detalle')}). "
                f"No voy a escribir encima de una base que no conozco: "
                f"arreglala o dime que siga.",
                fin="verificador_rojo")

        destructiva = _es_destructiva(tool, args, a)
        if destructiva:
            pid = a.pedir(run_id=run_id, paso=paso, tool=tool, args=args,
                          motivo=f"Escritura grande: {destructiva}",
                          proyecto=alias)
            return Decision(False, destructiva, peticion=pid)

        # La primera vez sobre un fichero que Aegis no ha tocado nunca.
        from .mcp_ops import _safe_resolve
        ruta = None
        sin_tocar = False
        try:
            ruta = _safe_resolve(str(args.get("path") or ""))
            sin_tocar = not tocado_alguna_vez(ruta)
        except Exception:  # noqa: BLE001 — la whitelist lo dira mejor que yo
            ruta = None
        if sin_tocar and ruta is not None:
            pid = a.pedir(
                run_id=run_id, paso=paso, tool=tool, args=args,
                motivo=f"Primera vez que toco {ruta.name} en '{alias}'. "
                       f"Prefiero que me des el visto bueno una vez: después "
                       f"puedo trabajar aquí sin preguntar.",
                proyecto=alias)
            return Decision(False, "Primera vez en este archivo.", peticion=pid)

        if ruta is not None:
            marcar_tocado(ruta)
        return Decision(True, f"escritura autorizada en '{alias}' (marcado)")

    # -- 2. libre ----------------------------------------------------------
    return Decision(True, "no cambia nada")


def _motivo_de_que_va_a_pedir(tool: str, args: dict[str, Any], alias: str,
                              fuera: str) -> str:
    """Lo que la persona va a leer para decidir. Dice **qué** y **por qué**.

    Se escribe en la persona, no en el nombre de la tool: "voy a migrar la base
    de compra-unida" se puede aprobar leyendo; "db_migrate(project=...)" no.
    """
    algo = f"'{alias}'" if alias else "esto"
    detalle = {
        "db_migrate": f"Voy a **migrar la base** de {algo}: se leen y ejecutan "
                      f"migraciones SQL. {fuera}.",
        "neon_branch": f"Voy a **crear o mirar ramas** en la base de {algo}. {fuera}.",
        "build_apk": "Voy a **compilar la app** y escribir el APK en el árbol de build.",
        "install_apk": "Voy a **instalar la app** en un dispositivo.",
        "deploy_smoke": "Voy a **arrancar la app en el emulador** y comprobar que "
                        "habla con el bridge.",
        "adb_connect": "Voy a **conectar por adb** a un dispositivo.",
        "project_create": f"Voy a **dar de alta el proyecto** {algo}: se crea la "
                          f"carpeta y su ficha a medio hacer.",
    }.get(tool, f"Voy a usar {tool} sobre {algo}.")
    if tool == "install_apk":
        destino = args.get("target") or "emulador"
        detalle = (f"Voy a **instalar la app en {destino}**. NO se abrirá: "
                   f"instalar y abrir son pasos separados.")
    return detalle


def resume_denegaciones(limite: int = 4) -> str:
    """Lo que le has dicho que no, para inyectarlo en el prompt.

    Es el mecanismo que hace que denegar con motivo **no sea un gesto perdido**.
    Sin esto, la columna `razon_denegacion` se escribe y no la lee nadie: es un
    registro del bridge, no del agente.
    """
    filas = almacen().denegaciones_recientes(limite=limite)
    if not filas:
        return ""
    lineas = ["## Lo que ya me dijiste que no"]
    for f in filas:
        linea = f"- {f['tool']}" + (f" en {f['proyecto']}" if f["proyecto"] else "")
        linea += f": {f['por_que_no']}"
        lineas.append(linea)
    lineas.append("No lo vuelvas a proponer sin una razón nueva.")
    return "\n".join(lineas)


# -- La base antes de tocar nada ----------------------------------------------

def medir_base(alias: str, what: str = "check") -> dict[str, Any]:
    """El estado del verificador de un proyecto, **antes** de escribir.

    ## Por qué "está en rojo" no sirve como criterio
    `trazeurs` llega con 452 issues de `flutter analyze` de la plantilla. Para un
    proyecto así, "está en rojo" es su estado normal y no dice nada. Lo que
    significa algo es **¿está peor que cuando empecé?**: la comparación con la
    línea base, y el número de problemas es el dato, no el color.

    ## Por qué un rojo desconocido **no** es un rojo
    Si el verificador no se puede ejecutar —proyecto sin verificador, comando que
    no existe, tiempo agotado— el resultado es `rojo: None`, no `True`.
    Confundir "no pude mirar" con "está mal" frenaría a Aegis de forma permanente
    y sin causa, y un freno permanente es un freno que nadie mira.
    """
    from .verifier import ejecutar
    from .projects import PROJECTS
    if alias not in PROJECTS:
        return {"alias": alias, "rojo": None, "detalle": f"'{alias}' no está en el registro"}
    if not PROJECTS[alias].verify:
        return {"alias": alias, "rojo": None,
                "detalle": f"'{alias}' no tiene verificador declarado"}
    try:
        v = ejecutar(alias, what=what)
    except Exception as exc:  # noqa: BLE001 — no pude mirar no es "está mal"
        return {"alias": alias, "rojo": None,
                "detalle": f"no pude ejecutar el verificador: {exc}"}
    return {
        "alias": alias,
        "rojo": not v.ok,
        "problemas": v.cuenta,
        "que": what,
        "ms": v.ms,
        # El resumen se corta: el verificador puede sacar 452 líneas y aquí solo
        # hace falta la cuenta y un trozo para reconocerlo.
        "detalle": v.resumen[:200],
    }


def empeora(baseline: Optional[dict[str, Any]],
            nuevo: Optional[dict[str, Any]]) -> str:
    """Si `nuevo` está peor que `baseline`, por qué. Si no, '""'.

    La comparación es de **número de problemas**: con una base de 452, pasar de
    452 a 452 es neutro y pasar a 460 es empeorar, aunque los dos estén "en
    rojo". Y si no hay números en los dos lados no se compara: decir "empeoró" sin
    cifras es una conjetura, y una conjetura que frena el trabajo molesta más
    de lo que ayuda.
    """
    if not baseline or not nuevo:
        return ""
    b, n = baseline.get("problemas"), nuevo.get("problemas")
    if b is None or n is None:
        return ""
    if n > b:
        return (f"el verificador pasó de {b} problema(s) a {n} en "
                f"'{nuevo.get('alias', '?')}': eso es empeorar, no mejorar")
    return ""
