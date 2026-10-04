"""Las lecciones de un proyecto: índice para el prompt, texto bajo demanda.

## Por qué existe esto, con la medición debajo

`lessons/{alias}.md` llegó a tener **120 KB**, y ese fichero entero se inyectaba
en el prompt de cada run. Medido el 2026-10-04, mismo encargo, n=5 cada caso:

| prompt | tool_calls | latencia en frío |
|---|---|---|
| con las lecciones enteras (127 738 chars) | 5/5 | **60,2 s** |
| sin ellas (7 672 chars) | 5/5 | **10,5 s** |

O sea: 5,7× más lento por llamada, y **el mismo número de tool_calls**. Encima se
midió el comportamiento que las lecciones describen (A-014, «no repitas la misma
llamada que ya ha fallado dos veces»): el modelo **repitió la llamada idéntica 3
de 3 con las lecciones inyectadas y 3 de 3 sin ellas**. Efecto: cero.

## Y lo que cuesta el índice, medido como toca
Comparación **intercalada** en un mismo proceso (alternando las dos variantes,
que es la única forma de comparar dos prompts en una máquina que deriva ±4 s):

| prompt | tool_calls | latencia media |
|---|---|---|
| con el índice (16 720 chars) | 5/5 | 11,9 s |
| sin lecciones (4 489 chars) | 4/5 | 10,1 s |

**+1,8 s por llamada, un 17%.** Ese es el precio real de esta decisión, y es
barato. La cifra grande era la de las 120 KB, no la del índice.

## Qué se hace entonces

No se borran: son documentación, y son las que explica por qué el código es como
es. Lo que cambia es **cuánto se le enseña al modelo**:

1. Al prompt va un **índice** con el número, el título y una frase de cuándo
   aplica. Cuesta ~2k caracteres en vez de 120 000.
2. La lección **más relevante** para el encargo va entera, porque una sola
   concreta sí cabe y es la que más puede servir.
3. El resto se pide con la tool `lecciones(alias, tema)`, que devuelve el texto
   de las que casan.

## El disparador de cada lección

Una lección puede declarar su propio criterio con una línea `> Aplica cuando: …`
justo debajo del título. Cuando no la tiene, el índice usa la primera línea de su
`**Qué pasó**: un incidente concreto que se puede reconocer, y que **no se
inventa**. Un disparador inventado es peor que ninguno: suena específico y no
sirve para nada.

## El presupuesto

`MAX_INDICE_CHARS` es un tope duro. Si un día hay 300 lecciones y el índice se
pasa, se recorta y **se dice en el propio índice** que está recortado: un índice
que miente sobre lo que contiene es peor que uno más corto.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LESSONS_DIR = Path(__file__).resolve().parent.parent / "lessons"

#: Tope del índice que va en el prompt.
#:
#: El número sale de una cuenta, no de una/linux wiki: hay 79 lecciones, y solo
#: con número y título ya salen ~4 700 caracteres. Con la frase de «qué pasó»
#: recortada, ~8 000. Y el prompt **sin** lecciones pesa 7 672. O sea: 8 000 es
#: doblar la base, no multiplicarla por 15 como estaban los 120 000.
#:
#: Y el tope sigue siendo un tope: si un día hay 300 lecciones, el índice se
#: recorta y lo dice.
MAX_INDICE_CHARS = 8000

#: Cuánto de la frase de «qué pasó» cabe en el índice. Es una pista para
#: reconocerla, no el caso completo: para eso está la tool.
CUECA_MAX_CHARS = 60

#: Cuántas lecciones enteras se inyectan sin pedir. Una: la más relevante.
MAX_INYECTADAS = 1

#: Cuántas devuelve la tool cuando pides un tema. Todas las que casen, con tope.
MAX_DEVUELTAS = 4

#: Encabezado de una lección: `## A-001 · título`.
#:
#: El prefijo admite **cualquier letra**, no solo `A`, porque los ficheros ya
#: escritos usan el prefijo de su proyecto: `### R-001` en `portafolio`. Con un
#: patrón estricto, esas 14 lecciones se escribieron, se pagaron y **nunca
#: llegaron al prompt**: `indice('portafolio')` devolvía cadena vacía, sin error
#: ni aviso. Relajar el patrón cuesta una clase de caracteres; reescribir los 14
#: encabezados perdería su historial y, además, no arreglaría el caso siguiente:
#: alguien con un prefijo raro.
#:
#: El **número** sigue siendo lo que se cita y por lo que se ordena, así que lo
#: único que cambia es que ya no se descarta una lección entera por cómo se tituló.
_HEAD = re.compile(r"^(#{2,4})\s+([A-Za-z]{1,4}-?\d+)\s*[·—–-]\s*(.+?)\s*$")
_CUE = re.compile(r"^\s*>\s*Aplica cuando:\s*(.+?)\s*$", re.IGNORECASE)
_QUE_PASO = re.compile(r"\*\*Qué pasó\*\*:\s*(.+?)(?:\n|$)", re.IGNORECASE)

#: Palabras que no distinguen una lección de otra. Una lista corta a propósito:
#:: una larga deja de ser una lista y se convierte en una opinion sobre el idioma.
_STOP = frozenset("""a al algo algunos ante antes como con cuando de del desde donde dos
el ella ellas ellos en entre era es esa ese eso esta este esto fue ha hay la las le
les lo los mas más me mi mis mucho muy nada ni no nos o os otra otras para pero por
que se ser si sin sobre solo son su sus también tanto te tiene un una uno unos y
ya yo""".split())


@dataclass
class Leccion:
    """Una lección: número, título, cuándo aplica y el texto entero."""

    numero: str
    titulo: str
    disparo: str = ""
    cuerpo: str = ""
    _cuerpo: str = field(default="", repr=False)

    @property
    def indice_linea(self) -> str:
        """La línea del índice: número, título y cuándo aplica.

        La frase se corta en `CUECA_MAX_CHARS`, y **sin puntos suspensivos**: un
        texto truncado que finge estar completo se lee como completo. Aquí lo
        delata el propio tamaño de la línea.
        """
        cuando = self.disparo or self.cue_extraido or "sin criterio declarado"
        cuando = " ".join(cuando.split())
        if len(cuando) > CUECA_MAX_CHARS:
            cuando = cuando[:CUECA_MAX_CHARS].rsplit(" ", 1)[0]
        return f"- {self.numero} · {self.titulo} · {cuando}"

    @property
    def cue_extraido(self) -> str:
        """La primera frase de su «qué pasó», si la tiene."""
        return _QUE_PASO.search(self._cuerpo).group(1).strip() if _QUE_PASO.search(self._cuerpo) else ""

    def como_texto(self) -> str:
        return f"### {self.numero} · {self.titulo}\n\n{self._cuerpo.strip()}"


def ruta(alias: str) -> Path:
    return LESSONS_DIR / f"{alias}.md"


def _partes(texto: str) -> list[Leccion]:
    """Parte el fichero en lecciones. Lo que no es lección se ignora."""
    lineas = texto.splitlines()
    libros: list[Leccion] = []
    actual: Leccion | None = None
    cuerpo: list[str] = []
    for linea in lineas:
        m = _HEAD.match(linea)
        if m:
            if actual is not None:
                actual._cuerpo = "\n".join(cuerpo).strip()
                libros.append(actual)
            actual = Leccion(numero=m.group(2), titulo=m.group(3))
            cuerpo = []
            continue
        if actual is not None:
            if (c := _CUE.match(linea)):
                actual.disparo = c.group(1)
                continue
            cuerpo.append(linea)
    if actual is not None:
        actual._cuerpo = "\n".join(cuerpo).strip()
        libros.append(actual)
    return libros


@lru_cache(maxsize=16)
def cargar(alias: str) -> tuple[Leccion, ...]:
    """Las lecciones de un proyecto. Sin fichero, ninguna — y no es un error."""
    if not alias or not _alias_valido(alias):
        return ()
    try:
        texto = ruta(alias).read_text(encoding="utf-8")
    except OSError:
        return ()
    return tuple(_partes(texto))


def _alias_valido(alias: str) -> bool:
    """Como cualquier alias que se convierta en ruta: solo un segmento."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,48}", alias or ""))


def indice(alias: str, presupuesto: int = MAX_INDICE_CHARS) -> str:
    """El índice que va al prompt. Vacío si no hay lecciones."""
    libros = cargar(alias)
    if not libros:
        return ""
    lineas: list[str] = []
    usados = 0
    recortado = 0
    for l in libros:
        linea = l.indice_linea
        if usados + len(linea) + 1 > presupuesto:
            recortado += 1
            continue
        lineas.append(linea)
        usados += len(linea) + 1
    if not lineas:
        return ""
    if recortado:
        # Se dice. Un índice que no avisa de que le falta cola parece completo.
        aviso = (f"- … y {recortado} más que no caben: pídelos con la tool "
                 f"`lecciones(alias, tema)`.")
        lineas.append(aviso)
        usados += len(aviso)
    return "\n".join(lineas)


def _tokens(texto: str) -> set[str]:
    return {p for p in re.findall(r"[\wáéíóúñü]{4,}", (texto or "").lower())
            if p not in _STOP}


def relevantes(alias: str, encargo: str, k: int = MAX_INYECTADAS) -> list[Leccion]:
    """Las lecciones que más se parecen al encargo.

    ## Cómo: palabras compartidas, sin stopwords
    Es un parecido burdo y a propósito. No «entiende» la lección: solapa
    términos con el encargo. Con un modelo de 6 GB, cualquier ranking más
    sofisticado (embeddings, un modelo encima) cuesta más de lo que aporta: lo
    que se busca no es la lección *correcta*, es una que le dé un motivo para
    mirar.
    """
    libros = cargar(alias)
    if not libros or not encargo:
        return []
    objetivo = _tokens(encargo)
    if not objetivo:
        return []
    puntuados: list[tuple[float, Leccion]] = []
    for l in libros:
        # El disparador pesa más que el cuerpo: es lo que dice cuándo aplica.
        peso = len(objetivo & _tokens(f"{l.titulo} {l.disparo}")) * 3 \
            + len(objetivo & _tokens(l._cuerpo))
        if peso:
            puntuados.append((float(peso), l))
    puntuados.sort(key=lambda t: (-t[0], t[1].numero))
    return [l for _, l in puntuados[:k]]


def cuerpo(alias: str, numeros: list[str]) -> str:
    """El texto completo de las lecciones pedidas. Es lo que devuelve la tool."""
    libros = {l.numero: l for l in cargar(alias)}
    pedidos = [n.strip().upper() for n in numeros or [] if n.strip()]
    if not pedidos:
        return ("Dime qué lección quieres: los números del índice, "
                "por ejemplo A-014. Sin esa lista no hay nada que devolver.")
    out: list[str] = []
    for n in pedidos:
        # Acepta «1», «a1» y «A-001»: la gente escribe lo primero y lo último es
        # como está en el fichero. Sin esto, pedir la lección 1 da «no existe».
        numero = n.upper().lstrip("A-").strip()
        if not numero.isdigit():
            continue
        clave = f"A-{int(numero):03d}"
        l = libros.get(clave)
        if l is None:
            continue
        out.append(l.como_texto())
    if not out:
        return (f"No hay ninguna lección con esos números en '{alias}'. "
                f"Las que hay: {', '.join(sorted(libros)) or 'ninguna'}.")
    return "\n\n---\n\n".join(out)


def por_tema(alias: str, tema: str, limite: int = MAX_DEVUELTAS) -> list[Leccion]:
    """Lecciones cuyo título o disparador casa con un tema."""
    return relevantes(alias, tema, k=limite)