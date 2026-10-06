"""Dar de alta un proyecto nuevo, y el registro que lo sostiene.

La regla del usuario es que nada se construye antes de entender para qué. Eso
tiene una consecuencia que suele olvidarse: **para poder empezar un encargo hay
que poder registrar un proyecto nuevo**, y hasta ahora eso exigía editar Python.

## Por qué la raíz no se escribe en el registro

`registro/{alias}.json` dice `alias`, `area` y `kind`. La ruta del proyecto se
DERIVA: `WORKSPACE/{area}/{alias}`, y ambas partes se validan contra la lista de
áreas y contra un patrón de alias.

La alternativa —que el JSON diga `"root": "/etc"`— habría convertido el fichero
de registro en la whitelist. Así no: el fichero declara **qué existe**, y el
código decide **dónde puede estar**. Ampliar el registro sigue ampliando la
whitelist, pero solo dentro del workspace, y solo a un sitio que se puede
revisar en un `git diff`.

## Por qué la puerta exige ficha

Un alta sin ficha deja un proyecto que Aegis no puede tocar: la puerta de
`app/fichas.py` lo va a negar en la primera escritura. Eso es lo correcto, pero
deja al usuario con un registro inútil hasta que la escriba. Por eso `alta`
devuelve la ficha ya creada desde la plantilla del tipo, con la sección de
alcance ya escrita con lo que se sabe en el alta.
"""

import json
import re
from pathlib import Path

from . import fichas
from .projects import (
    REGISTRO_DIR,
    RegistroInvalido,
    areas,
    project,
    workspace,
)

_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,48}$")
#: Nombre de carpeta en disco. Separate del alias porque los proyectos que ya
#: existen tienen mayúsculas (`Sistema-Gestor-Financiero`). Sigue siendo **un solo
#: segmento**: la whitelist no se abre, solo se puede nombrar la carpeta real.
_CARPETA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")


class AltaInvalida(ValueError):
    """El alta no se puede hacer. El mensaje dice por qué."""


def _validar(alias: str, area: str, kind: str, carpeta: str = "") -> tuple[Path, Path]:
    if not _ALIAS.match(alias or ""):
        raise AltaInvalida(
            f"alias inválido: {alias!r}. Se permiten minúsculas, dígitos, punto, "
            f"guion y guion bajo (empezando por letra o dígito)."
        )
    permitidas = areas()
    if area not in permitidas:
        raise AltaInvalida(
            f"área inválida: {area!r}. Las áreas son: {', '.join(permitidas)}."
        )
    if kind not in fichas.TIPOS:
        raise AltaInvalida(
            f"tipo inválido: {kind!r}. Los tipos son: {', '.join(fichas.TIPOS)}."
        )
    carpeta = carpeta or alias
    if not _CARPETA.match(carpeta):
        raise AltaInvalida(
            f"nombre de carpeta inválido: {carpeta!r}. Es un solo nombre de carpeta, "
            f"sin barras ni recorridos hacia arriba."
        )
    raiz = workspace()
    root = raiz / area / carpeta
    # Cinturón y tirantes: aunque las tres validaciones de arriba pasen, el
    # resultado tiene que seguir dentro del workspace.
    if not str(root.resolve()).startswith(str(raiz)):
        raise AltaInvalida("la ruta derivada se sale del workspace")
    return root, raiz


def _llenar(texto: str, seccion: str, cuerpo: str) -> str:
    """Pone contenido real bajo un encabezado de la plantilla.

    Sustituye el comentario de ayuda, que es lo único que hay ahí. Si la
    sección no aparece, no inventa nada: devuelve el texto como estaba, para que
    se note en vez de perder lo escrito.
    """
    marcas = list(re.finditer(rf"^## {re.escape(seccion)}\s*$", texto, re.M))
    if not marcas:
        return texto
    inicio = marcas[0].end()
    fin = len(texto)
    siguiente = re.search(r"^##\s+", texto[inicio:], re.M)
    if siguiente:
        fin = inicio + siguiente.start()
    return texto[:inicio] + "\n\n" + cuerpo.strip() + "\n\n" + texto[fin:]


def _verificar_de(verificar: str) -> tuple[dict, str]:
    """Parte `verificar` en (verificador, nota).

    ## Por qué dos cosas en un campo
    `verificar` nació como texto libre: una nota que decía cómo se comprueba el
    proyecto. Pero un verificador **declarado** es otra cosa —es una lista de
    comandos— y sin él `POST /autonomy/{alias}` responde 409 y el proyecto
    recién creado no puede marcado para escritura. O sea: el alta podía
    terminar en un proyecto que Aegis no podía tocar.

    ## El contrato
    Un texto que empieza por `{` se interpreta como el verificador, en JSON:
    `{"check": ["tsc --noEmit"], "test": ["vitest run"]}`. Cualquier otra cosa
    sigue siendo nota, que es como se usaba hasta aquí. Los dos valores vacíos
    se ignoran en vez de dejar `{"check": []}` en el registro.
    """
    import json as _json
    if not verificar:
        return {}, ""
    if verificar.lstrip().startswith("{"):
        try:
            datos = _json.loads(verificar)
        except ValueError:
            raise AltaInvalida(
                "verificador ilegible: empieza por '{' pero no es JSON válido. "
                'Ejemplo: {"check": ["npm test"], "test": ["npm run check"]}'
            ) from None
        if not isinstance(datos, dict):
            raise AltaInvalida("el verificador debe ser un objeto JSON con check/test")
        limpio = {str(k): [str(c) for c in v if str(c).strip()]
                  for k, v in datos.items()
                  if isinstance(v, list) and any(str(c).strip() for c in v)}
        if not limpio:
            return {}, ""
        return limpio, ""
    return {}, verificar


def alta(alias: str, area: str, kind: str, nombre: str = "",
         verificar: str = "", alcance: str = "", db: str = "",
         carpeta: str = "", ya_existe: bool = False) -> str:
    """Da de alta el proyecto: crea carpeta, ficha y entrada de registro.

    `carpeta` es el nombre en disco cuando no coincide con el alias, que es el
    caso de los proyectos que ya existen (`Sistema-Gestor-Financiero`). Con
    `ya_existe` no intenta crear el directorio: sirve para dar de alta algo que
    ya está en el workspace, que es lo normal al registrar un encargo viejo.

    `verificar` admite las dos formas que explica `_verificar_de`: un JSON de
    comandos, o una nota.
    """
    from .projects import PROJECTS
    if alias in PROJECTS:
        raise AltaInvalida(f"'{alias}' ya está registrado")
    if fichas.ficha_path(alias).exists():
        raise AltaInvalida(f"ya existe una ficha para '{alias}'")
    root, _ = _validar(alias, area, kind, carpeta)
    verificador, nota = _verificar_de(verificar)

    if not ya_existe:
        root.mkdir(parents=True, exist_ok=True)
    elif not root.is_dir():
        raise AltaInvalida(f"no existe la carpeta {root}, y pediste no crearla")

    REGISTRO_DIR.mkdir(parents=True, exist_ok=True)
    entrada = {"alias": alias, "area": area, "kind": kind}
    if carpeta and carpeta != alias:
        entrada["carpeta"] = carpeta
    if verificador:
        entrada["verify"] = verificador
    if nota:
        entrada["note"] = nota
    # `db` va **siempre**, aunque sea vacío. El contrato del registro lo exige
    # (tests/test_neon.py): un proyecto declara explícitamente qué base tiene o
    # que no se sabe. Sin esta línea, un alta nueva producía una entrada que
    # rompía ese contrato — que es como se rompen las fronteras: no haciendo
    # falta el campo que las sostiene.
    entrada["db"] = db
    (REGISTRO_DIR / f"{alias}.json").write_text(
        json.dumps(entrada, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Sin esto el proyecto recién creado quedaría fuera de la whitelist hasta el
    # siguiente reinicio, y la primera escritura en él fallaría sin explicación.
    from .projects import reload
    reload()

    # La ficha nace de la plantilla del tipo, con lo que ya sabemos escrito. La
    # puerta igual la va a negar hasta que estén las secciones de fondo: esto es
    # un punto de partida, no una ficha aprobada.
    texto = fichas.plantilla(kind)
    if nombre:
        texto = texto.replace(f"\n# Ficha · {kind}\n", f"\n# {nombre}\n", 1)
    if alcance:
        clave = "Alcance dentro" if kind == "encargo" else "Qué es"
        texto = _llenar(texto, clave, alcance)

    fichas.FICHAS_DIR.mkdir(parents=True, exist_ok=True)
    fichas.ficha_path(alias).write_text(texto, encoding="utf-8")

    # La privada se crea también, y con la plantilla **sin rellenar**: es lo que
    # Aegis no puede inventar. Sin esto, el alta dejaba al usuario sin un sitio
    # donde poner el precio y la fecha, que son justo los datos que el agente
    # tiene prohibido suponer.
    privada = fichas.crear_privada(alias)

    pendientes = fichas.read_ficha(alias).faltan()
    lineas = [
        f"Alta de '{alias}' (tipo {kind}) en {root}.",
        f"Registro: {REGISTRO_DIR / (alias + '.json')}",
        f"Ficha:    {fichas.ficha_path(alias)}",
        f"Privada:  {privada} (plantilla sin rellenar; Aegis no inventa "
        "precios ni fechas, así que lo que no escribas ahí no lo sabe)",
    ]
    if pendientes:
        lineas.append(
            "Sigue PENDIENTE en la ficha, y la puerta va a negar cualquier "
            f"escritura en este proyecto hasta que se complete: "
            + "; ".join(pendientes))
    if verificador:
        lineas.append(
            "Verificador declarado: " + "; ".join(
                f"{k}: {' '.join(v)}" for k, v in sorted(verificador.items()))
            + ". Ya se puede marcar para escritura con POST /autonomy/"
            + alias + ".")
    else:
        lineas.append(
            "SIN verificador declarado: no se puede marcar para escritura "
            f"(POST /autonomy/{alias} responde 409). Decláralo en "
            f"{REGISTRO_DIR / (alias + '.json')} con 'verify', o vuelve a "
            "darlo de alta con verificar=... en formato JSON.")
    lineas.append(
        "Mientras tanto Aegis puede LEERLO, que es lo que hace falta para "
        "entenderlo antes de escribir.")
    return "\n".join(lineas)


def _origen(alias: str) -> str:
    """De dónde viene el alias: disco o código. Disto importa para revisarlo."""
    from . import projects
    return "registro" if alias in projects._DATOS else "código"


def resumen_registro() -> str:
    """Qué proyectos puede operar Aegis y en qué estado está la ficha de cada uno.

    Antes esto solo miraba `registro/*.json`, y por eso los proyectos declarados
    en Python —compra-unida, portafolio, trazeurs— no salían nunca: tres fichas
    inexistentes que además eran invisibles para el agente. Un trabajo que no se
    ve no se hace.
    """
    from . import projects
    filas = []
    for alias in sorted(projects.PROJECTS):
        cfg = projects.PROJECTS[alias]
        ficha = fichas.read_ficha(alias)
        if not ficha.existe:
            estado = "SIN FICHA"
        elif ficha.kind not in fichas.TIPOS:
            estado = f"TIPO INVÁLIDO ({ficha.kind or 'sin declarar'})"
        elif ficha.completa:
            estado = "completa"
        else:
            estado = f"incompleta, faltan {len(ficha.faltan())}"
        verificador = ", ".join(sorted(cfg.verify)) or "SIN VERIFICADOR"
        base = cfg.db_provider or "sin base"
        filas.append(f"{alias:22} {ficha.kind or '—':12} {estado:26} "
                     f"{verificador:22} {base:12} [{_origen(alias)}]")
    encabezado = (f"{len(filas)} proyectos · registro en disco: "
                  f"{REGISTRO_DIR}")
    return "\n".join([encabezado] + filas)