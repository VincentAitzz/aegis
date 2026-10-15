"""Recuperar los runs que estaban en marcha cuando el proceso murió.

## El problema, y por qué no basta con leer el JSONL

`_AUTOPILOT_RUNS` es un `dict` en memoria, y `aegis-bridge.service` está en
`Restart=always`. Consecuencia medida: **reiniciar el bridge borra todos los runs
en vuelo** sin dejar estado que diga dónde estaban.

La primera versión del arreglo fue «leer los JSONL al arrancar y reconstruir el
índice». Y es verdad que **la traza está en disco**. Lo que no está —o no estaba—
es el **estado**: si aquel run estaba corriendo, y cuál era su siguiente paso.

Un JSONL es un historial, y un historial no sabe si su último evento fue el final
o una interrupción. Por eso el escritor pasó a ser append-only
(`_abrir_jsonl_de_autopilot`): un run cortado deja `task.created` y sus pasos, y
eso **es** el estado — está en marcha, y se paró en el paso N.

## Qué se restaura, y qué no

| | |
|---|---|
| **traza, pasos, respuesta, fin, veredicto** | sí, leyendo el JSONL |
| **`running`** | **nunca**: la tarea de asyncio no existe tras el reinicio |
| **`interrumpido`** | sí — es lo que se marca, y es la diferencia entre «se perdió» y «nunca se empezó» |
| **la tarea viva** | no, y no puede: `asyncio.Task` no sobrevive a un proceso |

Y por eso `recuperar()` **no relanza nada por su cuenta**. Relanzar es una
decisión —de cuánto se reintenta, de qué plan, de si el corte fue un OOM o un
`systemctl restart`— y este módulo solo dice la verdad sobre lo que había.

## Por qué el run interrumpido **no** cuenta como roto

Porque `veredicto.py` trata `interrumpido` como lo que es: el trabajo se paró a
media. Un `SIGKILL` durante un despliegue y un despliegue que falla no son lo
mismo, y mezclarlos en un número esconde justo lo que hay que mirar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Eventos que cierran un run. Un JSONL sin ninguno de estos estaba en marcha.
TERMINALES = ("task.done", "task.failed", "task.stopped")

#: El `fin` que se le pone al que se encontró a medias.
FIN_INTERRUMPIDO = "interrumpido"


def _leer(ruta: Path) -> tuple[list[dict[str, Any]], str, int, bool, dict]:
    """(eventos, fin, pasos, terminado, payload_terminal) de un JSONL.

    Un JSONL con una línea corrupta no se salta entero: se lee lo que se puede y
    se cuenta lo que se perdió, porque perder un evento suelto y perder el run
    no son la misma cosa.
    """
    eventos: list[dict[str, Any]] = []
    fin = ""
    pasos = 0
    terminado = False
    terminal: dict[str, Any] = {}
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return eventos, fin, pasos, terminado, terminal

    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(evento, dict):
            continue
        eventos.append(evento)
        payload = evento.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if evento.get("event") == "tool.completed":
            if isinstance(payload.get("step"), int):
                pasos = max(pasos, int(payload["step"]))
            else:
                pasos += 1
        if evento.get("event") in TERMINALES:
            terminado = True
            fin = str(payload.get("fin") or evento.get("event") or "")
            terminal = payload
    return eventos, fin, pasos, terminado, terminal


def _sellar(ruta: Path) -> None:
    """Cierra en disco un run que estaba en marcha, con `fin: interrumpido`.

    Sin esto, el fichero se queda con `task.created` y sus pasos para siempre, y
    todo el que lo lee —`leer_run`, `medir-runs`, `veredicto`— ve un run sin
    motivo de cierre. En `desde_jsonl` eso acaba en `fin="reventado"`, que es
    **mentira**: un corte no es un fallo del run, es un corte del proceso.

    Es idempotente: se llama una sola vez por run, porque después de sellarlo ya
    hay terminal y la próxima lectura no vuelve a sellar.
    """
    try:
        with ruta.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": "", "run_id": ruta.stem, "event": "task.failed",
                "agent": "autopilot", "at_run": "",
                "payload": {"fin": FIN_INTERRUMPIDO, "answer": "",
                            "error": "el proceso se reinició con el run en marcha"},
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _estado_de(ruta: Path) -> dict[str, Any] | None:
    eventos, fin, pasos, terminado, terminal = _leer(ruta)
    if not eventos:
        return None
    run_id = str(ruta.stem)
    trace = [{"tool": (e.get("payload") or {}).get("tool"),
              "ok": (e.get("payload") or {}).get("ok"),
              "step": (e.get("payload") or {}).get("step")}
             for e in eventos
             if e.get("event") == "tool.completed"
             and isinstance(e.get("payload"), dict)
             and (e.get("payload") or {}).get("tool")]
    fin_real = fin or (FIN_INTERRUMPIDO if not terminado else "")
    answer = str(terminal.get("answer") or "")

    # El veredicto se calcula **aquí**, y no se deja vacío. Un run restaurado sin
    # `estado` ni `resumen` es un run del que no se puede decir nada, y quien lo
    # consulte por HTTP vería un `interrumpido` sin explicación — que es
    # justamente el campo que existe para contarla.
    #
    # **No sustituye al del terminal.** Si el run terminó de verdad, su veredicto
    # se calculó con la traza entera, y recalcularlo aquí daría otro número con
    # la traza recortada. Solo se usa cuando no vino, que es el caso del run
    # restaurado.
    calculado: dict[str, Any] = {}
    try:
        from .veredicto import clasificar as _clasificar
        calculado = _clasificar(fin_real, trace, answer)
    except Exception:  # noqa: BLE001 — sin veredicto, el run sigue recuperable
        pass

    return {
        "run_id": run_id,
        # **Nunca `running`.** La tarea no existe tras el reinicio, y decir que
        # un run está corriendo cuando no lo está hace que un cliente espere
        # indefinidamente a algo que ya no va a llegar.
        "status": "interrumpido" if not terminado else "completed",
        # Va fuera a propósito. El sellado tiene que decidir con «¿tenía ya un
        # evento terminal?», no con «¿su fin es `interrumpido`?»: después de
        # sellarlo **el fin sigue siendo `interrumpido`**, así que la segunda
        # condición volvía a dar que sí en cada arranque y le añadía otra línea
        # —y otra, y otra— a un fichero que no tenía por qué crecer. Es el tipo
        # de bug que solo se ve al reiniciar el puente tres veces, y por eso
        # `test_es_idempotente` lo comprueba.
        "_terminado": bool(terminado),
        "fin": fin_real,
        "steps": pasos,
        "answer": answer,
        "trace": trace,
        "error": str(terminal.get("error") or ""),
        # Si el terminal trae veredicto, **manda**: lo calculó el run real con
        # la traza entera. El de arriba solo rellena cuando no vino, que es el
        # caso del run restaurado.
        "estado": str(terminal.get("estado") or calculado.get("estado") or ""),
        "completado": bool(terminal.get("completado")
                           if "completado" in terminal
                           else calculado.get("completado")),
        "resumen": str(terminal.get("resumen") or calculado.get("resumen") or ""),
        "duracion_s": float(terminal.get("duracion_s") or 0.0),
        "restaurado": True,
    }


def recuperar(directorio: Path, *, maximo: int = 50,
              solo_autopilot: bool = True,
              sellar: bool = True) -> list[dict[str, Any]]:
    """Los runs del disco, del más reciente al más viejo, ya en forma de buffer.

    `solo_autopilot` deja fuera los `run_*.jsonl` de Hermes: son de otro motor
    y no tienen este formato. Si mañana se mezclaran, sus `steps` serían otra
    cosa y el `status` mentiría.

    El tope es el mismo que el del buffer en memoria (`_AUTOPILOT_RUNS_MAX`): si
    se recuperan más, los que no quepan no se ven por `GET /autopilot/{id}` igual
    que si nunca hubieran existido, y la mejor forma de no perder trabajo es
    **empezar por el más reciente**.
    """
    if not directorio.exists():
        return []
    salida: list[dict[str, Any]] = []
    ficheros = sorted(
        directorio.glob("autopilot-*.jsonl" if solo_autopilot else "*.jsonl"),
        key=lambda p: p.stat().st_mtime, reverse=True)
    for ruta in ficheros:
        estado = _estado_de(ruta)
        if estado is None:
            continue
        if not estado["_terminado"] and sellar:
            _sellar(ruta)
        salida.append(estado)
        if len(salida) >= maximo:
            break
    return salida


def interrumpidos(recuperados: list[dict[str, Any]]) -> list[str]:
    """Los ids de los runs que estaban en marcha y no llegaron a nada.

    Es la lista con la que hay que hacer algo al arrancar: son los que hay que
    decidir si se relanzan, y los que hay que contar cuando Aegis dice que no
    perdió trabajo.
    """
    return [r["run_id"] for r in recuperados if r.get("fin") == FIN_INTERRUMPIDO]