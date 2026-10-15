"""El cierre de un run: qué pasó, en cinco apartados, y solo lo que importa.

## Por qué existe

Lo que Aegis hace al terminar un run es devolver un `answer` y un `fin`. Luego
la persona tiene que ir a `GET /runs/{id}` a buscar qué pasó. Eso es lo
contrario de lo que se pidió:

> Aegis debe… informarme de resultados, cambios drásticos, errores, decisiones
> con sus argumentos, y recomendaciones. Y cae en mí la responsabilidad de
> revisar los avances en mi ausencia.

Esos cinco son exactamente los cinco apartados de `cierre()`. Y hay uno más,
que es el que hace que los otros cinco valgan: **recomendaciones**.

## La regla: sale de la traza, nunca del texto

Tercera vez que se aplica la misma idea. La primera, A-016: el veredicto sale de
la traza y no de `final_text`, porque tres episodios falsos con `answer="OK"`
bajaban el tool-calling de 7/8 a 0/8. La segunda, `app/evidencia.py`: las
afirmaciones del modelo se comprueban contra la traza, porque una conversación no
tiene tool que revisar y el hueco se llena de «está en verde» sin comprobar.

Aquí la regla es la misma y por el mismo motivo: **un informe escrito por el
modelo sobre sí mismo no es un informe**. Si Aegis dice «cerré el trabajo», y el
cierre lo cuenta, lo que cuenta es la traza.

Cada apartado de este módulo sale de un dato de la traza:

| apartado | de dónde sale |
|---|---|
| resultados | las tools que se ejecutaron, con su `ok` |
| cambios drásticos | las reformulaciones, los cambios de `usar_enfoque`, los pasos saltados |
| errores | las tools en rojo, y los `fin` de rotura |
| decisiones | `usar_enfoque`, y los desvíos del encargo |
| recomendaciones | lo anterior, por reglas — **nunca el modelo** |

## Por qué las recomendaciones NO las escribe el modelo

Porque es el único apartado donde el modelo podría decir cualquier cosa sin que
nadie se entere: nadie más va a mirar. Un modelo al que se le pide «recomienda»,
responde con algo plausible, y suena igual de profesional que las otras cuatro
secciones.

Y hay una asimetría real: los otros cuatro apartados describen **hechos** que se
pueden comprobar. Este describe una **opinión**, y una opinión generada no vale
como recomendación: es relleno con formato de consejo.

Las reglas son tres y están a la vista, en `_recomendaciones()`. Que sean tres y
no una dozen es el punto: **una recomendación que siempre sale es un aviso, y
un aviso que siempre sale es ruido.**

## El filtro de vitalidad

No se notifica nada. El cierre se escribe siempre y se consulta cuando quieras.
Un run donde no hubo errores, ni reformulación, ni decisión, **no produce nada
que leer** — `vacio()` lo dice, y quien lo consulte lo ve.

Eso es lo que separa un asistente de un log: un log te avisa de todo y por eso
no te avisa de nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import evidencia as _evidencia


@dataclass
class Cierre:
    """Los cinco apartados, más lo que los sostiene.

    `sostiene` son los datos de la traza de los que sale cada apartado. Se
    devuelven para que el informe sea **auditable**: no hay que creerle a este
    módulo, se leen los datos y se comprueba que el apartado sale de ahí. La
    invariante es «siempre se puede saber qué hizo y por qué», y un informe que
    no enseña sus fuentes no la cumple.
    """

    resultados: list[str] = field(default_factory=list)
    cambios_drasticos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    decisiones: list[str] = field(default_factory=list)
    recomendaciones: list[str] = field(default_factory=list)
    sostiene: dict[str, list[str]] = field(default_factory=dict)
    vital: bool = False

    @property
    def vacio(self) -> bool:
        """Nada que leer. Es una respuesta, no un fallo."""
        return not (self.cambios_drasticos or self.errores or self.decisiones
                    or self.recomendaciones)

    def a_dict(self) -> dict[str, Any]:
        return {
            "resultados": self.resultados,
            "cambios_drasticos": self.cambios_drasticos,
            "errores": self.errores,
            "decisiones": self.decisiones,
            "recomendaciones": self.recomendaciones,
            "sostiene": self.sostiene,
            "vital": self.vital,
            "vacio": self.vacio,
        }

    def como_texto(self) -> str:
        """El informe en texto, para el móvil y para el terminal.

        Los apartados vacíos **no se imprimen**. Un informe con cinco títulos y
        tres líneas dice «no pasó nada» en 200 caracteres; uno con solo lo que
        pasó dice lo mismo en 40, y se lee.
        """
        if self.vacio:
            return "Sin nada que contar: el run fue sin errores, sin cambios " \
                   "drásticos y sin decisiones."
        partes: list[str] = []
        for titulo, valores in (
            ("RESULTADOS", self.resultados),
            ("CAMBIOS DRÁSTICOS", self.cambios_drasticos),
            ("ERRORES", self.errores),
            ("DECISIONES", self.decisiones),
            ("RECOMENDACIONES", self.recomendaciones),
        ):
            if valores:
                partes.append(f"{titulo}")
                partes += [f"  · {v}" for v in valores]
        return "\n".join(partes)


def _herramientas(trace: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Los nombres de las tools de la traza, en orden y sin repetir.

    Los tres formatos y el porqué están en `veredicto._herramientas`; se llama a
    esa función en vez de repetirla, para que un run viejo y uno de ahora no
    puedan etiquetarse con reglas distintas.
    """
    from .veredicto import _herramientas as _v
    return _v(trace)


def _a_texto(entrada: Any) -> str:
    from .evidencia import _a_texto as _e
    return _e(entrada)


def cierre_de(answer: str, trace: Iterable[dict[str, Any]], *,
              fin: str = "",
              reformulaciones: Iterable[dict[str, Any]] = (),
              plan_objetivo: str = "") -> Cierre:
    """Construye el cierre de un run.

    Los argumentos de la derecha son opcionales a propósito: el cierre tiene que poder
    construirse **desde la traza sola**, que es lo que permite reetiquetar el
    histórico entero con la misma regla. Lo que necesita el run vivo —las
    reformulaciones y el objetivo del plan— lo mejora, y su ausencia no lo
    invalida: es un run viejo, y los runs viejos no tienen plan.
    """
    trace = list(trace or [])
    ok, rojas = _herramientas(trace)
    c = Cierre()

    # -- resultados: las tools que se ejecutaron -----------------------------
    c.resultados = [f"{n}: en verde" for n in ok]
    c.sostiene["resultados"] = [f"tool ok: {n}" for n in ok]

    # -- errores: las rojas y las roturas ------------------------------------
    c.errores = [f"{n}: en rojo" for n in rojas]
    if fin in ("modelo_caido", "reventado"):
        c.errores.append(f"el run terminó por `{fin}`")
    if fin == "max_steps":
        c.errores.append(
            "agotó los pasos sin cerrar por su cuenta: el trabajo quedó a medias")
    c.sostiene["errores"] = [f"tool roja: {n}" for n in rojas] + \
                           ([f"fin: {fin}"] if fin else [])

    # -- cambios drásticos: reformulaciones y cambios de enfoque -------------
    cambios: list[str] = []
    for r in reformulaciones:
        cambios.append(f"reformuló «{r.get('antes', '?')}» por «{r.get('despues', '?')}»"
                       + (f" — {r['motivo']}" if r.get("motivo") else ""))
    for e in trace:
        nombre = (e.get("tool") if isinstance(e, dict) else None) or \
                 ((e.get("payload") or {}).get("tool")
                  if isinstance(e, dict) and isinstance(e.get("payload"), dict)
                  else None)
        if nombre == "usar_enfoque":
            args = ((e.get("payload") or {}).get("data") or e).get("arguments") \
                if isinstance(e, dict) else None
            if isinstance(args, dict) and args.get("nombre"):
                cambios.append(f"eligió el enfoque «{args['nombre']}»")
    c.cambios_drasticos = cambios
    c.sostiene["cambios_drasticos"] = [
        f"reformulacion: {r.get('motivo', '')}" for r in reformulaciones] + \
        ["usar_enfoque" for e in trace
         if isinstance(e, dict) and (e.get("tool") == "usar_enfoque")]

    # -- decisiones: del enfoque y de la evidencia ---------------------------
    decisiones = list(cambios)
    caidas = _evidencia.sin_respaldo(answer, trace)
    if caidas:
        # La cadena empieza por SIN RESPALDO y no por otra cosa porque hay un
        # test que depende de ella y porque las tres reglas de abajo la buscan
        # así. Se dice aquí porque la versión anterior decía «la traza no
        # sostiene» y la regla buscaba «sin respaldo»: dos maneras de decir lo
        # mismo, y la recomendación **no salía nunca**. Es A-124 en pequeño —un
        # detector que no suena parece que pasa— y el test
        # `test_la_recomendacion_de_sin_respaldo_sale` lo fija.
        decisiones.append(
            "SIN RESPALDO — afirmó cosas que la traza no sostiene: "
            + "; ".join(f"{a.valor} ({a.respaldo})" for a in caidas[:3]))
    c.decisiones = decisiones
    c.sostiene["decisiones"] = c.sostiene["cambios_drasticos"]

    # -- recomendaciones: reglas, no el modelo -------------------------------
    c.recomendaciones, c.sostiene["recomendaciones"] = _recomendaciones(
        c, fin, plan_objetivo)

    c.vital = not c.vacio
    return c


#: Por qué se pide el cierre en estos casos. Tres, y no una docena, porque una
#: recomendación que siempre sale es ruido: y el ruido es lo que hace que la
#: gente deje de mirar los informes.
_REGLAS_RECOMENDACION = {
    "errores": (
        "Hay {n} paso(s) en rojo. Vale la pena mirarlos antes de nada; "
        "el informe de este run los lista."),
    "sin_cerrar": (
        "El run agotó los pasos. Si el trabajo importa, hay que relanzarlo "
        "con más margen o partirlo en dos."),
    "sin_evidencia": (
        "Aegis afirmó cosas que no llegó a comprobar. Antes de dar por bueno "
        "el resultado, compruébalo tú: el informe dice cuáles."),
    "sin_tools": (
        "No se ejecutó ninguna herramienta. Si el encargo era de trabajo, "
        "no se hizo; si era una pregunta, no hace falta hacer nada."),
    "cambio_enfoque": (
        "Cambió de enfoque a mitad. Conviene saber por qué: casi siempre es "
        "que el encargo no estaba suficientemente acotado."),
}


def _recomendaciones(c: Cierre, fin: str, plan_objetivo: str
                     ) -> tuple[list[str], list[str]]:
    """Las recomendaciones, por reglas. Ver el docstring del módulo."""
    out: list[str] = []
    fuentes: list[str] = []

    if c.errores:
        out.append(_REGLAS_RECOMENDACION["errores"].format(n=len(c.errores)))
        fuentes.append("hay errores")
    if fin == "max_steps":
        out.append(_REGLAS_RECOMENDACION["sin_cerrar"])
        fuentes.append("fin=max_steps")
    if any("sin respaldo" in d for d in c.decisiones):
        out.append(_REGLAS_RECOMENDACION["sin_evidencia"])
        fuentes.append("afirmaciones sin respaldo")
    if not c.resultados and not c.errores:
        out.append(_REGLAS_RECOMENDACION["sin_tools"])
        fuentes.append("ninguna tool ejecutada")
    if any("enfoque" in d for d in c.decisiones):
        out.append(_REGLAS_RECOMENDACION["cambio_enfoque"])
        fuentes.append("cambio de enfoque")

    return out[:3], fuentes[:3]