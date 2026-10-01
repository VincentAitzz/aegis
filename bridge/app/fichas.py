"""La ficha de cada proyecto: qué es, cómo se trabaja en él y qué le falta.

Nace de una regla del usuario: **nada se construye antes de saber para qué**.
Para que eso no dependa de que el modelo "se acuerde", la puerta mira el disco.

## Partida en dos

- `fichas/{alias}.md`         versionada. Lo técnico: qué construye, stack,
                              verificador, alcance, criterios. Sin cliente.
- `fichas-privadas/{alias}.d` **fuera de git**. Quién es el cliente, su problema
                              en sus palabras, la banda de presupuesto, por qué
                              se descartó cada alternativa.

La razón de partirlo es que la primera es conocimiento de ingeniería, que vale
para todos y se quiere compartir. La segunda es información comercial de un
tercero: no tiene por qué viajar en un `git push`.

## La puerta

`SECCIONES_POR_TIPO` define qué tiene que estar escrito para cada tipo de
proyecto. Un encargo nuevo exige descubrimiento completo; un proyecto tuyo no
tiene que inventarse un cliente para Unlock la puerta, porque exigirle
"alternativas de cliente" a tu propia herramienta produce basura, no disciplina.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent.parent
FICHAS_DIR = BRIDGE_DIR / "fichas"
PRIVADAS_DIR = BRIDGE_DIR / "fichas-privadas"

#: Secciones que la puerta exige para cada tipo. Es lo que define "completa".
SECCIONES_POR_TIPO: dict[str, list[str]] = {
    "encargo": [
        "Qué problema resuelve",
        "Para qué se usa",
        "Quién lo usa",
        "Criterio de aceptación",
        "Alcance dentro",
        "Alcance fuera",
        "Alternativas consideradas",
        "Cómo se verifica",
    ],
    "producto": [
        "Qué es",
        "Para quién",
        "Dónde estamos",
        "Próximo paso",
        "Invariantes",
        "Cómo se verifica",
    ],
    "herramienta": [
        "Qué es",
        "Por qué existe",
        "Invariantes",
        "Cómo se verifica",
        "Qué no toca",
    ],
}

TIPOS = tuple(SECCIONES_POR_TIPO)

#: Marcadores que cuentan como "no escrito". Una plantilla recién creada no
#: puede pasar la puerta por tener los encabezados puestos.
PENDIENTE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:tbd|todo|pendiente|por (?:completar|llenar|definir)"
    r"|_pendiente_?|<pendiente>|\.\.\.|—|-{0,3})\s*$",
    re.IGNORECASE,
)

#: Bloque de comentario HTML. Puede ocupar varias líneas, y se quita entero
#: antes de decidir si la sección está escrita. Con un regex de una sola línea
#: un comentario largo contaba como contenido y la puerta se abría sola.
_COMENTARIO = re.compile(r"<!--.*?-->", re.DOTALL)

#: Una subsección `###` no rellena la sección `##` que la contiene. Si alguien
#: deja el encabezado vacío y pone todo abajo, la puerta tiene que seguir
#: diciendo que falta: si no, basta con crear un `###` para saltarse el control.
_SUBSECCION = re.compile(r"^\s{0,3}###\s", re.MULTILINE)

_FRONT = re.compile(r"^---\s*$")
_HEAD = re.compile(r"^##\s+(.+?)\s*$")


class FichaIncompleta(ValueError):
    """La puerta se negó. El mensaje dice exactamente qué falta."""


@dataclass
class Ficha:
    alias: str
    kind: str = ""
    front: dict[str, str] = field(default_factory=dict)
    secciones: dict[str, str] = field(default_factory=dict)

    @property
    def existe(self) -> bool:
        return bool(self.front or self.secciones)

    @property
    def completa(self) -> bool:
        if self.kind not in SECCIONES_POR_TIPO:
            return False
        return not self.faltan()

    def faltan(self) -> list[str]:
        """Secciones exigidas por su tipo que no están escritas de verdad."""
        if self.kind not in SECCIONES_POR_TIPO:
            return []
        return [s for s in SECCIONES_POR_TIPO[self.kind] if not _escrito(self.secciones.get(s, ""))]


def _escrito(cuerpo: str) -> bool:
    """Una sección cuenta como escrita si tiene contenido propio, no solo el encabezado.

    Se quitan enteros los comentarios (multilínea incluido) y todo lo que venga
    en subsecciones `###`. La plantilla lleva la guía en comentarios para ayudar
    a quien rellena: si eso contara, una ficha recién creada pasaría la puerta y
    la puerta no valdría nada.
    """
    limpio = _COMENTARIO.sub("", cuerpo or "")
    propio = _SUBSECCION.split(limpio, 1)[0]
    lineas = [l for l in propio.splitlines() if l.strip()]
    if not lineas:
        return False
    return not all(PENDIENTE.match(l) for l in lineas)


def ficha_path(alias: str) -> Path:
    return FICHAS_DIR / f"{alias}.md"


def privada_path(alias: str) -> Path:
    return PRIVADAS_DIR / f"{alias}.md"


def parse(alias: str, texto: str) -> Ficha:
    """Frontmatter `clave: valor` + secciones `## `. Formato propio, sin yaml."""
    lineas = texto.splitlines()
    front: dict[str, str] = {}
    secciones: dict[str, str] = {}
    i = 0
    if lineas and _FRONT.match(lineas[0]):
        i = 1
        while i < len(lineas) and not _FRONT.match(lineas[i]):
            if ":" in lineas[i]:
                k, _, v = lineas[i].partition(":")
                front[k.strip()] = v.strip().strip('"\'')
            i += 1
        i += 1
    actual = ""
    buffer: list[str] = []
    for linea in lineas[i:]:
        m = _HEAD.match(linea)
        if m:
            if actual:
                secciones[actual] = "\n".join(buffer).strip()
            actual = m.group(1).strip()
            buffer = []
        elif actual:
            buffer.append(linea)
    if actual:
        secciones[actual] = "\n".join(buffer).strip()
    return Ficha(alias=alias, kind=front.get("kind", ""), front=front, secciones=secciones)


def read_ficha(alias: str) -> Ficha:
    """La ficha del alias, o una Ficha vacía si no está. Nunca lanza."""
    path = ficha_path(alias)
    try:
        return parse(alias, path.read_text(encoding="utf-8"))
    except OSError:
        return Ficha(alias=alias)


def exige(alias: str) -> Ficha:
    """Para usar antes de escribir. Lanza `FichaIncompleta` con el motivo."""
    ficha = read_ficha(alias)
    if not ficha.existe:
        raise FichaIncompleta(
            f"el proyecto '{alias}' no tiene ficha. No se escribe nada sin saber "
            f"para qué es. Créala en bridge/fichas/{alias}.md (plantillas en "
            f"bridge/fichas/_plantilla-*.md) o lánzalo por el flujo de alta."
        )
    if ficha.kind not in SECCIONES_POR_TIPO:
        raise FichaIncompleta(
            f"la ficha de '{alias}' no declara un tipo válido (kind: "
            f"{ficha.kind or '—'}). Tipos: {', '.join(TIPOS)}. El tipo decide qué "
            f"secciones hay que escribir, así que no se puede adivinar."
        )
    faltan = ficha.faltan()
    if faltan:
        raise FichaIncompleta(
            f"la ficha de '{alias}' (tipo {ficha.kind}) está incompleta. Faltan: "
            + "; ".join(faltan)
            + f". Completa bridge/fichas/{alias}.md antes de escribir en este proyecto."
        )
    return ficha


def es_proyecto(alias: str) -> bool:
    """¿Es un alias que Aegis puede operar? Import diferido por ciclo de módulos."""
    from .projects import PROJECTS
    return alias in PROJECTS


def secciones_que_faltan(alias: str) -> tuple[str, str, list[str]]:
    """(tipo, estado legible, secciones pendientes) de un proyecto."""
    if not es_proyecto(alias):
        return "", "no es un proyecto registrado", []
    ficha = read_ficha(alias)
    if not ficha.existe:
        return "", "no tiene ficha", []
    if ficha.kind not in SECCIONES_POR_TIPO:
        return ficha.kind, f"tipo inválido ({ficha.kind or 'sin declarar'})", []
    faltan = ficha.faltan()
    if not faltan:
        return ficha.kind, "completa", []
    return ficha.kind, f"incompleta (faltan {len(faltan)})", faltan


def context_for(alias: str, *, incluir_privada: bool = True) -> str:
    """La ficha lista para inyectar en el system prompt.

    Cuando el proyecto **no tiene ficha**, no devuelve cadena vacía: devuelve el
    aviso y lo que falta. Antes devolvía "" y el agente no se enteraba ni de que
    el proyecto existía, así que no tenía por dónde empezar. Un vacío es
    indistinguible de "no hay nada que decir".

    La privada lleva datos del cliente, así que va marcada como "no la repitas":
    entra en el prompt local y no tiene por qué salir de ahí.
    """
    if not alias:
        return ""
    tipo, estado, faltan = secciones_que_faltan(alias)
    if estado.startswith("no es un proyecto"):
        return ""

    if estado == "no tiene ficha":
        exigir = SECCIONES_POR_TIPO.get(tipo) if tipo in SECCIONES_POR_TIPO else None
        partes = [
            f"EL PROYECTO '{alias}' NO TIENE FICHA. Está registrado y Aegis puede "
            f"operarlo, pero todavía no está escrito para qué sirve. No le preguntes "
            f"a tu usuario lo que se pueda deducir del repo: léelo, y pregunta solo "
            f"lo que de verdad no se puede saber.",
        ]
        if exigir is None:
            partes.append(
                "Primero hay que declararle un tipo (kind): "
                + ", ".join(TIPOS)
                + ". El tipo decide qué secciones hay que escribir, así que no se "
                "puede asumir."
            )
        else:
            partes.append("La ficha de un proyecto de tipo "
                          f"{tipo} necesita estas secciones: {', '.join(exigir)}.")
        return "\n\n".join(partes)

    ficha = read_ficha(alias)
    partes = [
        f"FICHA DEL PROYECTO '{alias}' (tipo {ficha.kind}). Esto ya está escrito: "
        "no preguntes otra vez lo que aquí ya está, y si algo no cuadra con lo que "
        "te piden, dilo antes de escribir."
    ]
    for seccion, cuerpo in ficha.secciones.items():
        if not _escrito(cuerpo):
            continue
        partes.append(f"### {seccion}\n{cuerpo}")
    if faltan:
        partes.append(
            f"PENDIENTE en esta ficha: {', '.join(faltan)}. Si la tarea necesita eso, "
            "pídelo antes de suponerlo."
        )
    if incluir_privada:
        try:
            privado = privada_path(alias).read_text(encoding="utf-8").strip()
        except OSError:
            privado = ""
        if privado:
            partes.append(
                "CONTEXTO PRIVADO (no lo nombres ni lo repitas en ninguna salida):\n"
                + privado
            )
    return "\n\n".join(partes)


def leer_para_agente(alias: str) -> str:
    """El texto de la ficha, para que el agente la lea y pueda proponer una.

    No lanza si no existe: responde diciendo que no hay ficha y qué secciones
    haría falta, porque eso es justo lo que el agente necesita para empezar.
    """
    if not alias:
        return "hace falta un alias de proyecto"
    tipo, estado, faltan = secciones_que_faltan(alias)
    if estado.startswith("no es un proyecto"):
        return f"'{alias}' no es un proyecto registrado."
    if estado == "no tiene ficha":
        exigido = (", ".join(SECCIONES_POR_TIPO[tipo])
                   if tipo in SECCIONES_POR_TIPO
                   else f"un tipo válido ({', '.join(TIPOS)})")
        return (f"El proyecto '{alias}' no tiene ficha. "
                f"Para poder escribir en él hay que crear bridge/fichas/{alias}.md "
                f"con tipo {tipo or 'sin declarar'} y estas secciones: {exigido}. "
                f"Léete el repo y propón lo derivable; pregunta lo que no se sepa.")
    try:
        crudo = ficha_path(alias).read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        return f"no pude leer la ficha de '{alias}': {exc}"
    cabecera = f"[ficha de '{alias}' · tipo {tipo} · {estado}]"
    if faltan:
        cabecera += "  FALTAN: " + "; ".join(faltan)
    return cabecera + "\n\n" + crudo


def plantilla(kind: str) -> str:
    """Esqueleto con los encabezados de su tipo, todo marcado como pendiente."""
    if kind not in SECCIONES_POR_TIPO:
        raise ValueError(f"tipo desconocido: {kind!r} (conocidos: {', '.join(TIPOS)})")
    cuerpos = {
        "encargo": {
            "Qué problema resuelve": "En las palabras de quien lo tiene.",
            "Para qué se usa": "La acción concreta que alguien hace con esto.",
            "Quién lo usa": "Roles y cantidad.",
            "Criterio de aceptación": "Cómo se sabrá que funcionó, observable.",
            "Alcance dentro": "Lo que sí entra.",
            "Alcance fuera": "Lo que no entra, explícito. Un alcance sin exclusiones es una promesa.",
            "Alternativas consideradas": "Cada opción, y por qué se descartó. Si no se miró ninguna, eso es un hallazgo.",
            "Cómo se verifica": "Comandos de verificación y qué deben dar.",
        },
        "producto": {
            "Qué es": "Una frase.",
            "Para quién": "Los usuarios reales.",
            "Dónde estamos": "Estado actual, sin adornos.",
            "Próximo paso": "Una sola cosa concreta y verificable.",
            "Invariantes": "Lo que no puede romperse.",
            "Cómo se verifica": "Comandos y qué deben dar.",
        },
        "herramienta": {
            "Qué es": "Una frase.",
            "Por qué existe": "Qué problema propio resuelve.",
            "Invariantes": "Lo que no puede romperse.",
            "Cómo se verifica": "Comandos y qué deben dar.",
            "Qué no toca": "Lo que esta herramienta deliberadamente no hace, y por qué.",
        },
    }[kind]
    lineas = [
        "---",
        "kind: " + kind,
        "---",
        "",
        f"# Ficha · {kind}",
        "",
        "> Sustituye cada línea. Una sección en blanco o con «pendiente» cuenta",
        "> como no escrita y la puerta no te deja trabajar en el proyecto.",
        "",
    ]
    for seccion in SECCIONES_POR_TIPO[kind]:
        lineas += [f"## {seccion}", "", f"<!-- {cuerpos[seccion]} -->", ""]
    return "\n".join(lineas)
