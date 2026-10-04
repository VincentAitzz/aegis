"""El verificador: convierte "el modelo dijo que lo hizo" en "lo comprobamos".

Es la señal de retorno del agente. Sin esto, un run termina cuando el modelo
deja de pedir tools, y eso no dice absolutamente nada sobre si el código
funciona. Ya se midió: un modelo local llega a reportar "el archivo se creó y se
verificó" sin haber escrito nada. La única respuesta que vale es la del proceso
que ejecuta el comando.

Tres ideas:

- Un veredicto es comparable con otro, para poder decir si un paso mejoró lo que
  hizo el anterior y no solo lo volvió a hacer.
- Dos errores se comparan por firma normalizada, no por texto: si la firma es la
  misma, el agente no progressedó, por mucho que el mensaje cambie.
- Una llamada idéntica que ya falló dos veces no se reintenta: se escala. Es el
  modo de fallo medido (siete escrituras seguidas con la misma ruta mala).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .projects import PROJECTS

# Una línea con esto es un problema. A propósito generoso: preferimos contar de
# más, porque un falso positivo se ve y uno por menos esconde el fallo. El
# IGNORECASE no es opcional: los compiladores escriben ERROR en mayúsculas y
# eslint en minúsculas, y un patrón sin él no cuenta ni la mitad.
ERROR_RE = re.compile(
    r"error|failed|fail|✗|exception|traceback|warning",
    re.IGNORECASE,
)
# Lo que cambia entre dos corridas del mismo error: rutas, números, hashes,
# timestamps. Se sustituye por '?' para que las firmas sean comparables. Primero
# las rutas (contienen dígitos y barras), luego el resto.
RUIDO_RE = re.compile(r"\S*[/\\]\S*|\d+|[0-9a-fA-F]{7,}")

QUE_ESCRIBEN = frozenset({"aegis_write_file", "aegis_patch_file"})


@dataclass
class Verdict:
    """Lo que un verificador respondió, en forma comparable."""

    ok: bool
    what: str
    proyecto: str
    exit_code: Optional[int]
    resumen: str
    firmas: tuple[str, ...] = ()
    ms: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        """Forma serializable: las tuplas no sobreviven a json.dumps."""
        datos = {
            "ok": self.ok, "what": self.what, "proyecto": self.proyecto,
            "exit_code": self.exit_code, "resumen": self.resumen,
            "firmas": list(self.firmas), "ms": self.ms, "error": self.error,
        }
        return datos

    @property
    def cuenta(self) -> int:
        return contar_problemas(self.resumen)


def _falla(proyecto: str, what: str, motivo: str) -> Verdict:
    """Un veredicto que no se pudo ejecutar. No lanza: quien llama tiene que poder
    seguir y reportar, y una excepción aquí dejaría el run sin veredicto."""
    return Verdict(ok=False, what=what, proyecto=proyecto, exit_code=None,
                   resumen="", error=motivo)


def contar_problemas(texto: str) -> int:
    """Cuántas líneas de la salida del verificador parecen un problema."""
    return sum(1 for linea in (texto or "").splitlines()
               if linea.strip() and ERROR_RE.search(linea))


def firmas_de(texto: str) -> tuple[str, ...]:
    """Firmas de error normalizadas, para comparar dos corridas."""
    firmas: list[str] = []
    for linea in (texto or "").splitlines():
        if not (linea.strip() and ERROR_RE.search(linea)):
            continue
        firma = RUIDO_RE.sub("?", linea.strip().lower())
        firma = re.sub(r"\s+", " ", firma)[:120]
        if firma not in firmas:
            firmas.append(firma)
        if len(firmas) >= 8:
            break
    return tuple(firmas)


def ejecutar(proyecto: str, what: str = "check", timeout: int = 900) -> Verdict:
    """Corre el verificador declarado del proyecto y devuelve su veredicto."""
    if what not in ("check", "test", "build"):
        return _falla(proyecto, what, f"verificador desconocido: {what!r} "
                                      "(usa check, test o build)")
    proj = PROJECTS.get(proyecto)
    if proj is None:
        return _falla(proyecto, what,
                      f"proyecto desconocido: {proyecto} "
                      f"(conocidos: {', '.join(sorted(PROJECTS))})")
    cmd = (proj.verify or {}).get(what)
    if not cmd:
        return _falla(proyecto, what,
                      f"'{proyecto}' no declara verificador para '{what}' "
                      f"(disponibles: {sorted(proj.verify or {}) or 'ninguno'})")
    if not proj.root.exists():
        return _falla(proyecto, what, f"la raíz no existe: {proj.root}")

    exe = Path(cmd[0])
    if not exe.is_absolute() and "/" in cmd[0] and not (proj.root / cmd[0]).exists():
        return _falla(proyecto, what,
                      f"falta {cmd[0]} en {proj.root} (¿instalaste las dependencias?)")

    env = dict(os.environ)
    env["PATH"] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH', '')}"
    env.setdefault("JAVA_HOME", "/RUTA/AL/JDK")

    inicio = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=env, cwd=str(proj.root), timeout=timeout)
    except subprocess.TimeoutExpired:
        return _falla(proyecto, what, f"el verificador agotó {timeout}s")
    except (FileNotFoundError, OSError) as exc:
        return _falla(proyecto, what, f"no pude ejecutar {cmd[0]}: {exc}")
    ms = int((time.monotonic() - inicio) * 1000)

    salida = (proc.stdout + proc.stderr).strip().splitlines()
    resumen = "\n".join(salida[-20:])
    return Verdict(ok=proc.returncode == 0, what=what, proyecto=proyecto,
                   exit_code=proc.returncode, resumen=resumen,
                   firmas=firmas_de(resumen), ms=ms)


def delta(antes: Optional[Verdict], despues: Verdict) -> dict:
    """¿Este paso mejoró lo anterior, o solo lo repitió?

    `mismo_error` es la señal honesta: si las firmas coinciden, el agente está
    golpeando el mismo muro con distinta forma.
    """
    antes_cuenta = antes.cuenta if antes else 0
    problemas = despues.cuenta
    d = antes_cuenta - problemas
    mismo = bool(antes and antes.firmas and despues.firmas
                 and antes.firmas == despues.firmas)
    return {
        "ok": despues.ok,
        "problemas": problemas,
        "antes": antes_cuenta,
        "delta": d,
        "mismo_error": mismo,
        "mejoro": bool(despues.ok and d > 0),
    }


def es_repetido(historial: list[dict[str, Any]], tool: str,
                argumentos: dict[str, Any]) -> bool:
    """¿Esta llamada idéntica ya falló dos veces? Entonces no se reintenta.

    Es la defensa contra el gasto de 16 pasos en lo mismo: el modo de fallo
    medido fue siete escrituras seguidas con la misma ruta equivocada.
    """
    objetivo = json.dumps(argumentos, sort_keys=True, ensure_ascii=False, default=str)
    veces = 0
    for entrada in historial or []:
        if entrada.get("tool") != tool or entrada.get("ok") is not False:
            continue
        previo = json.dumps(entrada.get("arguments") or {},
                            sort_keys=True, ensure_ascii=False, default=str)
        if previo == objetivo:
            veces += 1
    return veces >= 2


def gate(proyecto: str, what: str = "check") -> Callable:
    """Puerta de verificación por paso para `run_autopilot(gate=...)`.

    Solo juzga lo que el agente **escribió**. Verificar en cada lectura sería
    ruido, y `build_apk` ya se verifica a sí mismo.

    Pone `"stop": True` cuando el verificador falla y el problema no se movió: a
    partir de ahí, seguir gastando pasos es peor que devolver el control.

    ## Y además, la escalada
    `es_repetido` estaba escrita desde hacía tiempo y **no se llamaba**: la
    lección que la nombra como antidoto describía un mecanismo que no estaba
    montado. Aquí se usa para algo que la puerta sola no ve: la puerta compara
    el verificador, y dos escrituras a la misma ruta equivocada con el mismo
    contenido dejan el verificador igual. Eso es «no está progresando», y es
    justo lo que `es_repetido` mide.
    """
    previo: dict[str, Optional[Verdict]] = {"v": None}
    historial: list[dict[str, Any]] = []

    async def _gate(step: int, tool: str, argumentos: dict[str, Any],
                    resultado: str) -> Optional[dict[str, Any]]:
        if tool not in QUE_ESCRIBEN:
            return None
        v = ejecutar(proyecto, what)
        d = delta(previo["v"], v)
        previo["v"] = v
        veredicto: dict[str, Any] = {
            "ok": v.ok,
            "verificador": what,
            "problemas": d["problemas"],
            "delta": d["delta"],
            "mismo_error": d["mismo_error"],
            "exit_code": v.exit_code,
            "resumen": (v.error or v.resumen)[:800],
            "ms": v.ms,
        }
        if not v.ok and d["delta"] <= 0:
            veredicto["stop"] = True
            veredicto["motivo"] = (
                "el verificador sigue en rojo y el número de problemas no bajó: "
                "repetir el mismo paso no lo arregla")
        if not v.ok and es_repetido(historial, tool, argumentos):
            # El caso que la puerta sola no ve: el mismo write, con los mismos
            # argumentos, que ya rompió dos veces. Aquí el rojo no ha cambiado,
            # pero el **qué** tampoco: no hay nada nuevo que probar.
            veredicto["stop"] = True
            veredicto["repetida"] = True
            veredicto["motivo"] = (
                f"esta misma llamada a `{tool}` ya ha fallado dos veces con esos "
                f"argumentos. Repetirla no lo arregla: cambia el enfoque o dime "
                f"qué hacer.")
        historial.append({"tool": tool, "arguments": argumentos, "ok": v.ok})
        return veredicto

    return _gate
