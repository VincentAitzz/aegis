"""Qué pasó de verdad en un run, dicho con un dato y no con un adjetivo.

## Por qué esto existe

Un run terminaba con un `fin`, y `fin` no dice si el trabajo se hizo. Medido
sobre los 133 runs de `data/logs/runs/`: **cero** con un `fin` de "completado",
59 con `sin_tools` y 31 con `max_steps`. Peor: el nombre miente, porque un
`sin_tools` con una tool ejecutada y una respuesta buena **es** un run terminado
— el modelo llamó a `registry_list`, leyó la respuesta y contestó bien. Con
solo el `fin`, ese run era indistinguible de uno que se rindió a mitad.

Lo que faltaba no era el dato: la traza ya lo tenía todo. Faltaba leerla.

## La regla

El veredicto sale de **la traza**, nunca de `final_text` (A-016). Un `final` sin
tool ejecutada es un texto, y un texto no prueba que se tocara nada.

Seis estados, y solo seis:

| estado | qué significa |
|---|---|
| `completado` | el modelo paró por su cuenta, había tool verde, y respondió |
| `incompleto` | se paró sin llegar a responder, o sin ninguna tool verde |
| `esperando_ok` | el run está esperando a una persona (no es un fallo) |
| `parado` | lo paró quien lo lanzó, a propósito |
| `roto` | el modelo no respondió, o el run reventó |
| `rechazado` | la puerta de verificación o la autonomía lo frenó |

`completado` **no** significa "el trabajo estaba bien hecho". Significa "el
agente cree que terminó y hay una tool que lo demuestra". La diferencia con la
calidad la pone `verificador.py`, que es otro asunto.

## Una regla, dossitios

`classificar` funciona sobre un `fin` y una traza ya en memoria (el run en
vivo), y `desde_jsonl` sobre las líneas de un fichero de traza (el histórico).
Las dosllaman a la misma `_clasificar`, así que un run de hace una semana y uno
de ahora no se pueden etiquetar con reglas distintas: si divergieran, cualquier
comparación entre ellos sería mentira.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from . import evidencia

# Los `fin` que el bucle puede devolver (`autopilot.py`) más los que pone
# `main.py` cuando el run revienta antes de empezar a correr.
FINS_ROTO = frozenset({"modelo_caido", "reventado"})
FINS_ESPERA = frozenset({"esperando_ok"})
FINS_PARADO = frozenset({"parado"})
FINS_RECHAZO = frozenset({
    "verificador_rojo", "llamada_repetida",
    "autonomia_bloqueada", "sin_ficha", "enfoque_cerrado",
})
# El modelo se paró solo y dio un `fin` de cierre normal.
FINS_PROPIO = frozenset({"sin_tools", "respuesta_vacia", "max_steps"})


def _herramientas(trace: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Los nombres de las tools de la traza, en orden y sin repetir.

    ## Tres formas, y por qué no es un descuido
    La traza llega en tres formatos según de dónde venga, y meterlos todos aquí
    es lo que hace que un número valga para el run en vivo y para el fichero de
    hace tres semanas:

    - **`{"tool": …, "ok": …}`** — la traza en memoria, tal cual la construye
      `autopilot._bucle`.
    - **`{"payload": {"tool": …, "ok": …}}`** — lo que escribe
      `main._escribir_jsonl_de_autopilot` (runs de autopilot).
    - **`{"payload": {"data": {"tool": …, "error": …}}}`** — lo que emitía
      Hermes, y que leía `hooks.py`. Son los 84 ficheros `run_*.jsonl` que hay en
      `data/logs/runs/`; sin esta rama quedarían fuera de la cuenta.

    ## Dos maneras de decir que una tool falló
    Autopilot graba `ok: false`; Hermes grababa `error` con el motivo. Se leen
    las dos, porque quien lee un run viejo tiene que obtener el mismo veredicto
    que habría obtenido el run nuevo: si solo se mirara `ok`, todos los
    ficheros de Hermes darían "tool verde" y el `completado` de la línea base
    saldría inflado.

    El `ok` explícito vale más que su ausencia: un paso que no grabó el campo
    no es una tool verde, es un dato que falta. Por eso `fuente.get("ok") is False`
    y no `not fuente.get("ok")` — que trataría como rojo lo que solo no grabó el
    campo.
    """
    ok: list[str] = []
    rojas: list[str] = []
    for entry in trace or []:
        if not isinstance(entry, dict):
            continue
        fuente: Any = entry
        payload = entry.get("payload")
        if isinstance(payload, dict):
            data = payload.get("data")
            fuente = data if isinstance(data, dict) else payload
        nombre = fuente.get("tool") or entry.get("tool")
        if not nombre or not isinstance(nombre, str):
            continue
        fallo = fuente.get("ok") is False or bool(fuente.get("error"))
        (rojas if fallo else ok).append(nombre)
    return list(dict.fromkeys(ok)), list(dict.fromkeys(rojas))


def _clasificar(fin: str, ok: list[str], rojas: list[str],
                answer: str, sin_respaldo: list[str] | None = None
                ) -> tuple[str, str]:
    """(estado, resumen). La regla unica; todo lo demas la llama.

    `sin_respaldo` son las afirmaciones de la respuesta que la traza no
    sostiene (ver `app/evidencia.py`). Solo puede **bajar** el estado de
    `completado` a `sin_evidencia`, nunca subirlo: un run sin evidencia no es
    mejor que uno con ella, es peor o igual. Por eso va al final de la cadena y
    no entre los `fin`.
    """
    resumen = ""
    caidas = list(sin_respaldo or [])
    if fin in FINS_ROTO:
        estado = "roto"
    elif fin in FINS_ESPERA:
        estado = "esperando_ok"
    elif fin in FINS_PARADO:
        estado = "parado"
    elif fin in FINS_RECHAZO:
        estado = "rechazado"
    elif fin in FINS_PROPIO:
        # Aquí está la decisión que no se podía tomar antes. El modelo se paró
        # solo: eso no dice si terminó. Lo dice si hay una tool que lo sostiene.
        estado = "completado" if (ok and answer.strip()) else "incompleto"
    elif fin:
        # Un `fin` que no está en ninguna lista es un dato nuevo. No se
        # clasifica como completado por omisión: se marca como roto, que es lo
        # que obliga a mirar.
        estado = "roto"
    else:
        estado = "incompleto"

    if estado == "completado" and caidas:
        # El unico caso en el que se degrada un estado ya bueno. Hay tool verde
        # y hubo respuesta, pero la respuesta afirma cosas que no pasaron. No
        # es `roto` —el trabajo se hizo— y no es `completado` —no se puede
        # decir que se delivered. Se llama distinto a propósito.
        estado = "sin_evidencia"
        resumen = (f"{len(ok)} tool(s) en verde, pero {len(caidas)} "
                   f"afirmación(es) sin respaldo: " + "; ".join(caidas[:3])
                   + ("…" if len(caidas) > 3 else ""))
    elif estado == "completado":
        resumen = f"{len(ok)} tool(s) en verde, respuesta de {len(answer.strip())} car."
    elif estado == "esperando_ok":
        resumen = "parado esperando tu OK; no ha escrito nada."
    elif estado == "parado":
        resumen = f"parado a petición tuya tras {len(ok)} tool(s)."
    elif estado == "rechazado":
        resumen = f"la puerta lo frenó tras {len(ok)} tool(s)."
    elif estado == "roto":
        resumen = "el run no llegó a un cierre propio."
    elif ok:
        resumen = (f"ejecutó {len(ok)} tool(s) y paró sin responder"
                   + (f"; {len(rojas)} en rojo" if rojas else "") + ".")
    else:
        resumen = "no llegó a ejecutar ninguna tool."
    return estado, resumen


def clasificar(fin: str, trace: Iterable[dict[str, Any]],
               answer: str = "") -> dict[str, Any]:
    """Etiqueta un run ya terminado. `trace` son entradas de la traza en memoria.

    Devuelve `estado`, `resumen`, `tools_ok`, `tools_fallidas` y `completado`
    (un bool que es `estado == "completado"`, para no obligar a quien lee a
    recordar la palabra).
    """
    ok, rojas = _herramientas(trace)
    ev = evidencia.resumen(answer or "", list(trace or []))
    estado, resumen = _clasificar(fin or "", ok, rojas, answer or "",
                                  [d for d in ev["detalle"]])
    return {
        "estado": estado,
        "completado": estado == "completado",
        "resumen": resumen,
        "tools_ok": ok,
        "tools_fallidas": rojas,
        "evidencia": ev,
    }


def desde_jsonl(lineas: Iterable[str]) -> dict[str, Any]:
    """Etiqueta un run leyéndolo del JSONL. Misma regla que `clasificar`.

    Lo usa el análisis histórico, y con eso la línea base se calcula con el
    mismo criterio que va a juzgar el código nuevo. Si el histórico se midiera
    con otra regla, la comparación entre «antes» y «después» no valdría.
    """
    fin = ""
    answer = ""
    error = ""
    trace: list[dict[str, Any]] = []
    for linea in lineas:
        try:
            evento = json.loads(linea)
        except (ValueError, TypeError):
            continue
        if not isinstance(evento, dict):
            continue
        trace.append(evento)
        if evento.get("event") in ("task.done", "task.failed", "task.stopped"):
            payload = evento.get("payload")
            if isinstance(payload, dict):
                fin = payload.get("fin") or evento.get("event", "")
                answer = payload.get("answer") or ""
                error = payload.get("error") or ""
    if not fin and error:
        fin = "modelo_caido"
    if not fin and trace:
        # Un fichero sin evento terminal: el run se cortó. Eso no es un `fin`
        # limpio y no puede contarse como nada bueno.
        fin = "reventado"
    veredicto = clasificar(fin, trace, answer)
    veredicto["fin"] = fin
    return veredicto


def resumir(run_ids: Iterable[tuple[str, Iterable[str]]]) -> dict[str, Any]:
    """Reparto de estados de una lista de `(run_id, líneas)`.

    Devuelve también el desglose por `fin`: sin él, `incompleto` no dice qué
    arreglar, y 31 runs con `max_steps` son un problema distinto de 3 con
    `modelo_caido`.
    """
    estados: dict[str, int] = {}
    fins: dict[str, int] = {}
    detalle: list[dict[str, Any]] = []
    for run_id, lineas in run_ids:
        v = desde_jsonl(lineas)
        estados[v["estado"]] = estados.get(v["estado"], 0) + 1
        fins[v["fin"] or "?"] = fins.get(v["fin"] or "?", 0) + 1
        detalle.append({"run_id": run_id, **{k: v[k] for k in ("estado", "fin", "resumen")}})
    total = sum(estados.values())
    return {
        "total": total,
        "estados": estados,
        "fins": fins,
        "pct_completado": round(100.0 * estados.get("completado", 0) / total, 1) if total else 0.0,
        "detalle": detalle,
    }