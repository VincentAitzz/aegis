"""El camino rápido: peticiones que no necesitan modelo.

## Por qué existe

Medido el 2026-10-05: un run del agente tarda **~58 segundos** para «lista los
proyectos». Y la razón no es el modelo —es que **todo** pasa por él. Un run paga
**37.057 chars de prompt** antes del primer token, y hasta 16 pasos.

Pero lo que más se pide a un asistente no necesita un modelo. «¿Qué hora es?» son
**0,022 milisegundos**: `datetime.now()`. «Pon una alarma mañana» es una fila en
SQLite. Este módulo son esos caminos.

## Por qué llama a funciones y no a tools

**A propósito no se añaden intents al schema de `mcp_ops`.** El schema son
**19.083 chars que se pagan en cada paso de cada run**, y meter ahí lo que solo
sirve para el camino rápido agrandaría el prompt para todos los runs a cambio de
acelerar los que ni lo usan. `docs/motores.md` §4 proponía exponerlos al modelo;
esta es la decisión contraria, y está en `docs/decisiones/002`.

Aquí se llaman **como funciones de Python**, directas. El router no le pide
permiso al modelo para saber qué hora es: ya lo sabe.

## Y sí usa la puerta

Un intent que **escribe** pasa por `autonomy.decide()` antes de ejecutarse
(`app/autonomy.py:616`), exactamente igual que una tool. T0 no es un camino
paralelo con menos controles: es el mismo control con menos latencia. El
crear-alarma es nivel 1 y no necesita aprobación, pero el día que se suba de nivel,
esta línea lo sube también.

## La regla de oro: la abstención manda

Todo lo que no case **con certeza** se abstiene y cae al modelo. Una petición
malinterpretada es peor que una lenta, y aquí la consecuencia de equivocarse es
que Aegis haga algo que nadie pidió.

El caso que obliga a esta regla: «no me digas qué hora es» contiene exactamente
las palabras de «qué hora es». Un router que solo buscase la frase ejecutaría el
intent en una petición que **pidió lo contrario**. De ahí que los patrones sean
estrictos y de que haya tests que comprueban que el casi-fallo se abstiene.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Confianza mínima para ejecutar. Por debajo de esto, abstención.
#:
#: Está a propósito alto y solo hay dos niveles: `1.0` casa segura, `0.0`
#: abstención. Un número intermedio sería la forma de tener una regla que parece
#: matizada y no lo es — y lo que haría falta para tratarlo bien sería otro módulo.
CONFIANZA_MINIMA = 1.0

log = logging.getLogger("aegis.bridge.intents")


@dataclass
class Intent:
    """Un patrón y lo que hace cuando casa."""

    nombre: str
    #: Patrón compilado. **Debe** estar anclado y ser estrecho: casa o no casa.
    patron: re.Pattern
    #: **Puro**: de la frase a los argumentos. No escribe nada.
    #:
    #: Separado de `aplicar` por una razón que no es de estilo: la puerta tiene
    #: que ir **entre** las dos cosas. Si calcular y aplicar estuvieran juntas,
    #: el intent escribiría y luego se preguntaría al usuario si podía — y una
    #: pregunta después de escribir no es una puerta, es un informe con
    #: formato de puerta. Lo dice `AGENTS.md`: «un permiso comprobado después de
    #: la escritura es un informe, y un informe llega tarde».
    calcular: Callable[[str], dict[str, Any]]
    #: Aplica los argumentos ya autorizados y devuelve texto para hablar.
    aplicar: Callable[[dict[str, Any]], str]
    #: Si escribe, pasa por `autonomy.decide()`. Si no, es una lectura.
    escribe: bool = False
    #: Trazabilidad: la tool que el intent representa, para la traza y el veredicto.
    tool: str = ""
    #: Con qué clase se declara el camino si ejecuta.
    clase: str = "T0"
    ayuda: str = ""


@dataclass
class Plan:
    """Un intent ya resuelto y con sus argumentos. Todavía **no** ha pasado nada."""

    intent: Intent
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def escribe(self) -> bool:
        return self.intent.escribe

    @property
    def tool(self) -> str:
        return self.intent.tool


@dataclass
class Resultado:
    """Lo que devuelve el camino rápido."""

    clase: str
    texto: str
    intent: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    #: `True` cuando **no** hubo modelo de por medio. Es el dato que sostiene el
    #: presupuesto de T0, y el primer test lo comprueba.
    sin_modelo: bool = True
    ms: float = 0.0

    def como_dict(self) -> dict[str, Any]:
        return {
            "clase": self.clase, "respuesta": self.texto, "intent": self.intent,
            "tool": self.tool, "args": self.args, "sin_modelo": self.sin_modelo,
            "ms": self.ms,
        }


class _Abstencion(Exception):
    """No casa, o no lo suficiente. No es un error: es el camino normal."""


# -- fechas -------------------------------------------------------------------

_DIAS = {
    "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,
    "lun": 0, "mar": 1, "mié": 2, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6,
}

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_HORA = re.compile(r"\b(\d{1,2})\s*(?:y\s*(pts?|puntos)?|:\s*(\d{2}))?\b")
_MENOS_UN_MINUTO = 1e-9


def _hoy() -> _dt.date:
    return _dt.date.today()


def _proximo_dia_de_semana(nombre: str) -> _dt.date:
    """El próximo día de la semana a partir de hoy.

    «el lunes» dicho un martes es el lunes **que viene**, no el de esta semana que
    ya pasó. Y dicho un lunes, es el de hoy: decir «el lunes» un lunes y que suene
    la semana que viene sería absurdo.
    """
    objetivo = _DIAS[nombre]
    hoy = _hoy()
    delta = (objetivo - hoy.weekday()) % 7
    return hoy + _dt.timedelta(days=delta)


def _fecha_de_frase(frase: str) -> _dt.date:
    """La fecha de una frase, o `_Abstencion` si no hay ninguna.

    ## Por qué las horas abortan
    `agenda.tarea_crear` guarda `para` como **`YYYY-MM-DD`**: una fecha, no una
    fecha y una hora. No hay campo de hora. Un intent que aceptara «a las 7» y
    guardara solo la fecha estaría **diciendo que guardó algo que no guardó**.

    Así que aquí se aborta, y el pedido cae a T1, donde el modelo puede preguntar
    en vez de adivinar. La columna que falta es `para_hora`, y está anotada en
    `docs/decisiones/002` como el siguiente arreglo: sin ella, «a las 7» es
    media feature.
    """
    t = frase.lower().strip()

    # Una hora explícita aborta el intent entero. Tres formas de decirla, y
    # chacune estaba en un sitio distinto cuando esto se escribió:
    #   «a las 7», «las 7», «a las 19:30», «a las 7 de la mañana».
    #
    # El bug que motivó a revisar esto: la comprobación pedía además la palabra
    # «hora», así que «pon una alarma hoy a las 7» **no abortaba** y creaba la
    # alarma para hoy — exactamente el fallo que este bloque existe para evitar.
    if re.search(r"\ba\s*las?\s+\d{1,2}\b", t):
        raise _Abstencion("una hora no cabe en `para`")
    if re.search(r"\b\d{1,2}\s*(?:h|:\d{2})\b", t):
        raise _Abstencion("una hora no cabe en `para`")
    if re.search(r"\b\d{1,2}\s*(?:y\s*media|\s*medias)\b", t):
        raise _Abstencion("una hora no cabe en `para`")

    m = re.search(r"\b(?:dentro de|en)\s+(\d+)\s*(min|minuto|minutos|hora|horas|día|dias|días)\b", t)
    if m:
        n = int(m.group(1))
        unidad = m.group(2)
        if unidad.startswith("min"):
            raise _Abstencion("una alarma en minutos necesita un reloj, no una fecha")
        delta = _dt.timedelta(hours=n) if unidad.startswith("hora") else _dt.timedelta(days=n)
        return _hoy() + delta

    for clave, numero in _DIAS.items():
        if re.search(rf"\b{clave}\b", t):
            return _proximo_dia_de_semana(clave)

    m = re.search(r"\b(\d{1,2})\s*(?:de\s*)?(" + "|".join(_MESES) + r")\b", t)
    if m:
        dia, mes = int(m.group(1)), _MESES[m.group(2)]
        anio = _hoy().year
        fecha = _dt.date(anio, mes, dia)
        if fecha < _hoy():
            fecha = _dt.date(anio + 1, mes, dia)
        return fecha

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", t)
    if m:
        dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if anio < 100:
            anio += 2000
        return _dt.date(anio, mes, dia)

    if re.search(r"\bhoy\b", t):
        return _hoy()
    if re.search(r"\bmañana\b|\bmanana\b", t):
        return _hoy() + _dt.timedelta(days=1)
    if re.search(r"\bpasado\s+mañana\b", t):
        return _hoy() + _dt.timedelta(days=2)
    if re.search(r"\bpróxima\s+semana\b|\bproxima\s+semana\b", t):
        return _hoy() + _dt.timedelta(days=7)

    raise _Abstencion("no hay fecha en la frase")


# -- ejecutores ----------------------------------------------------------------
#
# Cada uno devuelve **texto para hablar**, no un objeto. La voz lee esto, y una
# persona también: la respuesta tiene que valer leída en voz alta, sin Symbolos
# raros ni listas de ids.

_HUM = ("la", "las", "un", "una", "unos", "unas")


def _sin_acentos(texto: str) -> str:
    """Quita las tildes: `qué` -> `que`.

    ## Por qué está separado y por qué no es opcional
    El TTS **no** pone tildes y el teclado **a veces**. Y `re.IGNORECASE` no
    pliega acentos: `re.I` convierte en mayúsculas, no en ASCII. Así que un
    patrón escrito con `que hora` no casa con `qué hora es`, que es la forma más
    normal de decirlo.

    Este bug estuvo aquí y se manifested como «el router no funciona» con cinco de
    seis intents rotos, mientras `dime la hora` — que no lleva tilde — sí pasaba.
    Un módulo que funciona en un caso y en otro parece que funciona en los dos.

    Se pliega a NFD y se quitan los diacríticos combinantes, que es lo único que
    funciona para `ñ`->`n` **y** para `é`, `í`, `ó`, `ú`. Escribir los patrones sin
    tilde, y no "arreglarlos" poniendo la tilde, porque el patrón tiene que casar
    con las dos formas.
    """
    import unicodedata
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _limpia(frase: str) -> str:
    """Normaliza lo que llega de la voz o del teclado para que los patrones anclen.

    Tres cosas, y las tres importan:
    1. El vocativo: «oye aegis, pon…» -> «pon…».
    2. **La interrogación inicial**: `¿qué hora es?` es lo más normal del mundo y
       si el patrón no la quita no casa nunca.
    3. **Los acentos**, por `_sin_acentos`. Ver su docstring: es el bug que hizo
       que este módulo pareciera roto.

    Y los signos sueltos de los extremos, que el TTS añade y el teclado no.
    """
    t = frase.strip()
    # El vocativo puede ir al principio o **dentro**: «oye, aegis, qué hora es».
    # Se quita en cualquier posición, no solo al principio, porque el TTS mete
    # «oye» delante de todo y el usuario escribe el nombre cuando se acostumbra.
    t = re.sub(r"\b(?:oye|ey|hola|aegis|asistente)\b[\s,.:!¡?]*", " ", t, flags=re.I)
    t = t.lstrip("¿¡ \t.,;:")
    t = t.rstrip(" \t.,;:?!¡")
    # El relleno se fue dejando huecos: «oye, lista mis tareas» deja «lista
    # mis tareas» con dos espacios. Colapsarlos aquí y no en cada patrón, porque
    # un `\s+` en el medio de un patrón ya lo tolerate pero `^\s*(?:a|b)` no
    # tolera un espacio de más **entre** la raíz y el resto.
    t = re.sub(r"\s{2,}", " ", t).strip()
    return _sin_acentos(t)


def _sin_args(frase: str) -> dict[str, Any]:
    """Los intents de lectura no tienen argumentos. Se conserva la firma para
    que todos los intents tengan la misma forma: calcular, puerta, aplicar."""
    return {}


def _dime(frase: str) -> str:
    ahora = _dt.datetime.now().astimezone()
    return ahora.strftime("%H:%M")


_MESES_INV = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
              "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_larga(fecha: _dt.date) -> str:
    """«martes 7 de octubre», en palabras. Lo lee un TTS: `2026-10-07` leído
    en voz alta suena a fichero, no a fecha."""
    dias = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
    return f"{dias[fecha.weekday()]} {fecha.day} de {_MESES_INV[fecha.month]}"


def _fecha_ahora() -> str:
    dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    hoy = _hoy()
    return f"hoy, {dias[hoy.weekday()]}"


def _dice_hora(args: dict[str, Any]) -> str:
    return f"Son las {_dime('')}."


def _dice_fecha(args: dict[str, Any]) -> str:
    return f"Hoy es {_fecha_ahora()}, y son las {_dime('')}."


#: «procede», «continua», y lo que se le parece. La lista sale de medir 500
#: prompts reales del usuario: 88 empiezan por aquí, y ninguno llegaba a ningún
#: sitio. Ver `app/plan.py`.
#: Verbos que **tienen que** valer solos. «listo», «hecho», «vamos» abren
#: frases que pueden no ser un gesto —«listo ya está, ahora abre el fichero»—
#: así que solo casan cuando no hay nada más detrás.
_SOLO_SOLO = r"(?:listo|hecho|vamos|venga|ya\s+esta|ya\s+va|siguiente)"

#: Verbos que se pueden llevar algo detrás. Son los que abren frases del tipo
#: «procede, inclúyelos pero sepáralos», que es el 50 % de las reales.
_VERBO_CONTINUAR = (
    r"procede|procedas|continua|continuar|sigue|sigamos|dale|adelante|"
    r"pasa\s+a\s+(?:implementar|hacer|ejecutar)"
)

#: Relleno que no significa nada. Si detrás del verbo solo hay esto, el gesto
#: va solo.
#: Relleno que no significa nada. Si detrás del verbo solo hay esto, el gesto
#: va solo.
#:
#: La segunda línea son **énfasis**, y están porque medidos: de 40 «procede» con
#: algo detrás, tres o cuatro no eran requisitos sino enfasis —«Procede
#: tal cual como dices», «Dale procede asi entonces», «Procede nomas rey»—. Sin
#: esta linea, Aegis reformula el plan con un requisito que dice «tal cual», que
#: es ruido que luego va a aparecer en el informe como si hubiera sido una
#: decision.
_RELLENO = (r"(?:por\s*favor|porfa|gracias|rey|"
            r"tal\s+cual|asi\s+entonces|a\s+vease|nomas|sin\s+mas|"
            r"y\s+ya\s+esta|entonces|asi|ya|ahora|"
            r"hasta\s*ahi|aqui|mas\s+o\s+menos|"
            r"como\s+dices|como\s+digas|lo\s+que\s+digas|"
            r"con\s+lo\s+que\s+sepas|lo\s+que\s+hagas|"
            r"vamos|venga|vale)")

#: El patrón, en dos alternativas porque los dos grupos de verbos no se
#: comportan igual.
#: Un solo grupo `resto`, que captura **todo** lo que va detrás del verbo —
#: incluido el relleno, que `calcular` quita después. Con dos alternativas y
#: anclos sueltos el grupo cogía un solo carácter (`.+?` es perezoso y
#: `re.match` no necesita consumir la frase entera), y los verbos sin nada
#: detrás dejaban de casar: `procede` a secas daba `resto='p'`.
_PATRON_CONTINUAR = (
    r"^\s*(?:(?:" + _VERBO_CONTINUAR + r")|(?:" + _SOLO_SOLO + r"))\b"
    r"[\s,.:!]*"
    r"(?P<resto>.*?)\s*[?.!]*\s*$"
)


def _calcula_procede(frase: str) -> dict[str, Any]:
    """Separa el gesto de continuar de lo que viene pegado.

    ## Por qué hay que separarlos
    Medido: de 88 «procede / continua / dale» reales, **44 llevan una
    restricción encima**. «Procede, los sin numero tambien incluyelos para
    manejarlos manualmente pero haz la separacion de los otros».

    Eso **no es un procede**. Es un procede con requisitos nuevos. Si se
    tratara como un procede seco, Aegis ejecutaría un plan que el usuario acaba
    de cambiar, y sería la peor respuesta posible a la frase más frecuente.

    ## La regla que salió de eso
    - gesto solo -> continuar
    - gesto + resto -> **no continuar**: hay un cambio de requisitos, y Aegis
      dice qué necesita antes de hacer nada.

    ## Y por qué el patrón no se come el resto
    El patrón ancla al principio y exige que **todo** el resto sea relleno
    («porfavor», «gracias»). En cuanto hay texto con contenido, el intent
    **abstiene**, y la abstención lo manda al modelo, que es donde una frase
    ambigua se resuelve preguntando en vez de suponiendo.
    """
    m = re.match(_PATRON_CONTINUAR, _limpia(frase), flags=re.I)
    resto = _limpia(m.group("resto") or "") if m else ""
    # El grupo `resto` incluye el relleno, así que hay que quitárselo: «procede
    # porfavor» tiene que ser un gesto solo, no un cambio de requisitos con la
    # palabra «porfavor» de requisito.
    #
    # Y hay que quitarlo **hasta que no quede**: un solo `re.sub` quita uno, y
    # «procede porfavor ahora por favor» —que es exactamente como se escribe—
    # dejaba un «ahora por favor» como requisito. `re.sub` con `+` en vez de
    # `*` solo arregla los que estén pegados, no los separados por espacios
    # sueltos que`_limpia` deja entre medias.
    # Y quitar un **verbo repetido**: «Dale procede así entonces» es un gesto
    # con énfasis, no un plan cuyo requisito sea «procede así entonces».
    resto = re.sub(rf"^(?:{_VERBO_CONTINUAR}|{_SOLO_SOLO})\b[\s,.:!]*", "",
                   resto, count=1, flags=re.I).strip()
    quitado = resto
    for _ in range(8):                    # tope: si no converge, es contenido
        antes = quitado
        quitado = re.sub(rf"^(?:{_RELLENO})\b[\s,.:!]*", "", quitado,
                         flags=re.I).strip()
        if not quitado or quitado == antes:
            break
    if not quitado.strip():
        return {"resto": "", "cambia": False}
    return {"resto": quitado.strip(), "cambia": True}


def _aplica_procede(args: dict[str, Any]) -> str:
    """Responde «procede» con lo que hay de verdad, y reformula si toca.

    ## Los dos casos, y por qué no son el mismo

    **Gesto solo** («procede», «dale»): se sigue con el plan en curso. Si no
    hay ninguno, se dice qué hay en la cola en vez de inventar que se continúa.

    **Gesto con requisitos** («procede, inclúyelos pero sepáralos»): medido,
    la mitad de los «procede» reales vienen así. Eso no es continuar, es
    **cambiar los requisitos de lo que ya se estaba haciendo**, y lo que se
    pidió fue que Aegis lo encajara por su cuenta: *«aegis debe encajar eso
    considerando en lo que esta trabajando actualmente y reformular de ser
    necesario el plan que esta ejecutandose»*.

    ## Por qué reformula y no pregunta
    Preguntar sería la respuesta prudente, y aquí sería la respuesta mala. La
    frase **ya dice** lo que quiere; volver con «¿seguro?» es gastarte el gesto de
    la persona por miedo a un error que se anota. Y el motivo queda escrito, que
    es lo que convierte esto en una decisión auditable y no en un capricho.

    ## Y si no hay nada que reformular
    Se crea un plan nuevo con ese requisito. Que se pueda decir «procede,
    quiero X» y acabe en la cola es mejor que contestarle «entendido» y no
    hacer nada: era exactamente eso lo que pasaba antes.
    """
    from .plan import Planes
    try:
        from .plan import planes as _planes
        ps = _planes()
    except Exception:                      # noqa: BLE001 — sin almacén, sin gate
        ps = Planes()

    if args.get("cambia"):
        requisito = str(args["resto"]).strip()
        actual = ps.en_curso()
        if actual:
            nuevo_objetivo = f"{actual['objetivo']} · además: {requisito}"
            ps.reformular(actual["id"], nuevo_objetivo=nuevo_objetivo,
                          motivo="requisito añadido con «procede»")
            return (f"He reformulado el plan en curso.\n"
                    f"  antes:  {actual['objetivo']}\n"
                    f"  ahora:  {nuevo_objetivo}\n"
                    f"Lo ejecuto sobre lo que ya venía haciendo, no desde cero.")

        creado = ps.crear(requisito, proyecto=actual.get("proyecto", "")
                          if actual else "")
        return (f"No había ningún plan en curso, así que he encolado esto "
                f"(prioridad {creado['prioridad']}): «{creado['objetivo']}».\n"
                f"Dime «procede» otra vez y lo tomo.")

    actual = ps.en_curso()
    if actual:
        return (f"En curso: «{actual['objetivo']}» (prioridad "
                f"{actual['prioridad']}). Sigue su curso.")

    siguiente = ps.siguiente()
    if siguiente:
        return (f"No hay nada en curso, pero tengo «{siguiente['objetivo']}» "
                f"en la cola con prioridad {siguiente['prioridad']}. "
                f"Dime «toma el siguiente» y lo tomo.")
    return ("No tengo ningún plan, así que no hay nada que continuar. "
            "Dime qué necesitas y con qué prioridad.")

def _que_puedes_hacer(args: dict[str, Any]) -> str:
    """Qué sabe hacer el sistema, dicho por el sistema.

    Sin modelo, sin tools, y —lo que importa— **sin memoria del modelo**: la
    lista sale de `app/capacidades.py`, que la deduce de las tools que existen.

    ## Por qué esto no es «un intent más»
    Porque antes de existir esto, la pregunta se contestaba de memoria: medido el
    2026-10-14, «cuentame cuales son tus funciones» tardó 161 s, no llamó a
    ninguna tool para contestarlo, **se inventó** la lista y además llamó a
    `project_create` para inventarse un proyecto. «hola, que puedes hacer?» tardó
    56 s con `fin=sin_tools` y otra lista inventada.

    Aquí se contesta en **0,02 ms** y la respuesta no puede quedar vieja, porque
    `test_toda_tool_tiene_descripcion` falla si añades una tool sin describirla.
    """
    from . import capacidades
    # `ancha=True` porque esta respuesta es para una persona, no para un prompt:
    # se pide una vez y se lee entera. No se paga en cada paso de cada run.
    return capacidades.como_texto(ancha=True)


def _lista_proyectos(args: dict[str, Any]) -> str:
    from .projects import PROJECTS
    from .workspaces import describe_workspace
    total = len(PROJECTS)
    if not total:
        return "No hay proyectos registrados todavía."
    detalle = describe_workspace().strip().splitlines()
    nombres = [l.split()[0] for l in detalle if l.strip() and not l.startswith(" ") and l.split()]
    if not nombres:
        return f"Hay {total} proyectos registrados, pero no consigo leer sus nombres."
    return f"Hay {total} proyectos: " + ", ".join(nombres) + "."


def _lista_tareas(args: dict[str, Any]) -> str:
    from .notas import agenda
    pendientes = agenda().tareas(limite=50)
    if not pendientes:
        return "No tienes tareas pendientes."
    cosas = []
    for t in pendientes[:5]:
        fecha = f" para el {t['para']}" if t.get("para") else ""
        cosas.append(f"{t['titulo']}{fecha}")
    extra = f" y {len(pendientes) - 5} más" if len(pendientes) > 5 else ""
    return f"Tienes {len(pendientes)} pendientes: " + ", ".join(cosas) + extra + "."


def _alarma_args(frase: str) -> dict[str, Any]:
    """Puro: de «pon una alarma mañana» a `{titulo, para}`. No escribe nada.

    ## Y por qué aborta si hay una hora
    `agenda.tarea_crear` guarda `para` como **`YYYY-MM-DD`**: una fecha, no una
    fecha y una hora. No hay campo de hora. Un intent que aceptara «a las 7» y
    guardara solo la fecha estaría **diciendo que guardó algo que no guardó**.

    Abstenerse aquí es lo honesto: cae a T1, donde el modelo puede preguntar en
    vez de adivinar. La columna que falta es `para_hora`, y está en
    `docs/decisiones/002` como el siguiente arreglo —sin ella, «a las 7» es media
    feature, y decir «listo» sería mentira.
    """
    limpia = _limpia(frase)
    fecha = _fecha_de_frase(limpia)
    titulo = limpia
    quitar = [r"\bponme\b", r"\bpon\b", r"\balarma\b", r"\baviso\b",
              r"\brecordatorio\b", r"\bpara\s+el\b", r"\bpara\s+la\b",
              r"\ben\b", r"\bel\b"]
    # Los dias y "hoy"/"manana" ya estan en `para`: dejarlo tambien en el titulo
    # lo duplica, y el TTS lo lee dos veces.
    quitar += [rf"\b{d}\b" for d in _DIAS]
    quitar += [r"\bhoy\b", r"\bmañana\b", r"\bmanana\b",
               r"\bpasado\s+mañana\b", r"\bpasado\s+manana\b"]
    for patron in quitar:
        titulo = re.sub(patron, " ", titulo, flags=re.I)
    # Cada palabra clave deja un hueco, y seis huecos son seis: sin colapsarlos,
    # el título sale «una     martes» y el TTS lo lee con los espacios de por
    # medio. Es el mismo motivo por el que `_limpia` los colapsa.
    titulo = re.sub(r"\s{2,}", " ", titulo).strip(" ,.:;-")
    # Lo que queda del título es relleno, no contenido: «pon una alarma
    # mañana» tras quitar las palabras clave deja «una». Se quita el artículo y
    # las preposiciones sueltas; si no queda nada, se usa un título decente.
    #
    # Sin esto el título era «una manana», que luego sale por el TTS: se oye
    # «anotado para el martes 7 de octubre: una mañana», que no dice nada.
    relleno = r"^(?:una?|unos?|unas?|los?|las?|de|del|en|para|el|la|lo)\s+"
    for _ in range(3):        # «para revisar el presupuesto»: dos de un golpe
        titulo = re.sub(relleno, "", titulo, flags=re.I).strip(" ,.:;-")
    if not titulo or titulo.lower() in ("una", "un", "el", "la", "los", "las"):
        titulo = "Alarma"
    return {"titulo": titulo, "para": fecha.isoformat(), "proyecto": ""}


def _alarma_aplicar(args: dict[str, Any]) -> str:
    """Escribe. Se llama **después** de que la puerta lo haya permitido."""
    from .notas import agenda, NotasError
    fecha = _dt.date.fromisoformat(args["para"])
    args = dict(args)
    args["id"] = ""
    try:
        creada = agenda().tarea_crear(
            titulo=args["titulo"], para=args["para"], proyecto=args.get("proyecto", ""))
    except NotasError as exc:
        raise _Abstencion(f"no pude crearla: {exc}") from exc
    return f"Anotado para el {_fecha_larga(fecha)}: {args['titulo']}."


def _nota_args(frase: str) -> dict[str, Any]:
    """Puro. Sin escribir."""
    limpia = _limpia(frase)
    cuerpo = re.sub(r"^\s*(?:anota|apunta|toma\s+nota|crea\s+una\s+nota|guarda)\b[\s:]*",
                    "", limpia, flags=re.I).strip()
    if not cuerpo:
        raise _Abstencion("la nota está vacía")
    return {"titulo": cuerpo[:200], "cuerpo": cuerpo, "proyecto": ""}


def _nota_aplicar(args: dict[str, Any]) -> str:
    """Escribe. Después de la puerta."""
    from .notas import agenda, NotasError
    try:
        creada = agenda().nota_crear(
            titulo=args["titulo"], cuerpo=args["cuerpo"],
            proyecto=args.get("proyecto", ""))
    except NotasError as exc:
        raise _Abstencion(f"no pude crearla: {exc}") from exc
    return f"Anotado: {args['cuerpo']}"


# -- el registro ---------------------------------------------------------------
#
# El orden **no** importa: cada patrón está anclado y son disjuntos. Lo que sí
# importa es que no haya dos que casen el mismo texto, porque entonces cuál gana
# sería decidido por el orden del diccionario — y eso no se puede auditar. Un test
# lo comprueba con una tabla de textos ambiguos.

def _p(patron: str) -> re.Pattern:
    return re.compile(patron, re.I)


INTENTS: list[Intent] = [
    Intent(
        "que_hora_es",
        _p(r"^\s*(?:que\s+hoy\s+es|que\s+hora\s+es|dime\s+la\s+hora"
           r"|la\s+hora(?:\s+es)?|cuanto\s+es\s+la\s+hora|hora|"
           r"dime\s+(?:que\s+hora\s+es|la\s+hora)|que\s+hora\s+hay)\s*[?.!]*\s*$"),
        _sin_args, _dice_hora, ayuda="qué hora es",
    ),
    Intent(
        # Medido el 2026-10-14 sobre 500 prompts reales: 88 empiezan por «procede»,
        # «continua» o «dale», y **ninguno llegaba a ningún sitio**. Caean a T1
        # —el modelo sin herramientas— y el modelo no tenía con qué continuar.
        #
        # El patrón exige que **todo** lo que viene detrás sea relleno. En cuanto
        # hay texto con contenido, abstain: es un cambio de requisitos, no un
        # gesto, y la respuesta correcta a eso es decir qué se necesita.
        "procede",
        _p(_PATRON_CONTINUAR),
        _calcula_procede, _aplica_procede, ayuda="procede / continua / dale",
    ),
    Intent(
        "que_dia_es",
        _p(r"^\s*(?:que\s+dia\s+es(?:\s+hoy)?|que\s+fecha\s+(?:es|hoy)|"
           r"dime\s+(?:la\s+fecha|que\s+dia\s+es)|en\s+que\s+dia\s+estamos|"
           r"que\s+dia\s+hoy)\s*[?.!]*\s*$"),
        _sin_args, _dice_fecha, ayuda="qué día es hoy",
    ),
    Intent(
        # «qué puedes hacer» es la pregunta que más se le hace a un sistema, y la
        # única cuya respuesta **es un hecho sobre el código**. Un modelo puede
        # contestarla de memoria y acertar hoy y equivocarse mañana; aquí no hay
        # nada que pueda equivocarse.
        #
        # El patrón es deliberadamente estrecho y **abstiene** ante cualquier cosa
        # que no sea la pregunta literal. «muéstrame tus herramientas» NO entra:
        # ese caso cae al modelo, que es lo correcto, porque «muéstrame» puede
        # significar «hazlo» y no «explícalo».
        "que_puedes_hacer",
        # Tres piezas, y las tres hacen falta para que case la frase **real** que
        # le dice una persona a un asistente.
        #
        #   1. lo de delante, que es de cortesía: «hola aegis, soy tu creador, »
        #   2. el verbo: pregunta directa («qué puedes hacer») o de cortesía
        #      («cuéntame un poco cuáles son tus funciones»)
        #   3. el sustantivo, que es lo que ancla el patrón: funciones,
        #      herramientas o capacidades. Sin él, «dime qué hora es» colaría.
        #
        # ## Por qué este patrón es más ancho que los demás
        # Porque **el peor caso de fallar es distinto aquí**. Si casa de más,
        # Aegis contesta con su lista cuando le preguntaron otra cosa: un susto.
        # Si casa de menos, cae al modelo —que es lo de antes—. Se ensancha
        # cuando equivocarse es un susto; los intents que **escriben** no se
        # tocan.
        #
        # ## Y lo que sigue sin entrar, a propósito
        # «muéstrame tus herramientas» cae al modelo: «muéstrame» puede querer
        # decir «hazlo». Y la cola `\s*[?.!]*\s*$` evita que «qué puedes hacer
        # por mí la cena» entre.
        _p(r"^\s*"
           # 1. la cortesía de delante. Tras el saludo puede venir otra frase
           #    suelta («hola aegis, soy tu creador, …»), así que el segundo
           #    grupo es genérico: cualquier fragmento corto acabado en coma.
           #    Sin el tope de 60 se comería un encargo entero y contestaría a
           #    algo que no se le preguntó.
           r"(?:(?:hola|hey|buenas|aegis)\b[^?!]{0,80}?[.,]\s*)*"
           r"(?:[^?!]{0,60}?[.,]\s*)*"
           # 2+3. el verbo y el sustantivo
           r"(?:"
           r"que\s+(?:puedes|sabes)\s+hacer"
           r"|para\s+que\s+sirves"
           r"|en\s+que\s+puedes\s+(?:ayudarme|ayudar)"
           r"|(?:que|cuales|cuales)\s+(?:son\s+)?(?:tus\s+|las\s+|los\s+)?"
           r"(?:funciones|herramientas|capacidades)\s+(?:tienes|haces)"
           r"|cuales?\s+(?:son\s+)?(?:tus\s+)?(?:funciones|herramientas|capacidades)"
           # «cuéntame qué puedes hacer»: el verbo de cortesía delante de una
           # pregunta directa. Faltaba y hacía que la frase cayera al modelo,
           # que es justo el caso que este intent viene a resolver.
           r"|(?:cuentame|cuéntame|dime|explicame|explícame)\s+(?:que\s+)?"
           r"(?:[^?!]{0,40}?\s+)?(?:funciones|herramientas|capacidades"
           r"|puedes\s+hacer|sabes\s+hacer)"
           r"(?:\s+(?:tienes|haces|hay))?"
           r"|(?:preséntate|presentate)"
           r")"
           # lo de detrás: más cortesía, y el cierre
           r"(?:\s*(?:un\s+poco(?:\s+mas)?|aegis|por\s+favor|gracias|ahora))*"
           r"\s*[?.!]*\s*$"),
        _sin_args, _que_puedes_hacer, ayuda="qué puedes hacer",
    ),
    Intent(
        "lista_proyectos",
        _p(r"^\s*(?:que\s+proyectos\s+(?:hay|tienes)|que\s+proyectos\s+operas"
           r"|lista(?:r)?\s+(?:los\s+)?(?:mis\s+)?proyectos"
           r"|proyectos\s+que\s+(?:hay|tienes))\s*[?.!]*\s*$"),
        _sin_args, _lista_proyectos, tool="projects_list", ayuda="qué proyectos hay",
    ),
    Intent(
        "lista_tareas",
        _p(r"^\s*(?:que\s+tareas\s+(?:hay|tengo|pendientes)|mis\s+tareas"
           r"|que\s+me\s+toca|lista(?:r)?\s+(?:mis\s+)?tareas"
           r"|que\s+pendientes\s+tengo)\s*[?.!]*\s*$"),
        _sin_args, _lista_tareas, tool="projects_list", ayuda="qué tareas tengo",
    ),
    Intent(
        "crea_alarma",
        _p(r"^\s*(?:pon|ponme|programa|agenda|acuerdate)\b.*"
           r"\b(?:alarma|aviso|recordatorio)\b"
           r"|^\s*(?:pon|ponme|programa|agenda)\b.*"
           r"\b(?:para\s+el|para\s+la|el\s|lunes|martes|miercoles|jueves|viernes"
           r"|sabado|domingo|manana|hoy)\b"),
        _alarma_args, _alarma_aplicar, escribe=True, tool="tarea_crear",
        clase="T0", ayuda="pon una alarma mañana",
    ),
    Intent(
        "crea_nota",
        _p(r"^\s*(?:anota|apunta|toma\s+nota|crea\s+una\s+nota)\b"),
        _nota_args, _nota_aplicar, escribe=True, tool="nota_crear",
        clase="T0", ayuda="anota comprar café",
    ),
]


def resolver(frase: str) -> Optional[Intent]:
    """El intent que casa con `frase`, o `None`.

    `None` **no** es un fallo: es el camino normal, y significa «esto lo lleva el
    modelo». Todo lo dudoso acaba aquí.
    """
    if not frase or not frase.strip():
        return None
    limpia = _limpia(frase)
    if not limpia:
        return None
    for intent in INTENTS:
        if intent.patron.match(limpia):
            return intent
    return None


def preparar(frase: str) -> Optional[Plan]:
    """Resuelve **y calcula**, sin escribir. El paso previo a la puerta.

    Devuelve `None` si abstain. Si el patrón casa pero la operación no se puede
    hacer —«a las 7» sin campo de hora—, también `None`: la puerta tiene que ir
    antes de cualquier efecto, y calcular no tiene ninguno.
    """
    intent = resolver(frase)
    if intent is None:
        return None
    try:
        args = intent.calcular(_limpia(frase))
    except _Abstencion:
        return None
    except Exception:  # noqa: BLE001 — un intent roto no puede tumbar la puerta
        return None
    return Plan(intent=intent, args=args)


def aplicar(plan: Plan) -> str:
    """Ejecuta un plan **ya autorizado**. Es el único sitio que escribe.

    Si alguien llama a esto sin haber pasado por `decide`, está saltándose la
    puerta. Es la razón de que sea una función aparte y no un paso dentro de
    `preparar`: que el orden sea visible en el código, y que la llamada sin
    puerta sea difícil de escribir por descuido.
    """
    return plan.intent.aplicar(plan.args)


def ejecutar(frase: str) -> Resultado:
    """Atajo **sin puerta**, solo para lecturas.

    ## Por qué existe, y por qué no debe usarse para escribir
    Es lo que usan los tests y lo que puede usar un lector. Para un intent de
    escritura **no** sirve: aplicaría sin preguntar. Por eso `aplicar` es
    separado y por eso `main.py` la usa solo tras `autonomy.decide()`.

    El caso raro —el patrón casa pero la operación no— se trata como abstención:
    caer al modelo para que pregunte, en vez de guardar media cosa y decir que la
    guardaste entera.
    """
    import time
    t0 = time.perf_counter()
    plan = preparar(frase)
    if plan is None:
        return Resultado(clase="", texto="", sin_modelo=True,
                         ms=round((time.perf_counter() - t0) * 1000, 2))
    if plan.intent.escribe:
        raise RuntimeError(
            f"ejecutar() no puede escribir el intent '{plan.intent.nombre}': "
            "pasa por main.py, que consulta autonomy.decide() antes")
    try:
        texto = aplicar(plan)
    except _Abstencion:
        return Resultado(clase="", texto="", intent=plan.intent.nombre,
                         sin_modelo=True,
                         ms=round((time.perf_counter() - t0) * 1000, 2))
    except Exception as exc:  # noqa: BLE001
        log.warning("intents %s: %s: %s", plan.intent.nombre, type(exc).__name__, exc)
        return Resultado(clase="", texto="", intent=plan.intent.nombre,
                         sin_modelo=True,
                         ms=round((time.perf_counter() - t0) * 1000, 2))
    ms = round((time.perf_counter() - t0) * 1000, 2)
    return Resultado(
        clase=plan.intent.clase, texto=str(texto), intent=plan.intent.nombre,
        tool=plan.intent.tool, args=dict(plan.args), sin_modelo=True, ms=ms,
    )
