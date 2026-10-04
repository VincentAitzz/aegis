"""Los enfoques: lo que Aegis pide para trabajar de otra manera.

## Qué es y qué no es

Un **enfoque** son las instrucciones que solo tienen sentido durante un tipo de
trabajo concreto. La idea ya está escrita y ahora toca decidir cómo se va a
construir, y esa decisión tiene que poder defenderse.

Lo que **no** es: un menú que le ofrecen a la persona. Nadie elige un enfoque
porque nadie debería tener que saber que existen. Aegis lo pide, con una tool,
cuando su encargo lo pide —y el motivo con el que lo pide queda escrito en la
traza, que es la parte que hace auditable la elección.

## Por qué un índice aparte y no solo los `.md`

Porque el `.md` es el texto y el índice es **lo que hace el texto funcional**:

- `titulo` y `resumen`: lo que la app enseña para poder «fijar» uno a mano.
- `cuando`: señales del encargo, para lo que quiera derivar sin tool.
- `restringe`: las tools que este enfoque prohíbe. **No es decoración** — lo
  cumple `decide()` en la autonomía, no el prompt.
- `presupuesto`: lo que cuesta en prompt frente a los otros, para repartir bien.

Un `.md` suelto solo puede meterse en el prompt. Con índice, el mismo enfoque puede
**cerrar puertas** y mañana **abrir tools** (`expone`), sin una línea de código
nueva.

## Por qué el presupuesto está aquí y no en el `.md`

Medido (A-016): los modelos de 6 GB dejan de emitir `tool_calls` cuando el prompt
crece, y el prompt es el presupuesto. `arquitectura.md` son ~2050 caracteres sobre
3386 de base: un +61 %. Por eso hay un **tope de enfoques activos y de caracteres
totales**, y ese número no es un gusto: si un bloque no cabe, es un método.

## Por qué quitar `idea`

Porque aterrizar una idea hasta poder escribir su ficha ya lo hace
`method_context()`, que va en todos los runs. Tenerlo además como enfoque era pagar
lo mismo dos veces: una técnica de prompt que se aplicaba siempre no es un enfoque,
es texto.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

#: Tope de caracteres de **todos** los enfoques activos a la vez. Copiado del que
#: tenía `fases.MAX_CHARS`, y por el mismo motivo: un bloque que necesita más ya no
#: es un enfoque, es un método.
MAX_CHARS = 2600

#: Tope de enfoques activos. Uno casi siempre basta; dos es para cuando la tarea
#: es legítimamente doble y el coste sigue entrando en el presupuesto.
MAX_ACTIVOS = 2

ENFOQUES_DIR = Path(__file__).resolve().parent.parent / "enfoques"
INDICE = ENFOQUES_DIR / "_indice.json"

#: Un nombre de enfoque es un identificador, no un camino. Sin esto, `../../metodo`
#: sería un enfoque válido y leería lo que hubiera en ese sitio.
_NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")

_CACHE: dict[str, str] = {}


class EnfoqueNoExiste(ValueError):
    """Un nombre de enfoque que no está en el índice. El error lista los válidos."""


def _leer_indice() -> dict[str, Any]:
    """El índice, del disco, con el error **nombrado** si está roto.

    No hay defaults silenciosos: un índice mal formado significa que Aegis no
    sabe qué enfoques hay, y que eso se entere por log y no por un `except: pass`
    que degrade el prompt sin avisar de nada.
    """
    try:
        crudo = INDICE.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnfoqueNoExiste(f"no pude leer el índice de enfoques: {exc}") from exc
    try:
        datos = json.loads(crudo)
    except ValueError as exc:
        raise EnfoqueNoExiste(
            f"el índice de enfoques no es JSON legible: {exc}. Sin él no hay "
            f"enfoques, y eso hay que verlo, no deducirlo.") from exc
    if not isinstance(datos.get("enfoques"), list):
        raise EnfoqueNoExiste("el índice de enfoques no tiene la lista 'enfoques'")
    return datos


@lru_cache(maxsize=1)
def _registro() -> dict[str, dict[str, Any]]:
    """`nombre -> ficha`, validado al cargar.

    La validación vive aquí y no en el punto de uso porque un error de índice son
    datos, y los datos se comprueban una vez: si `restringe` es una lista de lo
    que parece, descubrirlo en la fila 3 del bucle sería tarde y en un hilo.
    """
    out: dict[str, dict[str, Any]] = {}
    for crudo in _leer_indice().get("enfoques") or []:
        nombre = str(crudo.get("nombre") or "").strip()
        if not _NOMBRE.match(nombre):
            raise EnfoqueNoExiste(
                f"'{nombre}' no es un nombre de enfoque válido "
                f"(minúsculas, guion bajo, hasta 24 caracteres)")
        for campo in ("titulo", "resumen", "bloque"):
            if not str(crudo.get(campo) or "").strip():
                raise EnfoqueNoExiste(f"el enfoque '{nombre}' no declara '{campo}'")
        if not (ENFOQUES_DIR / str(crudo["bloque"])).exists():
            raise EnfoqueNoExiste(
                f"el enfoque '{nombre}' apunta a un bloque que no existe: "
                f"{crudo['bloque']}")
        ficha = dict(crudo)
        ficha["restringe"] = [str(t) for t in (crudo.get("restringe") or [])]
        ficha["expone"] = [str(t) for t in (crudo.get("expone") or [])]
        ficha["presupuesto"] = int(crudo.get("presupuesto") or 0)
        out[nombre] = ficha
    return out


def nombres() -> list[str]:
    """Qué enfoques existen. Para la UI y para poder decir «estos son»."""
    try:
        return sorted(_registro())
    except EnfoqueNoExiste:
        return []


def ficha(nombre: str) -> dict[str, Any]:
    """La ficha de un enfoque, o un error que **lista los que sí hay**.

    El error importa: un nombre mal escrito por un 7B («arquitecturas») tiene que
    producir un mensaje que le permita arreglarse solo, no un «no existe».
    """
    clave = str(nombre or "").strip()
    registro = _registro()
    if clave in registro:
        return registro[clave]
    hay = ", ".join(sorted(registro)) or "(ninguno)"
    raise EnfoqueNoExiste(
        f"no hay ningún enfoque llamado '{clave}'. Los que hay: {hay}. "
        f"Si ninguno encaja con lo que te han pedido, sigue sin ninguno: "
        f"un enfoque equivocado es peor que ninguno.")


def bloque(nombre: str) -> str:
    """El texto del enfoque, o cadena vacía si algo va mal.

    Vacía y no una excepción para el texto, pero **el registro roto sí levanta**:
    hay dos cosas distintas aquí y confundirlas es lo que volvió silencioso al
    código viejo. Un nombre equivocado lo elige (o no) el modelo; un índice roto
    es un fallo nuestro y tiene que verse.
    """
    try:
        f = ficha(nombre)
    except EnfoqueNoExiste:
        return ""
    clave = f"bloque:{nombre}"
    if clave in _CACHE:
        return _CACHE[clave]
    try:
        texto = (ENFOQUES_DIR / str(f["bloque"])).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise EnfoqueNoExiste(
            f"el enfoque '{nombre}' declara el bloque {f['bloque']} y no se puede "
            f"leer: {exc}") from exc
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS].rstrip() + "\n\n[…truncado por tamaño]"
    _CACHE[clave] = texto
    return texto


def coste(nombre: str) -> int:
    """Cuánto prompt cuesta un enfoque. Lo que se gasta al activarlo."""
    return len(bloque(nombre))


def cabe(nombre: str, ya_gastado: int) -> tuple[bool, str]:
    """¿Cabe este enfoque en lo que ya va gastado? Y si no, por qué no."""
    if nombre in ya_gastado:
        return False, f"ya estás en '{nombre}'"
    if len(ya_gastado) + 1 > MAX_ACTIVOS:
        return False, (
            f"ya llevas {len(ya_gastado)} enfoques y el tope son {MAX_ACTIVOS}. "
            f"Suelta alguno con usar_enfoque(nombre='') antes de pedir otro.")
    gastado = sum(coste(n) for n in ya_gastado)
    c = coste(nombre)
    if gastado + c > MAX_CHARS:
        return False, (
            f"'{nombre}' son {c} caracteres y ya llevas {gastado} de un máximo de "
            f"{MAX_CHARS}. El prompt es el presupuesto (A-016): meterlo entero "
            f"haría que Aegis deje de llamar herramientas. Suelta lo que llevas o "
            f"pide el encargo sin enfoque.")
    return True, ""


def restringe(nombre: str) -> list[str]:
    """Las tools que este enfoque prohíbe. Lo que `decide()` va a negar."""
    if not nombre:
        return []
    try:
        return list(ficha(nombre).get("restringe") or [])
    except EnfoqueNoExiste:
        return []


def expone(nombre: str) -> list[str]:
    """Tools extra que este enfoque abre solo durante el encargo.

    Vacío hoy en todo el registro, y está desde el principio a propósito: es la
    mitad de «otras funciones» —un enfoque puede no solo cerrar puertas, también
    abrirlas— y no quiero que abrirla sea un cambio de código.
    """
    if not nombre:
        return []
    try:
        return list(ficha(nombre).get("expone") or [])
    except EnfoqueNoExiste:
        return []


def indice_publico() -> list[dict[str, Any]]:
    """Lo que la app necesita para ofrecer «fijar» uno a mano.

    **Sin el texto del bloque.** La app enseña qué enfoques existen para poder
    elegir, no para leerlos: bajarle 2 KB de prompt al móvil que igual no se usa
    es el mismo peaje de A-016 por el otro lado: prompt de mas aqui,
    prompt de mas alla. La app solo necesita saber **que** hay.
    """
    try:
        registro = _registro()
    except EnfoqueNoExiste:
        return []
    return [
        {
            "nombre": n,
            "titulo": f["titulo"],
            "resumen": f["resumen"],
            "cuando": [str(s) for s in (f.get("cuando") or [])],
            "restringe": list(f.get("restringe") or []),
            "bloque_chars": len(bloque(n)),
        }
        for n, f in sorted(registro.items())
    ]


def derivar(encargo: str) -> Optional[tuple[str, str]]:
    """El enfoque que **sugiere** el encargo, y el motivo. O `None`.

    ## Por qué existe esto si Aegis pide el suyo con una tool
    Porque está medido que Aegis **no** lo pide solo (A-077): con `qwen2.5:7b`,
    tres runs seguidos razonaron bien y no llamaron a la tool —uno la narro en
    prosa, otro se inventó un nombre de enfoque, otro respondió en chino— y los
    tres acabaron en `fin: sin_tools`. La capacidad no era inútil: no disparaba.

    Así que la tool deja de ser el **único** camino y pasa a ser el de **corregir**:
    el bridge propone, y Aegis lo suelta con `usar_enfoque(nombre='')` o pide otro
    con su propio motivo. El de la propuesta queda escrito en la traza, que es lo
    que hace auditable una elección que no tomó una persona.

    ## Y por qué es determinista
    Un 7B que decide con reglas da siempre lo mismo, se puede probar y se puede
    leer. Preguntarle al modelo sería una inferencia más —que en esta máquina son
    minutos— por una decisión que se puede tomar mirando.

    ## Por qué devuelve **uno** y no una lista
    Dos enfoques a la vez es el tope, no el plan. Gana el que más señales tiene;
    empatados, el nombre que va antes en el índice, para que la respuesta no dependa
    del orden del diccionario. Sugerir varios y quedarse con uno sería hacer
    trabajar al modelo para descartarlos.

    `None` es la respuesta honesta cuando no hay ninguna señal: es preferible que
    Aegis pida el suyo con su propio razonamiento a que le inyectemos uno que no
    encaja. Un enfoque equivocado cuesta prompt **y** cierra tools de más.
    """
    texto = str(encargo or "").lower()
    if not texto.strip():
        return None
    try:
        registro = _registro()
    except EnfoqueNoExiste:
        return None
    mejor: Optional[tuple[int, str, str]] = None
    for nombre, f in sorted(registro.items()):
        for señal in f.get("cuando") or []:
            s = str(señal).strip().lower()
            if s and s in texto:
                # Una señal que aparece es un acierto; el nombre alfabetico es lo
                # que hace que el desempate sea reproducible.
                if mejor is None or (-1, nombre) < (-1, mejor[1]):
                    mejor = (1, nombre, s)
                break
    if mejor is None:
        return None
    return mejor[1], f"el encargo dice «{mejor[2]}»"
