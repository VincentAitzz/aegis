"""¿Está Aegis hablando ahora mismo?

## Qué es
Un reloj. Cuando llega texto de un run, alguien llama a [`marcar`] y el módulo
contiene la hora. `hablando` es `True` mientras esa hora no sea más antigua que
la ventana.

## Por qué un reloj y no un registro de runs
Porque «tiene una misión abierta» y «está hablando» no son lo mismo, y para lo
que se usa —**pintar de magenta el glifo**— importa la segunda. Un run puede
estar pensando treinta segundos antes de decir nada, y un glifo encendido en ese
rato dice «está hablando» cuando no está, que es exactamente la clase de mentira
que este repo lleva desandando desde A-016.

La ventana es corta a propósito: 2,5 s. Con una ventana larga, un run que acaba
de terminar deja el glifo encendido un rato y parece que sigue. Con una ventana
corta, un parpadeo entre deltas deja el glifo parpadear, y eso es peor. La de
2,5 s aguanta un stream con deltas separados y se apaga en cuanto calla.

## Por qué en memoria y no en disco
Es una señal de **este momento**, no un dato. Reiniciar el bridge lo pone a
cero, que es exactamente lo que quiere: si el bridge no vive, no hay nadie
hablando, y el glifo tiene que estar en reposo.
"""

from __future__ import annotations

import time

#: Cuánto se considera que sigue hablando después de la última frase.
VENTANA_S = 2.5

_ultimo: dict = {"ts": 0.0, "que": "", "run": ""}


def marcar(que: str, run: str = "") -> None:
    """Anota que acaba de haber texto."""
    _ultimo["ts"] = time.time()
    _ultimo["que"] = que
    _ultimo["run"] = run


def limpiar() -> None:
    """Olvida la última frase. Para las pruebas y para apagar el bridge."""
    _ultimo["ts"] = 0.0
    _ultimo["que"] = ""
    _ultimo["run"] = ""


def estado() -> dict:
    """Lo que ve la app. Nunca lanza: si esto falla, la UI se queda en reposo."""
    ahora = time.time()
    edad = ahora - _ultimo["ts"]
    return {
        "hablando": _ultimo["ts"] > 0 and edad < VENTANA_S,
        "desde": _ultimo["ts"],
        "hace_s": round(edad, 1) if _ultimo["ts"] else -1,
        "que": _ultimo["que"] if edad < VENTANA_S else "",
        "run": _ultimo["run"] if edad < VENTANA_S else "",
    }
