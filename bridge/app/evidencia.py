"""Las afirmaciones del modelo, comprobadas contra la traza.

## La regla que extiende a A-016

El repo ya tiene una regla escrita y aplicada:

    El veredicto sale de la traza, nunca de `final_text`.

Lo que faltaba era el mismo paso un nivel mas arriba. Esa regla evita que un
**run** se contabilice como success porque el texto de despues parecia bueno.
No evita que una **frase** sePSB contada como verdad:

    "Esta en verde."   ->  no corrio `repo_verify`
    "Revise app/puerta_http.py"   ->  ese fichero no existe

Son las dos alucinaciones medidas en el trabajo de la identidad (2026-10-14),
y las dos salen de lo mismo: el modelo afirma que ha hecho una comprobacion que
nunca ocurrio. Con tools habia traza que lo delata. En conversacion no la hay,
y por eso esto comprueba **la respuesta**, no solo el run.

## Que se comprueba, y que no

Se comprueban dos clases de afirmacion, y solo dos, porque son las que se
pueden comprobar de forma determinista:

1. **Ficheros**. Una ruta que aparece en la respuesta y no aparece **en
   ningun sitio** de la traza (ni en el encargo, ni en un argumento, ni en un
   resultado) es una ruta de la que el modelo no sabe nada. Si habla de ella,
   se la invento.

2. **Verificaciones**. Una respuesta que dice que algo esta en verde, sin que
   haya corrido un verificador, es una afirmacion sin respaldo.

Lo que **no** se comprueba, a proposito: si el trabajo estaba bien hecho. Eso no
lo sabe un regex y fingir que si lleva a un sitio peor que no mirar —que es
justo lo que hacia `verificador.py` cuando creia que podia calidad con un
`tool verde`. Un `completado` con una afirmacion sin respaldo pasa a
`sin_evidencia`, que es un estado distinto y honesto, no un aprobado.

## Por que el estado nuevo baja el numero de `completado`

Porque el numero viejo era demasiado alto. Decir "46,8 % completado" cuando
una parte de esos runs afirmaba cosas que no habian pasado no es una
aproximacion: es un numero que no describe lo que cree describir. A-001 ya lo
avia avisado por el otro lado —«una verificacion en verde NO es una entrega
completa»— y aqui esta la misma idea aplicada al texto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

#: Una ruta con al menos una barra y una extension. Sin la barra, cualquier
#: palabra con punto (`config.py`, `app.run`) seria candidata y los falsos
#: positivos serian Disorder. Con barra, «app/main.py» y «bridge/app/main.py»
#: cuentan y «A-001» no.
# El cierre `(?!\w)` y no `(?![\w/.-])`, y no es un matiz: con el punto final
# dentro del conjunto, **ninguna ruta al final de una frase se encontraba**,
# porque el `.` de la frase hacia fallar el cierre. Medido: los tests de este
# modulo lo cazaron con «He revisado app/puerta_http.py.» devolviendo vacio, y
# con el mismo fallo la regla de ficheros no habria comprobado nunca nada —
# que es justo el modo de fallo que se supone que evita: una comprobacion que
# no suena nunca parece que pasa.
RUTA_RE = re.compile(
    r"""(?<![\w/.-])
    (?:[\w.-]+/)+[\w.-]+\.[A-Za-z]{1,6}
    (?!\w)""",
    re.VERBOSE,
)

#: Tools que de verdad comprueban algo. Si la respuesta afirma un verificador,
#: tiene que haber salido uno de aqui.
VERIFICADORES = frozenset({"repo_verify", "verificador"})

#: Afirmaciones de que algo se comprobó y salió bien. Deliberadamente
#: estrechas: una frase que puede significar veinte cosas no se comprueba,
#: porque un falso positivo aqui degrada un estado que era correcto.
VERDE_RE = re.compile(
    r"""(?ix)
    \b esta\ s+n?\ en\ verde
    | \b esta\ s*n?\ verde \b
    | \b todo\ s+(?:esta|va|en|queda)\ en\ verde
    | \b en\ verde \b
    | \b 0\ issues
    | \b cero\ issues
    | \b sin\ issues
    | \b el\ verificador\ s+(?:esta|va|pasa)
    | \b verificador\ en\ verde
    """
)

#: Extensiones que casi nunca son un fichero de codigo y si ruido (`1.5`, `v2`).
_NO_FICHERO = re.compile(r"^\d")


@dataclass(frozen=True)
class Afirmacion:
    """Una frase del modelo que se afirma y que se puede comprobar."""

    tipo: str          # "fichero" | "verificador"
    valor: str
    respaldo: str      # "" si está respaldada; si no, por qué no

    @property
    def sostenida(self) -> bool:
        return not self.respaldo


def rutas(texto: str) -> set[str]:
    """Las rutas que se mencionan en un texto."""
    if not texto:
        return set()
    return {m.group(0) for m in RUTA_RE.finditer(texto)
            if not _NO_FICHERO.match(m.group(0))}


def rutas_vistas(trace: Iterable[dict[str, Any]]) -> set[str]:
    """Todo lo que aparece en algún sitio de la traza, como ruta o como texto.

    Se mira **todo** el contenido, no solo los argumentos: un fichero que solo
    aparece en el resultado de una lectura tambien se ha visto. Y se miran las
    subrutas, porque un modelo puede responder con `main.py` sobre un
    `app/main.py` que si leyeron — que no es una alucinacion.
    """
    vistas: set[str] = set()
    for entrada in trace or []:
        # **La respuesta no se mira.** Es lo que hace que esto funcione: si la
        # respuesta contase como "visto", cualquier ruta que el modelo invente
        # estaria respaldada por si misma y el control no comprobaria nada.
        # Mirado por el otro lado, el fallo es real: `app/puerta_http.py` no
        # aparece en el encargo ni en ninguna tool, y aun asi sale en la
        # respuesta.
        texto = _a_texto(entrada, con_respuesta=False)
        if not texto:
            continue
        for r in rutas(texto):
            vistas.add(r)
            # `app/main.py` cubre `main.py`: el modelo puede abreviar.
            for parte in r.split("/"):
                if len(parte) > 3:
                    vistas.add(parte)
    return vistas


def _a_texto(entrada: Any, *, con_respuesta: bool = False) -> str:
    """El texto que hay dentro de una entrada de traza, sea del formato que sea.

    Los tres formatos de la traza estan en `veredicto._herramientas`, y la
    razon de mirar los tres es la misma: un run viejo y uno de ahora tienen que
    dar el mismo veredicto, o la comparacion entre ellos es mentira.
    """
    if not isinstance(entrada, dict):
        return str(entrada) if isinstance(entrada, str) else ""
    partes: list[str] = []
    claves = ["prompt", "instructions"]
    if con_respuesta:
        claves += ["answer", "final_text"]
    for clave in claves:
        v = entrada.get(clave)
        if isinstance(v, str):
            partes.append(v)
    payload = entrada.get("payload")
    for bloque in (payload, (payload or {}).get("data") if isinstance(payload, dict) else None,
                   entrada.get("tool_call"), entrada.get("args"),
                   entrada.get("arguments"), entrada.get("resultado"),
                   entrada.get("result")):
        if isinstance(bloque, dict):
            partes.extend(str(v) for v in bloque.values()
                          if isinstance(v, (str, int, float)))
        elif isinstance(bloque, str):
            partes.append(bloque)
    return "\n".join(partes)


_ESTRUCTURAL_RE = re.compile(r"^\s*(?:#{1,6}\s|>\s|[-*+]\s|\d+[.)]\s|```|~~~)")


def solo_prosa(texto: str) -> str:
    """Lo que el modelo **afirma**, quitando lo que cita o estructura.

    ## Por qué hace falta, y no es elegancia

    Medido sobre los 103 runs `completado`, la regla de verificador daba **dos**
   _caidas_ y **las dos eran falsas**:

    - `### A-001 · Una verificacion en verde NO es una entrega completa` — el
      modelo está citando la lección, y dice justo lo contrario de lo que la
      regla lee.
    - `El modelo agotó los pasos; traza real de lo ejecutado:` — un resumen de
      lo que pasó, no una afirmación sobre el estado de nada.

    Las dos son texto **estructural**: encabezado, cita, lista, bloque de
    código. Es texto que Aegis está *reproduciendo*, no *afirmando*, y una
    afirmación es lo que dice en prosa corriente dirigiéndose a quien lee.

    Por eso se quita lo que empieza por `#`, `>`, `-`, `*`, `1.` o una valla de
    código. Lo que queda es lo que el modelo le dice a la persona.

    ## Lo que esto cuesta, dicho claro

    Se pierde cobertura a propósito. Es un intercambio: el mismo texto que hace
    de manifiesto a la lección A-001 haria de manifiesto a la respuesta del
    agente que diria «esta en verde» sin comprobar. **Una comprobacion que
    necesita entender el texto no es una comprobacion**, y este modulo no
    pretende entender texto: pretende que lo que se puede leer a ojo no se
    pueda colar.
    """
    dentro = False
    fuera = []
    for linea in (texto or "").splitlines():
        if linea.strip().startswith(("```", "~~~")):
            dentro = not dentro
            continue
        if dentro or _ESTRUCTURAL_RE.match(linea):
            continue
        fuera.append(linea)
    return "\n".join(fuera)


#: Una afirmación suelta es corta. Por encima de esto ya no es «está en verde»,
#: es un informe que **contiene** la frase.
_AFIRMACION_MAX = 100


def afirma_verde(texto: str) -> bool:
    """True si el texto **afirma en prosa** que algo se comprobó y salió bien.

    ## Lo que costó decidir esto, medido

    Aplicada a los 220 runs del histórico, la versión sin más dio **3 falsos
    positivos y 0 detecciones**:

    - la lección A-001 citada («Una verificacion en verde NO es una entrega
      completa»), dos veces;
    - un indice de lecciones entero, en una linea envuelta que el filtro de
      prosa no distingue de una frase.

    Los tres dicen **lo contrario** de lo que la regla leia. Un patron que
    necesita entender la frase para no dispararse no es un patron, es una
    conjetura con mala prensa; asi que la afirmacion tiene que ser **suelta y
    corta**. Una linea de mas de 100 caracteres es un informe que contiene la
    frase, y un informe no se comprueba con un patron.

    Que tras el recorte las tres se vayan es lo que hace que esto sea una
    comprobacion y no un falso positivo mas. Y que se lleve por delante la
    cobertura queda dicho en el modulo, no escondido: sobre 220 runs, esto
    atrapa 1 caso real y habria atrapado 3 falsos si no se hubiera medido.
    """
    for linea in solo_prosa(texto).splitlines():
        limpia = linea.strip()
        if limpia and len(limpia) <= _AFIRMACION_MAX and VERDE_RE.search(limpia):
            return True
    return False


def corrrio_verificador(trace: Iterable[dict[str, Any]]) -> bool:
    """True si algún verificador llegó a correr en la traza."""
    for entrada in trace or []:
        if not isinstance(entrada, dict):
            continue
        fuente: Any = entrada
        payload = entrada.get("payload")
        if isinstance(payload, dict):
            data = payload.get("data")
            fuente = data if isinstance(data, dict) else payload
        nombre = fuente.get("tool") or entrada.get("tool")
        if isinstance(nombre, str) and nombre.strip() in VERIFICADORES:
            return True
    return False


def afirmaciones(answer: str, trace: Iterable[dict[str, Any]]) -> list[Afirmacion]:
    """Las afirmaciones de la respuesta, y si la traza las sostiene.

    Se devuelven **todas**, no solo las que caen. Saber qué se comprobaró y
    qué se es lo que hace auditable el veredicto: si dice
    «comprobado contra `app/main.py`» y no lo estaba, eso también hay que verlo.
    """
    # Solo prosa: un `app/main.py` dentro de un bloque de código o de una cita
    # es material que se reproduce, no una afirmación sobre lo que se hizo.
    respuesta = solo_prosa(answer or "")
    vistas = rutas_vistas(trace)
    salida: list[Afirmacion] = []

    for r in sorted(rutas(respuesta)):
        if r in vistas or any(r.endswith("/" + v) for v in vistas) \
                or r in vistas or any(v.endswith("/" + r) for v in vistas):
            salida.append(Afirmacion("fichero", r, ""))
        else:
            salida.append(Afirmacion(
                "fichero", r,
                "no aparece en ninguna parte de la traza: ni en el encargo, "
                "ni en un argumento, ni en un resultado"))

    if afirma_verde(respuesta):
        if corrrio_verificador(trace):
            salida.append(Afirmacion("verificador", "en verde", ""))
        else:
            salida.append(Afirmacion(
                "verificador", "en verde",
                "afirma que está en verde y no corrió ningún verificador"))

    return salida


def sin_respaldo(answer: str, trace: Iterable[dict[str, Any]]) -> list[Afirmacion]:
    """Solo las afirmaciones que la traza no sostiene."""
    return [a for a in afirmaciones(answer, trace) if not a.sostenida]


def resumen(answer: str, trace: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """El recuento, para el veredicto y para `GET /runs/{id}`."""
    todas = afirmaciones(answer, trace)
    caidas = [a for a in todas if not a.sostenida]
    return {
        "afirmaciones": len(todas),
        "sin_respaldo": len(caidas),
        "detalle": [f"{a.tipo}: {a.valor} — {a.respaldo}" for a in caidas],
        "respaldada": not caidas,
    }