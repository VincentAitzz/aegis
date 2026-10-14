"""Bridge Aegis: la puerta unica por la que el movil habla con el agente.

## Que hay dentro y que no
Un motor, un bucle y una cola de aprobaciones. `POST /autopilot` es lo que
**ejecuta tools**; `POST /tareas` y `/notas` son agenda y no pasan por el modelo.
El WebSocket y las cuatro rutas `/tasks*` que quedan en el historial se
quitaron en la Fase 1 (`docs/motores.md` §6): eran el segundo motor, y nada los
llamaba.
"""

import asyncio
import contextlib
import json
import logging
import re
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends
from pydantic import BaseModel, Field

from . import autonomy as autonomy_modulo
from .autonomy import (MODOS, AutonomiaError, almacen as autonomy,
                       init_autonomia, medir_base)
from .autopilot import run_autopilot
from .config import get_settings
from .fichas import context_for
from .hermes_client import hermes
from .llm import ollama
from .memory import get_memory, init_memory
from .method import method_context
from .notas import init_agenda
from .notas import agenda as notas
from .telemetry import configure as configure_telemetry
from .telemetry import stopwatch, telemetry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aegis.bridge")

settings = get_settings()


# -- El anuncio en la red local ------------------------------------------------
#
# Envuelto en tres funciones para que **el lifespan se pueda ejecutar entero en
# los tests**. Enseñar un servicio real en la red durante `unittest` sería ruido
# para todo lo que hubiera en la LAN, y un `import` de `zeroconf` en el camino
# de un test que solo mide otra cosa convierte un fallo de dependencia en un
# fallo de puerta que no dice de qué.
#: Lo que anuncia el bridge por mDNS, y lo que la app usa para decidir si lo que
#: encontró es algo con lo que puede hablar.
VERSION_BRIDGE = "0.1.0"


def _anunciar() -> str:
    from .descubrimiento import registrar
    return registrar(settings.bridge_port, VERSION_BRIDGE)


def _retirar_anuncio() -> None:
    from .descubrimiento import retirar
    retirar()


def _sin_descubrimiento() -> bool:
    """Salta el anuncio. Lo usan los tests y quien no lo quiere."""
    import os
    return os.environ.get("AEGIS_SIN_DESCUBRIMIENTO") == "1"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry(settings.log_dir)
    init_memory(settings)                       # 'cerebro' del proyecto (capas 1-2)
    init_autonomia()                            # qué puede hacer sin preguntar
    init_agenda()                               # notas, tareas y recordatorios
    # Me anuncio en la red local para que el móvil me encuentre sin que nadie
    # configure una IP. Va **después** de todo lo que puede fallar, y su fallo no
    # se propaga: `registrar` devuelve el motivo en vez de lanzar, porque perder
    # el descubrimiento degrada el caso de uso pero no impide trabajar.
    #
    # El puerto sale de los settings y no de una constante: si alguien lo mueve,
    # un valor fijo anunciaría uno que no escucha y el móvil encontraría el bridge
    # para no poder hablar con él.
    if not _sin_descubrimiento():
        log.info("anuncio en la red: %s", _anunciar())
    log.info("bridge arriba (bind %s:%s -> hermes %s)",
             settings.bridge_bind, settings.bridge_port, settings.hermes_base_url)
    # Que el lifespan se ejecute en los tests HTTP es lo que permite usar
    # `with TestClient(app)`, y con eso testear `init_memory`, `init_autonomia` e
    # `init_agenda`. Por eso el cierre del cliente es explícito y reversible
    # (`hermes_client.HermesClient._client` rehace el cliente si estaba cerrado):
    # si fuese irreversible, el mismo apagón que en producción es inocuo dejaba
    # el lifespan sin ejecutar en todos los tests.
    #
    # Antes este bloque lo hacía `relay.lifespan_guard()`, que además cancelaba
    # los lectores SSE de Hermes. Esos lectores se fueron con el segundo motor
    # (Fase 1): nada los creaba desde el commit `2f1fccb`.
    try:
        yield
    finally:
        # Retirar el anuncio va con el apagado, no con el cierre del cliente: un
        # anunciante vivo después de apagar el bridge hace que alguien intente
        # conectarse a algo que ya no está. `retirar` es idempotente y no lanza,
        # así que duplicarlo con el `atexit` del propio módulo es inofensivo y
        # cubre el caso de que el proceso muera sin pasar por aquí.
        _retirar_anuncio()
        await hermes.aclose()


# `docs_url`/`redoc_url`/`openapi_url` a None: Swagger, ReDoc y el esquema
# OpenAPI son la **superficie completa de la API** —todas las rutas, sus esquemas
# y los cuerpos de petición— y por defecto se sirven **sin token**, porque FastAPI
# los monta fuera de la puerta. Aquí semeasured 200 en los tres.
#
# No es un descuido de configuración: `tests/test_puerta_http.py` recorre las
# rutas de `app.routes` para que ninguna nueva nazca abierta, y **excluía estas
# tres a propósito** (`if ruta.path.startswith(("/docs", "/openapi", "/redoc"))`),
# porque no entran en `app.routes` del mismo modo. El guardarraíl estaba escrito
# y no cubría el hueco, que es el peor sitio para que un hueco esté.
app = FastAPI(
    title="Aegis Bridge",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# -- La puerta de lo nuevo ----------------------------------------------------
#
# Los endpoints que appeared DESPUÉS de esta fecha exigen `X-Aegis-Token`. Lo
# anterior se queda abierto a propósito: cambiarlo de golpe rompería la app el
# día que la actives, y un sistema que hay que reconfigurar antes de usarlo es
# un sistema que nadie configura.
#
# Lo que hay detrás de la puerta no es lo mismo que lo que había antes: dar
# permiso de escritura sobre tus proyectos, denegar una aprobación, leer tus
# notas. Eso no es "ver una traza", es poder.

def _token_aceptado(x_aegis_token: Optional[str]) -> bool:
    """El veredicto de una clave, sin la excepción. Lo comparten el HTTP y el WS.

    Sin clave configurada, todo vale: ver la nota de `exigir_token`.

    ## Por qué `compare_digest` y no `==`
    `==` sobre `str` en CPython sale en cuanto encuentra el primer byte distinto,
    y además compara longitudes antes. Eso convierte cada 401 en un oráculo: con
    muchas peticiones midiendo el tiempo de respuesta se puede recuperar el
    token prefijo a prefijo.

    Aquí el riesgo es de manual, no de red —el ruido de una llamada HTTP real es
    mayor que la diferencia—, pero el arreglo cuesta una línea y no hay forma
    honesta de decir que no hace falta: **una comparación de secretos no es una
    comparación de secretos si depende del reloj**.

    ## Por qué el `except`
    `compare_digest` exige que las dos entradas sean `str` **ASCII**. La clave la
    elige la persona, y una con una `ñ` o un emoji legítimamente rompería el
    arranque entero con un `TypeError` en *cada* petición. Caer a `==` en ese caso
    degrada la protección, pero es una clave que nadie puede atacar por reloj si
    no es ASCII: no la puede ni escribir.
    """
    esperada = settings.aegis_api_key
    if not esperada:
        return True
    if not x_aegis_token:
        return False
    try:
        return secrets.compare_digest(x_aegis_token, esperada)
    except TypeError:
        return x_aegis_token == esperada


def exigir_token(x_aegis_token: Optional[str] = Header(default=None)) -> None:
    """Verifica `X-Aegis-Token`. Sin clave configurada, no exige nada.

    ## Por qué vacío significa abierto
    Para que la app funcione el primer día sin tener que generar un secreto. El
    día que pongas `AEGIS_API_KEY_V2` en `bridge/.env`, estos endpoints empiezan
    a exigirlo, y el móvil deja de funcionar si no lo lleva — que es el motivo
    de que el fallo sea explícito y no un 500.
    """
    if _token_aceptado(x_aegis_token):
        return
    raise HTTPException(
        status_code=401,
        detail="esta ruta pide X-Aegis-Token y la que llega no vale. "
               "El móvil la lleva en la cabecera; si acabas de rotar la "
               "clave, hay que reinstalarlo con la nueva.")


#: Lecturas que quedan abiertas **a propósito**, porque devuelven estado del
#: sistema y no trabajo tuyo.
#:
#: ## La regla, que no es «muta o no muta»
#: Cerrar solo lo que muta parecía suficiente y no lo era: `GET /autopilot/{id}`
#: devuelve tu prompt literal y los argumentos de cada tool, y `GET
#: /fichas/{alias}` devuelve la descripción del trabajo de un cliente con su
#: nombre. Ninguna de las dos cambia nada y las dos son lo que más te importa que
#: no se lea desde otro dispositivo de la tailnet.
#:
#: La regla real es: **abierto si y solo si no sale nada tuyo ni del trabajo por
#: detrás.** Y por eso esta lista es explícita: una lectura nueva nace cerrada y
#: hay que abrirla a propósito, que es distinto de tener que acordarse de
#: cerrarla. El test recorre las rutas y falla si alguna no está en la lista.
#:
#: De lo que hay aquí, ladiscussión es solo una: `/proyectos` devuelve las rutas
#: absolutas de tus repos. Es inventario, no contenido, y la app lo necesita para
#: pintar la lista antes de tener la llave.
LECTURAS_ABIERTAS = frozenset({
    "/health",        # ¿está el stack arriba? El watchdog de stack.sh depende de esto.
    "/models",        # qué modelos hay.
    "/enfoques",      # nombres de enfoques, sin su texto.
    "/actividad",     # un reloj, no un registro: a propósito en memoria.
    "/origen",        # quién tocó esto último. Sin historial.
    "/proyectos",     # inventario de alias y rutas, sin contenido de las fichas.
})


def _store_bytes() -> int:
    """Bytes que ocupa el store local de memoria (Chroma + grafo)."""
    total = 0
    for carpeta in (Path(settings.memory_dir),):
        if carpeta.is_dir():
            for f in carpeta.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
    return total


def _agents() -> dict[str, str]:
    """Aegis tiene un solo agente. `worker` es el nombre canonico.

    Antes habia tambien `orchestrator`, pero los dos valores acababan en el
    mismo modelo (Hermes usaba su default), o sea que era configuracion muerta.
    """
    return {"worker": settings.agent_worker}


async def _memory_context(prompt: str) -> str:
    """Recupera experiencias previas y las devuelve listas para inyectar."""
    mem = get_memory()
    if not mem:
        return ""
    try:
        with stopwatch() as ms:
            results = await mem.recall(prompt)
            ctx = mem.render_context(results)
        if ctx:
            telemetry.record("INFO", "memory.recall", prompt_len=len(prompt),
                             ms=round(ms(), 1), chars=len(ctx))
        return ctx
    except Exception as exc:  # noqa: BLE001 — la memoria nunca bloquea la tarea
        log.warning("recall de memoria falló: %s", exc)
        return ""


# -- health / estado ----------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    hermes_h, ollama_cap, models = await asyncio_gather_health()
    hostname = socket.gethostname()
    return {
        "status": "ok",
        "bridge": {"host": hostname, "bind": settings.bridge_bind, "port": settings.bridge_port},
        "hermes": hermes_h,
        "ollama": {"ok": ollama_cap, "models": models},
        "agents": list(_agents().keys()),
        "memory": {**(get_memory().status() if get_memory() else {}),
                   # El tamaño del store es lo que decide si el cerebro debería
                   # mudarse a Postgres. Medirlo es lo que hace que la pregunta se
                   # responda con un número y no con una corazonada.
                   "store_bytes": _store_bytes()},
    }


async def asyncio_gather_health():
    """Hermes y Ollama **a la vez**, y no uno detrás del otro.

    El nombre de la función prometía un `gather` desde el principio y no lo había:
    eran dos `await` seguidos, así que la respuesta tardaba lo que tardase la más
    lenta **sumadas**. Con la gateway caída, `/health` tardaba lo que tardase
    Hermes y encima le sumaba el tiempo de Ollama.

    Importa más de lo que parece por quién la mira: el watchdog de
    `infra/stack.sh` espera `/health` con 90 s, y el LED de la app lo consulta cada
    1,2 s. Con un `gather`, que es lo que ya hacía `/models` dos líneas más abajo,
    el LED sigue diciendo «voy bien» aunque uno de los dos esté muerto, que es
    justo lo que tiene que decir: cuál de los dos.
    """
    h, models = await asyncio.gather(hermes.health(), ollama.list_models())
    return h, True, [m.get("name") for m in models]


@app.get("/models")
async def models() -> dict:
    tags, loaded = await asyncio.gather(ollama.list_models(), ollama.loaded_models())
    return {"available": [m.get("name") for m in tags],
            "loaded": [m.get("name") for m in loaded]}


class ProyectoOut(BaseModel):
    """Un proyecto del workspace y el estado de su ficha.

    `estado` es lo que pinta el color en el móvil: `sin_ficha` en rojo,
    `parcial` en ámbar, `completa` en verde. El móvil no parsea el texto de
    `registry_list` porque eso es para personas, no para la app.
    """
    alias: str
    kind: str = ""
    root: str = ""
    area: str = ""
    estado: str = "sin_ficha"          # sin_ficha | parcial | completa
    faltan: list[str] = []
    verify: list[str] = []
    db: str = ""
    origen: str = ""                    # registro | código
    existe: bool = True


@app.get("/enfoques")
async def enfoques_listar() -> dict:
    """Qué enfoques existen, para que la app pueda ofrecer **fijar** uno.

    ## Por qué devuelven el título y el resumen, y no el texto
    La app solo necesita saber **qué hay** para pintar la línea de «trabajando
    así». Bajarle el texto entero serían ~2000 caracteres por enfoque en el móvil
    que igual no se usa nunca, y el prompt es el presupuesto en los dos
    sentidos (A-016).

    ## Y por qué la lista sale del disco
    Añadir `bridge/enfoques/x.md` más una entrada en `_indice.json` lo enciende.
    Ni Python, ni enum, ni compilar. Es lo que hace que esto se pueda ampliar a
    otras funciones sin tocar el agente.
    """
    from .enfoques import indice_publico
    return {"enfoques": indice_publico()}


class FichaIn(BaseModel):
    """El texto de una ficha ya revisado por la persona."""
    contenido: str = Field(min_length=1, max_length=20_000)


#: Tope de la ficha privada. Es más corta que la pública —es contexto comercial,
#: no documentación— pero el mismo generoso, porque lo escribe una persona desde
#: un móvil y cortar a mitad de frase no ayuda a nadie.
PRIVADA_MAX = 20_000

#: El mismo patrón de alias que valida el alta (`alta._ALIAS`). Se repite aquí
#: porque la ruta privada se deriva del alias **antes** de pasar por el alta:
#: alguien puede escribir la ficha de un proyecto que ya existe sin haber pasado
#: por allí nunca.
_ALIAS_PRIVADO = re.compile(r"^[a-z0-9][a-z0-9._-]{0,48}$")


def _ascii_corto(texto: str, tope: int = 180) -> str:
    """Un motivo que quepa en una cabecera HTTP.

    ## Por qué hay que quitarlo a mano
    Las cabeceras no son UTF-8: viajan en latin-1. Un motivo con `código` —que es
    exactamente el texto que escribe este endpoint— hace que la respuesta
    reviente con `UnicodeDecodeError` al codificarse, y el 409 se convierte en un
    500 sin motivo.

    La salida fácil —dejar el texto solo en el `detail`, que sí admite UTF-8— ya
    se probó y es la que hace que la app pierda el motivo: pregunta con `HEAD`, y
    un `HEAD` no tiene cuerpo.
    """
    limpio = texto.encode("ascii", "ignore").decode("ascii")
    return limpio[:tope]


@app.api_route("/apk/{base}", methods=["GET", "HEAD"])
async def apk_descargar(base: str,
                        _auth: None = Depends(exigir_token)) -> FileResponse:
    """El APK compilado, para que el móvil lo instale sin `adb`.

    ## Por qué también `HEAD`
    Porque la app necesita saber la versión **antes** de bajarse 50 MB. Con `GET`
    tendría que empezar la descarga para descubrir que ya tiene esa versión, y eso
    en una línea de datos es un coste que no existe: lo que hace falta son tres
    cabeceras.

    `HEAD` responde con las mismas cabeceras y el mismo código de error —un `404`
    si no hay APK, un `409` si no pasó la puerta— sin el fichero. Y por eso no es
    una ruta aparte con reglas propias: son las **mismas** dos comprobaciones. Una
    ruta `HEAD` colgando de otro sitio se desincronizaría de la que baja, y
    volvería a ofrecer una versión que el `GET` luego rechaza.

    ## Por qué esto **no** es una puerta atrás a la instalación
    Bajar un fichero no es ejecutarlo. Aquí solo se sirve el binario; lo que lo
    instala es el diálogo del sistema de Android, y lo que autoriza esa
    instalación es la cola de aprobaciones de siempre. La separación es
    deliberada: si el endpoint instalara, la invariante «nada irreversible sin
    OK» se podría saltar con una descarga.

    Lo que sí exige este endpoint es que el binario **haya pasado la puerta** —
    analyze, tests y humo en el emulador—, porque por la red un binario sin
    comprobar es un binario sin comprobar pero además distribuido.

    ## Por qué pide token, y por qué no está en `LECTURAS_ABIERTAS`
    Servir un APK firmado es lo de más consecuencia que hace el bridge: quien lo
    descarga tiene un binario que Android va a aceptar como Aegis. Abierto, eso
    es «cualquiera en la LAN se baja algo firmado de Aegis». El token no es aquí
    una formality, es lo que separa el binario de un atacante.

    ## Por qué `no-store`
    Un APK cacheado por el Wi-Fi es **instalar código viejo**, que es el peor
    desenlace posible de una actualización. Y no es un riesgo teórico: los
    intermediarios de malla cachean por defecto.

    ## Y `X-Aegis-Version`
    El `versionCode` leído del propio APK, que es el número que Android compara.
    Con eso la app decide si hay versión nueva **antes** de descargar 50 MB, y sin
    que el dato pueda discrepar del binario: sale del fichero, no de otro sitio.

    ## Y `X-Aegis-Motivo` en el 409
    El motivo va **también en una cabecera**, y no solo en el `detail` del JSON.
    Porque la app pregunta con `HEAD`, y un `HEAD` no tiene cuerpo: el `detail`
    no le llega nunca. Medido: un `409` porque el APK era más viejo que el código
    aparecía en el móvil como «el bridge no tiene un APK que servir todavía», que
    es justo lo contrario de lo que pasaba —había un APK, y lo que faltaba era
    recompilarlo—. Un motivo que se pierde no es un motivo: es ruido con pasos.
    """
    from .deploy import _huella_binario, apk_desactualizado, apk_sin_verificar
    from .deploy import sello_de
    from .dispositivos import TARGETS, apk_para, version_de
    from .deploy import PERFIL

    if base not in TARGETS:
        raise HTTPException(
            status_code=404,
            detail=f"destino desconocido: {base!r}. Los destinos son: "
                   f"{', '.join(sorted(TARGETS))}.")
    apk = apk_para(base, PERFIL)
    if not apk.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"no hay APK de '{base}' ({apk.name}). Compílalo antes: "
                   f"build_apk(target='{base}').")
    # Las dos comprobaciones que heredan de la puerta, en el mismo orden en que
    # las usa `instalar_pendiente`: primero de dónde salió el binario, después si
    # pasó las pruebas. Un APK desactualizado puede estar perfectamente
    # verificado —lo que se verificó fue *ese* fichero— y aun así no servir.
    if (motivo := apk_desactualizado(apk)):
        raise HTTPException(
            status_code=409,
            detail=f"el APK de '{base}' no representa el código de ahora: {motivo}. "
                   f"Recompílalo.",
            headers={"X-Aegis-Motivo": _ascii_corto(f"recompila: {motivo}")})
    if (motivo := apk_sin_verificar(apk)):
        raise HTTPException(
            status_code=409,
            detail=f"el APK de '{base}' no ha pasado la puerta: {motivo}",
            headers={"X-Aegis-Motivo": _ascii_corto(f"sin verificar: {motivo}")})
    code, nombre = version_de(apk)
    desde = sello_de(apk)
    respuesta = FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        headers={
            # Los dos van juntos: `no-store` evita que un caché de malla sirva un
            # binario viejo, y el `ETag` permite a la app saber que lo que tiene
            # ya es esto mismo sin volver a bajarlo.
            "Cache-Control": "no-store, must-revalidate",
            "ETag": f'"{_huella_binario(apk)}"',
            "X-Aegis-Version": str(code),
            "X-Aegis-Version-Name": nombre,
        },
    )
    if desde.is_file():
        respuesta.headers["X-Aegis-Sello"] = desde.read_text(
            encoding="utf-8").strip()[:40]
    return respuesta


@app.get("/fichas/plantillas")
async def plantillas_fichas(_auth: None = Depends(exigir_token)) -> dict:
    """Qué secciones hay que escribir, por tipo, y cuáles tiene la privada.

    ## Por qué existe
    Para que el formulario del móvil sepa qué preguntar. Las secciones viven en
    `fichas.SECCIONES_POR_TIPO`, y copiar esa lista a Dart tiene un fallo
    silencioso: el día que el bridge añada una sección, la app seguiría sin
    mostrarla, la puerta la seguiría exigiendo, y el usuario vería «incompleta»
    sin ninguna sección que la pueda completar. Un bug que no se puede
    diagnosticar desde la pantalla.

    Es el mismo criterio que los enfoques (`GET /enfoques`): el índice sale del
    disco, y ampliarlo es escribir un fichero.

    ## Y las secciones de la ficha privada
    Se leen de la plantilla, en vez de tener su propia lista en Python. Motivo
    medido: la plantilla privada **no tiene lista de secciones obligatorias** a
    propósito —el modelo de cobro no tiene forma canónica—, así que sus
    encabezados son un recordatorio. Duplicar esa lista en el código
    guarantees que algún día el formulario pregunta por una sección que la
    plantilla ya no tiene.
    """
    from . import fichas as fichas_mod

    privadas: list[str] = []
    try:
        cruda = fichas_mod.plantilla_privada()
        privada = fichas_mod.parse("_plantilla", cruda)
        # Solo las que son `##` de primer nivel, y en el orden del fichero: el
        # orden es la secuencia en la que se rellena.
        privadas = [s for s in privada.secciones]
    except Exception as exc:  # noqa: BLE001 — sin plantilla, se dice y se sigue
        return {
            "secciones": {k: list(v) for k, v in fichas_mod.SECCIONES_POR_TIPO.items()},
            "tipos": list(fichas_mod.TIPOS),
            "privada": [],
            "aviso": f"no pude leer la plantilla de la ficha privada: {exc}",
        }
    return {
        "secciones": {k: list(v) for k, v in fichas_mod.SECCIONES_POR_TIPO.items()},
        "tipos": list(fichas_mod.TIPOS),
        "privada": privadas,
    }


@app.get("/fichas/{alias}/privada")
async def leer_ficha_privada(alias: str,
                             _auth: None = Depends(exigir_token)) -> dict:
    """La ficha comercial: quién es el cliente y a qué se te compromete.

    Pide token aunque no devuelva secreto: son datos de un tercero, y la regla de
    las lecturas abiertas es «abierto si no sale nada tuyo». Un nombre, un
    teléfono y un banco son tuyos aunque no parezcan.
    """
    from . import fichas as fichas_mod
    from .projects import PROJECTS

    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no es un proyecto registrado")
    path = fichas_mod.privada_path(alias)
    try:
        texto = path.read_text(encoding="utf-8")
    except OSError:
        texto = ""
    # Sin fichero todavía se devuelve la **plantilla parseada**, no un mapa
    # vacío. Es lo que permite que el formulario del móvil se abra justo después
    # del alta, que es cuando hace falta: con un `{}` la app no tendría ni las
    # preguntas que hacer. `existe: false` sigue diciendo la verdad sobre el
    # disco, y es lo que la app usa para no fingir que hay datos escritos.
    parseada = fichas_mod.parse(alias, texto or fichas_mod.plantilla_privada())
    return {
        "alias": alias,
        "texto": texto,
        "existe": path.exists(),
        "path": str(path),
        "plantilla": str(fichas_mod.ruta_plantilla_privada()),
        # Igual que en la pública: el mapa ya parseado, para prellenar el
        # formulario. Y `escritas`, porque en la privada no hay puerta y la app
        # no puede deducirlo de `existe` —una plantilla recién creada existe y
        # no tiene nada escrito—.
        "secciones": dict(parseada.secciones),
        "escritas": [s for s, c in parseada.secciones.items()
                     if fichas_mod._escrito(c)],
    }


@app.post("/fichas/{alias}/privada")
async def escribir_ficha_privada(alias: str, body: FichaIn,
                                _auth: None = Depends(exigir_token)) -> dict:
    """Guarda la ficha comercial, sin pasar por el modelo.

    Misma decisión que `POST /fichas/{alias}`, y por el mismo motivo: la
    persona escribe el precio y la fecha en el móvil y lo manda tal cual. Un 7B
    al que se le pide copiar ese texto se come los `---` y deja la ficha rota.

    ## Lo que NO se comprueba aquí
    Que esté completa. No hay puerta sobre la ficha privada a propósito: el
    modelo de cobro no tiene forma canónica —precio cerrado, por hitos, por
    horas, a partes, o nada— y exigir un esquema fijo obligaría al usuario a
    rellenar campos que en su encargo no existen. Lo que Aegis no sepa, lo
    preguntará.
    """
    from . import fichas as fichas_mod
    from .mcp_ops import _no_secrets, _write_guarded
    from .projects import PROJECTS

    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no es un proyecto registrado")
    if len(body.contenido) > PRIVADA_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"la ficha privada admite hasta {PRIVADA_MAX} caracteres "
                   f"(van {len(body.contenido)})")

    # La ruta sale de `privada_path(alias)`, que **deriva** el nombre del alias
    # y no lo recibe. `_safe_resolve` se usaba aquí antes, pero resuelve contra
    # la raíz del repo y no contra `PRIVADAS_DIR`: en los tests escribía en el
    # directorio real, y en producción habría ignorado cualquier cambio de
    # esa ubicación. Aquí la ruta y la que lee `context_for` son la misma, que
    # es lo que hace falta para que lo que escribas llegue al prompt.
    if not _ALIAS_PRIVADO.match(alias):
        raise HTTPException(status_code=400, detail=f"alias inválido: {alias!r}")
    target = fichas_mod.privada_path(alias)
    if target.parent.resolve() != fichas_mod.PRIVADAS_DIR.resolve():
        # Cinturón y tirantes: aunque el patrón cuaje, el resultado tiene que
        # seguir dentro del directorio de las fichas privadas.
        raise HTTPException(status_code=400,
                            detail="la ruta derivada se sale del directorio privado")

    try:
        _no_secrets(body.contenido)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"contenido denegado: {exc}") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.read_text() if target.exists() else None
    ok, mensaje = _write_guarded(target, body.contenido, before)
    if not ok:
        raise HTTPException(status_code=400, detail=f"escritura RECHAZADA: {mensaje}")
    return {"alias": alias, "escrito": True, "path": str(target)}


@app.get("/fichas/{alias}")
async def leer_ficha(alias: str,
                  _auth: None = Depends(exigir_token)) -> dict:
    """La ficha de un proyecto, en texto, con su estado calculado.

    ## Por qué existe
    Para poder **escribirla** desde el móvil hay que poder leerla: la escritura
    (`POST /fichas/{alias}`) es de una persona y no pasa por el modelo, y el
    botón que la usaba vivía en una pantalla atada al motor de conversación que
    ya no está. Sin este endpoint, escribir la ficha desde el cliente era
    imposible: no había de dónde sacar el texto ni qué corregir.

    Devuelve el texto tal cual. Es el mismo documento que versiona git, sin lo
    comercial, que vive aparte (`fichas-privadas/`).
    """
    from . import fichas as fichas_mod
    from .projects import PROJECTS
    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no es un proyecto registrado")
    ficha = fichas_mod.read_ficha(alias)
    return {
        "alias": alias,
        "texto": ficha.texto,
        "kind": ficha.kind,
        "estado": "completa" if ficha.completa else ("incompleta" if ficha.existe else "sin_ficha"),
        "faltan": list(ficha.faltan()),
        # El mapa de secciones ya parseado, para que el formulario del móvil
        # pueda **prellenar** los campos. Sin esto habría que parsear markdown
        # en Dart, y `fichas._escrito` tiene reglas que no son triviales:
        # comentarios multilínea, `###` que no rellena el `##` que lo contiene,
        # y marcadores de «pendiente». Duplicarlas en Dart es la forma
        # fiable de que las dos copias acaben diciendo cosas distintas —y que
        # la puerta diga «incompleta» sobre una ficha que sí lo está.
        "secciones": dict(ficha.secciones),
        "escritas": [s for s, c in ficha.secciones.items() if fichas_mod._escrito(c)],
    }


@app.post("/fichas/{alias}")
async def escribir_ficha(alias: str, body: FichaIn,
                       _auth: None = Depends(exigir_token)) -> dict:
    """Escribe la ficha de un proyecto, **sin pasar por el modelo**.

    Existe porque la ruta por el modelo no funciona, y se comprobó: un 7B
    al que se le pide copiar un texto literal **se come los `---` del
    frontmatter**, que es lo que declara el `kind`. La ficha quedaba sin tipo y
    la puerta la rechazaba. Medido, no supuesto.

    Aquí no hay nada que el modelo pueda tocar: la persona ya revisó el texto en
    el móvil y lo manda tal cual. El modelo redacta y propone; esto es un
    guardado.

    La ruta se **deriva** de `bridge/fichas/{alias}.md`: el que llama no puede
    escribir en ningún otro sitio. Pasa por los mismos guardarraíles que
    cualquier escritura (`_safe_resolve`, secretos, reversión si no parsea).
    """
    from . import fichas as fichas_mod
    from .mcp_ops import _no_secrets, _safe_resolve, _write_guarded
    from .projects import PROJECTS

    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no es un proyecto registrado")
    try:
        # El alias es un segmento controlado por el patrón de las fichas; aun así
        # pasa por el resolutor, que es quien aplica la whitelist.
        target = _safe_resolve(f"bridge/fichas/{alias}.md")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _no_secrets(body.contenido)
    except ValueError as exc:
        # Bloqueado de verdad; lo que estaba mal era el código de respuesta:
        # un 500 esconde el motivo y hace que un rechazo correcto parezca un fallo.
        raise HTTPException(status_code=400, detail=f"contenido denegado: {exc}") from exc
    before = target.read_text() if target.exists() else None
    ok, mensaje = _write_guarded(target, body.contenido, before)
    if not ok:
        raise HTTPException(status_code=400, detail=f"escritura RECHAZADA: {mensaje}")

    ficha = fichas_mod.read_ficha(alias)
    return {
        "alias": alias,
        "escrito": True,
        "kind": ficha.kind,
        "estado": ("completa" if ficha.completa else
                   "incompleta" if ficha.existe else "sin ficha"),
        "faltan": ficha.faltan(),
        "path": str(target),
    }


#: De dónde vino la última llamada de cada origen (emulador / teléfono).
#:
#: Existe porque el emulador y el teléfono llegan los dos por `adb reverse` y
#: los dos aparecen como `127.0.0.1` en el log: sin esto no hay forma de
#: distinguir quién es quién, ni de responder a la pregunta que de verdad importa
#: —¿cuándo tocó Aegis mi teléfono?— con datos en vez de conjeturas.
_ULTIMO_ORIGEN: dict[str, float] = {}


@app.middleware("http")
async def _registrar_origen(request: Request, call_next):
    origen = request.headers.get("x-aegis-origen")
    if origen:
        _ULTIMO_ORIGEN[origen] = time.time()
    return await call_next(request)


class DeployDecision(BaseModel):
    decision: str = "aprobar"     # aprobar | denegar
    #: Solo al denegar. Sin motivo, el "no" no se puede aplicar a la siguiente
    #: situación parecida, y el puente lo dice con un 400.
    motivo: str = ""


class DeployInstalado(BaseModel):
    id: str
    estado: str          # en_curso
    detalle: str = ""


class DeployOut(BaseModel):
    id: str
    estado: str
    razon: str = ""
    lanzar: bool = False
    token: Optional[str] = None


@app.get("/deploys")
async def deploys_listar(_auth: None = Depends(exigir_token)) -> dict:
    """Despliegues esperando tu aprobación. Lo consulta el móvil.

    Mientras haya algo aquí, Aegis **no ha instalado nada** en tu teléfono: está
    esperando a que alguien lo apruebe. Eso es lo que hace que no te entere a
    posteriori.

    ## Por qué estas rutas sí exigen token
    Estaban abiertas, y la puerta protegía notas, tareas y autonomía pero no los
    despliegues. Eso es incoherente por partida doble: el comentario de arriba
    decía que la puerta cubría «dar permiso de escritura sobre tus proyectos y
    denegar una aprobación», y aprobar un despliegue es exactamente eso.

    Con `POST /deploys/{id}/instalar` el agujero era de ventaja
    real: cualquiera que alcanzara el bridge en la tailnet —cualquier
    dispositivo tuyo, o el de cualquiera que se conecte a la malla— podía leer
    los ids pendientes, aprobarlos y disparar una instalación. La puerta no
    protegía lo único que no se puede deshacer.

    El móvil ya lleva el token: en la cabecera HTTP de Dart y en `BuildConfig`
    para el overlay nativo. No rompe a la app, y cierra la vía.
    """
    from .deploy import snapshot
    return snapshot()


@app.post("/deploys/{pet_id}", response_model=DeployOut)
async def deploy_aprobar(
    pet_id: str,
    body: DeployDecision,
    _auth: None = Depends(exigir_token),
) -> DeployOut:
    """Aprueba o deniega una instalación pendiente.

    Aprobar devuelve un **token de un solo uso**: sirve para una instalación y
    se gasta. No es una autorización permanente.

    ## Y para que sirva de algo, está `POST /deploys/{id}/instalar`
    Aprobar sin instalar es medio gesto. Quien aprueba desde el móvil (el cuadro
    superpuesto) encadena las dos: el token se gasta **dentro del bridge** y no
    sale hacia el agente, que es lo único que hace que "instalar en segundo
    plano" sea verdad y no un trámite que el agente se entere.
    """
    from .deploy import aprobar, PuertaCerrada
    try:
        r = aprobar(pet_id, body.decision, body.motivo)
    except PuertaCerrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    p = pendientes_por_id(pet_id)
    return DeployOut(id=pet_id, estado=r["estado"], razon=p.get("razon", ""),
                     lanzar=bool(p.get("lanzar")), token=r.get("token"))


@app.post("/deploys/{pet_id}/instalar", response_model=DeployInstalado)
async def deploy_instalar(
    pet_id: str,
    _auth: None = Depends(exigir_token),
) -> DeployInstalado:
    """Instala un despliegue ya aprobado, sin que pase por el agente.

    Devuelve **de inmediato**: la instalación va en un hilo aparte, porque
    `install` por adb tarda y el móvil está esperando con el dedo puesto. El
    resultado se ve en el aviso que sale cuando termina.

    Si se bloqueara la respuesta, pulsar "sí" se sentiría como la app colgada, y
    quien aprueba desde el móvil no tiene a nadie a quien preguntarle qué pasó.

    ## Y el aviso lleva las tres fases
    Antes solo se avisaba del **final**. El aviso decía «necesito tu OK», tú
    aprobabas, y el aviso desaparecía: se había aprobado *tu* parte, no la de
    Aegis, y durante el trabajo no había nada. Ahora es el mismo aviso pasando de
    «necesito tu OK» a «en marcha» y a «instalado», que es lo que hace que la
    bandeja no se quede muda justo en la parte que espera (A-069).
    """
    from .deploy import (avisar_fallo_telefono, avisar_trabajando,
                         instalar_pendiente, PuertaCerrada)

    def _correr() -> None:
        avisar_trabajando(pet_id, "instalando la app en tu teléfono")
        try:
            detalle = instalar_pendiente(pet_id)
            log.info("instalación en segundo plano de %s: %s", pet_id, detalle)
        except PuertaCerrada as exc:
            # La puerta se cerró con un motivo. Sin este aviso el usuario pulsó
            # "sí", la app dijo "se instala" y no vuelve a saber nada: el peor
            # final posible para un gesto que se hizo a distancia.
            log.warning("instalación en segundo plano de %s: %s", pet_id, exc)
            avisar_fallo_telefono(pet_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — un hilo no puede propagar
            log.exception("instalación en segundo plano de %s", pet_id)
            avisar_fallo_telefono(pet_id, f"fallo inesperado: {exc}")
        # El éxito **no** se avisa aquí: lo avisa `instalar_en_telefono`, que es
        # quien sabe que `adb install` salió bien. Avisarlo también desde aquí
        # publicaría dos veces y la segunda podría llegar antes que la primera.

    # `run_in_executor`: tanto la puerta como `adb install` son llamadas
    # bloqueantes. En el bucle de eventos pararían el WebSocket de telemetría
    # durante la instalación entera.
    asyncio.get_running_loop().run_in_executor(None, _correr)

    return DeployInstalado(
        id=pet_id, estado="en_curso",
        detalle="la instalación arranca ya; el aviso del móvil confirma al terminar",
    )



def pendientes_por_id(pet_id: str) -> dict:
    from .deploy import ESTADO
    return ESTADO.peticion(pet_id)


@app.get("/actividad")
async def actividad() -> dict:
    """¿Está Aegis hablando ahora mismo?

    Lo consume el glifo de la app: **celeste en reposo, magenta hablando**. Y de
    paso arregla el LED de la cabecera, que hasta ahora no tenía nada que
    consultar: `healthProvider` no se sondea, se leía al arrancar y al tocar el
    banner, así que «en línea» era verdad solo si el puente seguía vivo en ese
    instante y durante los diez segundos siguientes.

    ## Por qué no se devuelve un «hay un run en marcha»
    Porque un run puede estar pensando treinta segundos antes de decir nada. Con
    esa señal, el glifo se pondría magenta durante el silencio y estaría
    mintiendo —que es lo que hace un indicador que no significa lo que dice.
    Aquí se marca cuando **llega texto**, y se apaga a los 2,5 s de callar.
    Ver `app/actividad.py`.
    """
    from . import actividad as _act
    return _act.estado()


@app.get("/origen")
async def origen() -> dict:
    """Última llamada de cada origen, para que se vea quién tocó qué."""
    return {"ultimo": _ULTIMO_ORIGEN, "ahora": time.time()}


# `_hubo_llamada_de` se borro de aqui en la Fase 1. Estaba sin un solo llamador y
# con una copia **viva** en `deploy.py:134`, que hace lo mismo consultando `/origen`
# por HTTP en vez de leyendo `_ULTIMO_ORIGEN` en memoria (el motivo esta en su
# docstring: el MCP corre como proceso aparte).
#
# Lo que mas caro sale no es la duplicacion, es la **docstring que mentia**: la de
# aqui decia "lo usa el humo del emulador", y el humo usaba la de `deploy.py`. Un
# nombre en dos ficheros con dos cuerpos es un bug esperando —el proximo que lea
# uno y lo toque creera que toca el otro— y su docstring desde el otro lado
# garantiza que no se note hasta que las dos cosas den resultados distintos.


@app.get("/proyectos")
async def proyectos() -> dict:
    """Los proyectos que Aegis puede operar, con lo que a cada uno le falta.

    Responde a la pregunta que el móvil necesita para pintar el selector: no
    solo qué hay, sino **en qué estado está cada ficha**, porque un proyecto sin
    ficha y uno completo se trabajan de forma distinta.
    """
    from .fichas import secciones_que_faltan
    from .projects import PROJECTS
    out: list[ProyectoOut] = []
    for alias in sorted(PROJECTS):
        cfg = PROJECTS[alias]
        tipo, legible, faltan = secciones_que_faltan(alias)
        if legible == "completa":
            estado = "completa"
        elif legible == "no tiene ficha":
            estado = "sin_ficha"
        else:
            estado = "parcial"
        partes = Path(cfg.root).relative_to(Path(settings.workspace_dir)).parts \
            if str(cfg.root).startswith(str(settings.workspace_dir)) else ()
        out.append(ProyectoOut(
            alias=alias,
            kind=tipo or cfg_note_kind(alias),
            root=str(cfg.root),
            area=partes[0] if partes else "",
            estado=estado,
            faltan=list(faltan),
            verify=sorted(cfg.verify),
            db=cfg.db_provider,
            origen="registro" if alias in PROJECTS_DATOS() else "código",
            existe=Path(cfg.root).is_dir(),
        ))
    return {"proyectos": [p.model_dump() for p in out]}


class ProyectoAltaIn(BaseModel):
    """Lo mínimo para dar de alta un proyecto desde el móvil.

    El campo `verificar` es texto a propósito y no dos listas: el verificador
    del registro es una lista de comandos, pero en un proyecto recién abierto lo
    primero es una **nota** de cómo se comprueba, y forcing formato JSON en el
    primer alta de un encargo es una puerta que se recuerda como molesta.
    `alta._verificar_de` distingue las dos formas por el `{` inicial.
    """
    alias: str = Field(min_length=1, max_length=49)
    area: str = Field(min_length=1, max_length=32)
    kind: str = Field(min_length=1, max_length=16)
    nombre: str = Field(default="", max_length=200)
    alcance: str = Field(default="", max_length=4_000)
    verificar: str = Field(default="", max_length=4_000)
    db: str = Field(default="", max_length=64)
    carpeta: str = Field(default="", max_length=64)
    ya_existe: bool = False


class AltaOut(BaseModel):
    """Lo que devuelve el alta: qué se creó y qué queda pendiente.

    `faltan` viene de la puerta, no de la plantilla. Un alta nunca deja la ficha
    completa —el usuario tiene que escribir lo que sabe—, y decir eso con los
    nombres exactos de las secciones es lo que permite al móvil pintar «te faltan
    estas tres» en vez de «se creó».
    """
    alias: str
    tipo: str = ""
    estado: str = ""
    faltan: list[str] = []
    mensaje: str = ""


@app.post("/proyectos", response_model=AltaOut)
async def proyecto_alta(body: ProyectoAltaIn,
                        _auth: None = Depends(exigir_token)) -> AltaOut:
    """Da de alta un proyecto: carpeta, registro, ficha pública y ficha privada.

    ## Por qué hace falta esto
    `project_create` ya existía como tool del agente, pero solo se llega desde un
    run de autopilot, y ese camino obliga a pasar por el modelo para escribir un
    alta que es enteramente determinista: una carpeta, un JSON y dos ficheros de
    texto. El alta es de la persona, no del agente, y por eso va directa.

    ## Por qué pide token
    Registra un proyecto, y con eso Aegis puede escribir en un directorio nuevo
    del workspace. Es la misma clase de acción que `POST /autonomy/{alias}`,
    que también pide token.

    Lo que **no** hace es dar permiso de escritura: eso sigue siendo
    `POST /autonomy/{alias}`, y sigue exigiendo verificador declarado.
    """
    from .alta import AltaInvalida, alta

    try:
        mensaje = alta(
            alias=body.alias,
            area=body.area,
            kind=body.kind,
            nombre=body.nombre.strip(),
            alcance=body.alcance.strip(),
            verificar=body.verificar.strip(),
            db=body.db.strip(),
            carpeta=body.carpeta.strip(),
            ya_existe=body.ya_existe,
        )
    except AltaInvalida as exc:
        # 422 lo convierte el propio FastAPI, pero el motivo de `AltaInvalida`
        # está escrito para una persona: es más útil que un error de validación
        # genérico.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from .fichas import secciones_que_faltan
    tipo, legible, faltan = secciones_que_faltan(body.alias)
    return AltaOut(
        alias=body.alias,
        tipo=tipo,
        estado=legible,
        faltan=list(faltan),
        mensaje=mensaje,
    )


def cfg_note_kind(alias: str) -> str:
    """Tipo declarado en `registro/` para los que aún no tienen ficha."""
    import json as _json
    from .projects import REGISTRO_DIR
    try:
        return str(_json.loads((REGISTRO_DIR / f"{alias}.json").read_text(encoding="utf-8"))
                   .get("kind", ""))
    except (OSError, ValueError):
        return ""


def PROJECTS_DATOS() -> set[str]:
    from .projects import _DATOS
    return set(_DATOS)


# -- por dónde se lanza un run -------------------------------------------------
#
# Aquí vivían cuatro rutas `/tasks*` que creaban y gobernaban runs en **Hermes**
# (`create_run`, `approve`, `steer`, `stop` + el lector SSE de `relay.py`).
# Se quitaron en la Fase 1: desde que el autopilot es el único motor de tools
# (`docs/motores.md` §6, "dos motores con tools son dos sitios donde puede vivir
# un guardarraíl"), nada las llamaba — ni la app, ni `bin/lab/medir-hermes.py`
# — y los 84 `run_*.jsonl` del histórico pararon el 2026-10-03.
#
# Lo que las sustituya ya existe y está probado: `POST /autopilot` y
# `/autopilot/start`, con `POST /autopilot/{run_id}/steer` y `/stop` para el
# control del run en marcha. Mismo poder, un solo camino.


class AutopilotIn(BaseModel):
    prompt: str
    model: Optional[str] = None
    max_steps: int = 6
    project: Optional[str] = None
    instructions: Optional[str] = None
    remember: bool = True
    # Con `verificar`, cada escritura pasa por el verificador del proyecto y el
    # run se detiene si el rojo no mejora. Sin esto el run termina cuando el
    # modelo deja de pedir tools, que no dice nada del código.
    verificar: bool = False
    que: str = "check"
    #: Token de un solo uso de una aprobación previa. Es lo que cierra el
    #: círculo: el run se paró pidiendo permiso, lo aprobaste, y al volver a
    #: lanzar le das el token para que reintente esa misma llamada sin volver a
    #: preguntar.
    #:
    #: Sin este campo el token era un callejón sin salida: la cola lo emitía,
    #: `/aprobaciones` lo devolvía, y no había por dónde meterlo. La fila se
    #: marcaba "aprobada" y el paso volvía a pedir permiso para siempre.
    token: str = ""
    #: Enfoque **fijado a mano**, o vacío para que lo pida Aegis.
    #:
    #: Lo normal es vacío: los enfoques los pide Aegis con `usar_enfoque`, que es
    #: lo que hace que sean suyos y no un menú. Este campo existe para cuando la
    #: derivación falla y hay que corregirlo sin cambiar el encargo.
    #:
    #: No es decoración. `bridge/enfoques/{enfoque}.md` se inyecta en el system
    #: prompt **solo** en los runs que lo llevan, y por un motivo medido: A-016, el
    #: 7B deja de emitir `tool_calls` cuando el prompt crece. Meterlo en
    #: `metodo.md` lo pagaría **todos** los runs, incluidos los de operación
    #: normal, que son los que más necesitan llamar tools.
    enfoque: str = ""


class AutopilotOut(BaseModel):
    model: str
    answer: str
    steps: int
    trace: list[dict]
    project: Optional[str] = None
    # Por qué terminó el run: sin_tools | respuesta_vacia | max_steps | puerta.
    # "agotó los pasos" y "el modelo respondió" se confundían, y ese dato es el
    # que mide si el bucle funciona.
    fin: str = "max_steps"

    # -- Veredicto (app/veredicto.py) ------------------------------------------
    #
    #: ## Por qué hay que declararlos aquí y no solo en el dict
    #: Este es un `response_model`, y Pydantic **descarta** lo que no está
    #: declarado. El envoltorio `run_autopilot` añadía `estado`, `completado`,
    #: `resumen` y `duracion_s` al dict, y el endpoint se los comía en silencio:
    #: en proceso el veredicto estaba, por HTTP no. El bug serafted durante dos
    #: sesiones porque el test que lo habría visto (`test_autopilot.py`) llama
    #: a `run_autopilot` **directamente**, saltándose el endpoint.
    #:
    #: La lección no es «declara los campos»: es que **la ruta serializa, y el
    #: test no pasa por ella**. Un contrato de API necesita un test que llame a la
    #: API, no solo a la función de debajo.
    estado: str = "incompleto"
    completado: bool = False
    resumen: str = ""
    duracion_s: float = 0.0
    tools_ok: list[str] = []
    tools_fallidas: list[str] = []


class AutopilotStarted(BaseModel):
    """Un run de autopilot lanzado en segundo plano."""
    run_id: str
    status: str = "started"


class AutopilotStatus(BaseModel):
    """Progreso de un run en segundo plano: lo que el móvil va consultando."""
    run_id: str
    status: str                      # running | completed | failed
    steps: int = 0
    trace: list[dict] = []
    answer: Optional[str] = None
    fin: Optional[str] = None
    error: Optional[str] = None
    #: Los mismos campos del veredicto, por la misma razón: `/autopilot/{id}` es
    #: lo que el móvil consulta mientras corre, y si el veredicto no viaja por
    #: aquí el cliente ve un run terminado sin poder decir si terminó.
    estado: str = ""
    completado: bool = False
    resumen: str = ""
    duracion_s: float = 0.0


#: Buffer **en vivo** de los runs de autopilot. Con tope: un móvil que nunca
#: cierra sesión no puede dejar el bridge creciendo sin límite.
#:
#: ## Por qué se queda, siendo que ya se lee del disco
#: Porque el móvil va **consultando mientras el run corre**, y necesita ver la
#: traza crecer paso a paso: en un 7B un paso puede tardar medio minuto. Un JSONL
#: en disco no se escribe tan seguido, así que para "ahora mismo" el disco llega
#: tarde.
#:
#: ## Por qué ya no es la única copia
#: Antes lo era, y eso no era una caché: era una pérdida de datos disfrazada de
#: feature. Al reiniciar el bridge se olvidaban los 50 últimos runs, y del 51 en
#: adelante nunca hubo nada.
#:
#: ## Y el disco tampoco lo tenía
#: La primera versión de este arreglo Miro el disco y trinkó: los JSONL de
#: `data/logs/runs/` los escribía el relay de Hermes, y **los runs de autopilot
#: nunca escribieron ninguno**. O sea, que la única copia era el dict en memoria.
#: Por eso `_run_autopilot_once` escribe ahora su traza al JSONL del run: sin
#: eso, la caída al disco sería una promesa, y una promesa de persistencia es
#: A-016 con otro disfraz.
_AUTOPILOT_RUNS: dict[str, dict] = {}
_AUTOPILOT_RUNS_MAX = 50

#: Prefijo de los ids de autopilot. Sirve para reconocer un run propio sin
#: mirar el buffer: un run ya podado sigue siendo reconocible, y un id de Hermes
#: nunca empieza por aquí.
_AUTOPILOT_PREFIX = "autopilot-"


def _autopilot_trim() -> None:
    """Poda los runs más viejos, **saltando los que siguen en marcha**.

    ## Por qué no basta con quitar el primero
    Con un dict de datos, quedarse sin la entrada de un run terminado era una
    molestia menor. Con `task`, `parar` y `extra` dentro, podar un run vivo le
    borraría justo lo que lo hace controlable: quien pulsara parar recibiría un
    404 y el steer se iría a un queue sin dueño, sin ningún error visible.

    Por eso el recorte solo se come runs terminados. Si todos los que quedan
    están vivos, no recorta y el buffer crece por encima del tope: preferible a
   trunca un run que se vuelve incontrolable, y en la práctica los runs vivos
    son pocos porque el tope es 50.
    """
    if len(_AUTOPILOT_RUNS) <= _AUTOPILOT_RUNS_MAX:
        return
    sobran = len(_AUTOPILOT_RUNS) - _AUTOPILOT_RUNS_MAX
    for run_id in list(_AUTOPILOT_RUNS):
        if sobran <= 0:
            break
        if _AUTOPILOT_RUNS[run_id].get("status") == "running":
            continue
        _AUTOPILOT_RUNS.pop(run_id, None)
        sobran -= 1


async def _run_autopilot_once(body: AutopilotIn, ctx: str, puerta: Any,
                              run_id: str, on_step: Any = None,
                              token: str = "",
                              parar: Any = None, extra: Any = None) -> dict:
    """El bucle de verdad, con su traza, su verificador y su episodio.

    Lo comparten la ruta síncrona y la de segundo plano: que el móvil vea el
    mismo resultado por los dos caminos, no dos implementaciones que divergen.

    ## Por qué se mide la base ANTES
    `estado_base` se calcula una vez, al empezar, y se le pasa a la autonomía en
    cada paso. Si se midiera después de cada escritura, el rojo ya sería
    consecuencia de lo que hizo Aegis y no serviría para decidir si puede
    seguir. Es la línea base, y por eso se mide una vez y antes.

    `parar` y `extra` llegan desde la ruta de segundo plano; la síncrona no los
    pasa porque no hay nadie a quien parar mientras `/autopilot` no responde.
    """
    project = body.project or ""
    estado_base = medir_base(project, body.que) if project else None
    if estado_base and estado_base.get("rojo"):
        log.info("autopilot %s: base de '%s' en rojo antes de empezar (%s problemas)",
                 run_id, project, estado_base.get("problemas"))
    try:
        result = await run_autopilot(
            body.prompt,
            ollama_url=settings.ollama_base_url,
            model=body.model or settings.autopilot_model,
            max_steps=max(1, min(body.max_steps, 16)),
            instructions=body.instructions or "",
            project=project,
            memory=ctx,
            gate=puerta,
            on_step=on_step,
            run_id=run_id,
            autonomy=autonomy_modulo,
            token=token,
            enfoque=body.enfoque or "",
            estado_base=estado_base,
            parar=parar,
            extra=extra,
        )
    except Exception as exc:  # noqa: BLE001 — un run que revienta también deja rastro
        # Esto estaba fuera de todo try: un run que moría de una excepción se
        # iba **sin traza y sin episodio**, porque los dos estaban aquí debajo.
        # Lo que se perdía no era un dato, era el aprendizaje entero: sin
        # episodio, esa forma de fallo no se vuelve a reconocer.
        detalle = f"{type(exc).__name__}: {exc}".strip()[:400]
        log.exception("autopilot %s: el run reventó", run_id)
        return await _run_roto(run_id, project, body, detalle, on_step)
    log.info("autopilot %s: %d pasos, %d tools ejecutadas (proyecto=%s, enfoque=%s)",
             run_id, result["steps"], sum(1 for t in result["trace"] if t.get("tool")),
             project or "-", body.enfoque or "-")
    await _registrar_run(run_id, project, body, result, on_step)
    return result


async def _registrar_run(run_id: str, project: str, body: AutopilotIn,
                         result: dict[str, Any], on_step: Any = None) -> None:
    """Escribe la traza a disco, el episodio en memoria y la telemetría.

    ## Por qué está en una función
    Estaba suelto en `_run_autopilot_once`, **después** del run. Eso convertía
    cualquier excepción en un run que no existía: sin JSONL, sin episodio, sin
    `GET /runs` que lo teachara. Un fallo que no deja rastro es un fallo que no
    se puede ni detectar ni corregir, y el(repo) entero está montado para que los
    fallos se puedan corregir.
    """
    # La traza va al disco. Sin esto, el JSONL del run solo lo escribía el relay
    # de Hermes y un run de autopilot **no existía** fuera del buffer en memoria:
    # reiniciar el bridge lo borraba sin dejar rastro. Y `GET /runs` leía ficheros
    # que no existían para la mitad de los runs que sí habían ocurrido.
    _escribir_jsonl_de_autopilot(run_id, project, result)
    if on_step is not None:
        # En segundo plano, alguien puede haberse suscrito a este run. Se le
        # avisa del desenlace sin que nadie lo estuviera esperando: antes, el
        # cliente se quedaba mirando un run que ya no avanzaba.
        await on_step(result["steps"], {
            "step": result["steps"], "action": "fin", "fin": result.get("fin", ""),
            "answer": result.get("answer", "")[:1200],
        })
    # La traza es la evidencia. El `answer` del modelo no lo es: se ha medido que
    # llega a reportar éxito sin haber escrito nada (lessons/aegis.md A-013).
    for paso in result["trace"]:
        if paso.get("gate"):
            telemetry.record("INFO", "autopilot.gate", run_id=run_id,
                             paso=paso["step"], tool=paso.get("tool"),
                             **{k: v for k, v in paso["gate"].items()
                                if k in ("ok", "problemas", "delta", "mismo_error", "stop")})
    if not body.remember or not get_memory():
        return
    tools_used = [t for t in result["trace"] if t.get("tool")]
    # Una tool puede "funcionar" y aun así rechazar la edición (guardarraíl de
    # sintaxis, whitelist). Eso es un fallo del agente, no un acierto: si no se
    # cuenta, el recall le va a enseñar los runs como exitosos.
    failures = [t for t in tools_used
                if t.get("ok") is False
                or "RECHAZADO" in str(t.get("result", ""))
                or "no se encontró" in str(t.get("result", ""))
                or "ERROR:" in str(t.get("result", ""))]
    used = [t["tool"] for t in tools_used]
    await get_memory().remember({
        "run_id": run_id,
        "agent": "autopilot",
        "outcome": "failed" if failures else "success",
        "prompt": f"[{project}] {body.prompt}".strip(),
        "summary": f"tools={used or 'ninguna'}; pasos={result['steps']}; "
                   f"rechazos={len(failures)}; respuesta={result['answer'][:200]}",
        "text": json.dumps(result["trace"], ensure_ascii=False)[:4000],
        "code": [],
        "error": "; ".join(str(t.get("result"))[:200] for t in failures),
        "at": "",
    })


async def _run_roto(run_id: str, project: str, body: AutopilotIn,
                    detalle: str, on_step: Any = None) -> dict[str, Any]:
    """Un run que reventó, convertido en un run que **sí** se puede leer.

    No se tira: se cierra con `fin: "reventado"` y su motivo. La razón es doble:
    el móvil tiene que poder pintar algo, y el episodio `failed` es lo que
    permite reconocer la próxima vez ese mismo fallo (A-016: el veredicto sale de
    la traza, nunca de la ausencia de traza).
    """
    answer = (f"El run se interrumpió por un error del bridge, no por tu: {detalle}\n"
              f"No he terminado. No hay más traza que esta, porque el fallo ha "
              f"sucedido antes de poder registrarla.")
    result = {
        "model": body.model or settings.autopilot_model,
        "answer": answer,
        "steps": 0,
        "trace": [{"step": 0, "action": "reventado", "text": detalle}],
        "fin": "reventado",
        "error": detalle,
    }
    await _registrar_run(run_id, project, body, result, on_step)
    return result


@app.post("/autopilot", response_model=AutopilotOut)
async def autopilot(body: AutopilotIn,
                   _auth: None = Depends(exigir_token)) -> AutopilotOut:
    """Ejecuta una tarea con el bucle modelo→aegis-ops, sin depender de tool_calls.

    Es la vía fiable de autonomía: el modelo local decide QUÉ tool usar y el
    bridge la EJECUTA de verdad, con lista blanca y traza auditable.

    El run se guarda como episodio: con `project` se inyecta la **ficha** del
    proyecto y el recall, de modo que una corrección escrita a mano llegue sola a
    los intentos siguientes.

    Lo que ya **no** se inyecta son las lecciones: eran el 54 % del prompt y su
    puerta —la tool `lecciones`— tuvo 0 llamadas en 857 runs registrados. Los
    números están en `load_lessons`, en `app/autopilot.py`.

    Es síncrono a propósito. Para el móvil, que no puede dejar al usuario
    mirando un spinner dos minutos sin saber qué pasa, está
    `POST /autopilot/start` + `GET /autopilot/{run_id}`.
    """
    project = body.project or ""
    ctx = ""
    if project:
        ctx = await _memory_context(body.prompt)
    puerta = None
    if body.verificar:
        from .verifier import gate as _gate
        puerta = _gate(project, body.que)
    # El id es un uuid y no un timestamp. Con `int(time.time())`, dos POST en el
    # mismo segundo producían el MISMO `run_id`, y como el JSONL se abre en "w"
    # (ver `_escribir_jsonl_de_autopilot`), el segundo truncaba el historial del
    # primero. Un run que desaparece del registro es justo lo que este repo dice
    # no admitir: la caída a disco no puede ser una promesa.
    result = await _run_autopilot_once(
        body, ctx, puerta, f"{_AUTOPILOT_PREFIX}{uuid.uuid4().hex[:12]}",
        token=body.token)
    return AutopilotOut(project=project or None, **result)


@app.post("/autopilot/start", response_model=AutopilotStarted)
async def autopilot_start(body: AutopilotIn,
                        _auth: None = Depends(exigir_token)) -> AutopilotStarted:
    """Lanza el run y devuelve ya, con la traza creciendo en GET /autopilot/{id}."""
    run_id = f"{_AUTOPILOT_PREFIX}{uuid.uuid4().hex[:12]}"
    # `parar` y `extra` se crean **antes** de la tarea y se guardan en el run: un
    # endpoint de parada que llegara después de arrancar la tarea podría no
    # encontrarlo, y la persona vería "parado" y el run seguiría escribiendo.
    # El `task` se rellena justo debajo, en cuanto existe.
    _AUTOPILOT_RUNS[run_id] = {"run_id": run_id, "status": "running",
                               "steps": 0, "trace": [],
                               "answer": None, "fin": None, "error": None,
                               "parar": asyncio.Event(), "extra": asyncio.Queue(),
                               "task": None}
    _autopilot_trim()
    project = body.project or ""
    ctx = await _memory_context(body.prompt) if project else ""
    puerta = None
    if body.verificar:
        from .verifier import gate as _gate
        puerta = _gate(project, body.que)

    async def _on_step(step: int, entry: dict) -> None:
        run = _AUTOPILOT_RUNS.get(run_id)
        if run is None:
            return
        run["trace"].append(entry)
        run["steps"] = max(run["steps"], step)

    async def _runner() -> None:
        try:
            run = _AUTOPILOT_RUNS.get(run_id) or {}
            result = await _run_autopilot_once(body, ctx, puerta, run_id,
                                               on_step=_on_step, token=body.token,
                                               parar=run.get("parar"),
                                               extra=run.get("extra"))
            run = _AUTOPILOT_RUNS.setdefault(run_id, {"run_id": run_id})
            run.update(status="completed", steps=result["steps"],
                       answer=result["answer"], fin=result["fin"],
                       trace=result["trace"],
                       # El veredicto va al buffer también. Sin esto el móvil
                       # ve el run terminado por `/autopilot/{id}` y no puede
                       # decir si terminó — que es justo lo que el veredicto
                       # vino a arreglar, y solo funcionaría por HTTP.
                       estado=result.get("estado") or "",
                       completado=bool(result.get("completado")),
                       resumen=result.get("resumen") or "",
                       duracion_s=float(result.get("duracion_s") or 0.0))
        except asyncio.CancelledError:
            # Parar la tarea de asyncio no es la vía de parada —el bucle corta
            # entre pasos—, pero si ocurre (apagado del bridge) el run no puede
            # quedarse en `running` para siempre: se marca como parado, que es
            # lo que pasó.
            log.info("autopilot %s: tarea cancelada", run_id)
            run = _AUTOPILOT_RUNS.setdefault(run_id, {"run_id": run_id})
            run.update(status="completed", fin="parado",
                       answer=run.get("answer")
                       or "El run se canceló antes de terminar.")
            raise
        except Exception as exc:  # noqa: BLE001 — el run no puede morir en silencio
            # Antes: `status="failed"` con `error="'fin'"` cuando la puerta del
            # verificador paraba el run, porque aquel retorno no traía `fin` y
            # esta línea pedía `result["fin"]`. El KeyError tapaba el motivo real
            # y el run quedaba como un fallo sin explicación.
            #
            # Ahora `_run_autopilot_once` **no** propaga nada: devuelve un `fin`
            # siempre. Este `except` queda como la red de debajo de la red, y por
            # eso registra su propio rastro en disco antes de rendirse.
            log.exception("autopilot %s: fallo en el envoltorio", run_id)
            detalle = f"{type(exc).__name__}: {exc}".strip()[:400]
            run = _AUTOPILOT_RUNS.setdefault(run_id, {"run_id": run_id})
            run.update(status="completed", steps=run.get("steps", 0),
                       fin="reventado", error=detalle,
                       answer=run.get("answer")
                       or f"El run se interrumpió por un error del bridge: {detalle}")
            _escribir_jsonl_de_autopilot(run_id, body.project or "", {
                "model": body.model or settings.autopilot_model,
                "answer": run["answer"], "steps": run.get("steps", 0),
                "trace": run.get("trace", []), "fin": "reventado",
            })

    tarea = asyncio.create_task(_runner(), name=f"autopilot-{run_id}")
    # La tarea se guarda ya en marcha: el endpoint de parada solo necesita el
    # `Event`, pero sin la referencia el run queda huérfano en `/proc` si nadie
    # lo para nunca, y no hay forma de distinguir eso de un bridge sano.
    _AUTOPILOT_RUNS[run_id]["task"] = tarea
    return AutopilotStarted(run_id=run_id)


class SteerIn(BaseModel):
    """Instrucción para un run que ya está corriendo."""

    text: str = Field(min_length=1, max_length=4_000)


@app.post("/autopilot/{run_id}/stop")
async def autopilot_stop(run_id: str,
                      _auth: None = Depends(exigir_token)) -> dict:
    """Pide que el run deje de empezar pasos.

    ## Por qué no se cancela la tarea
    El bucle está a mitad de un `await` contra el modelo o dentro de `_execute`,
    que **es síncrono**: cortar ahí deja una escritura a medias y la traza sin el
    paso que la menjelaskan. Poner el `Event` deja terminar el paso en marcha y
    corta antes de pedirle nada más al modelo.

    La parada es por tanto «no empieces otro»: si ya habías pedido una tool, esa
    se ejecuta y se registra. Es lo que hace un interruptor de proceso, y es
    honesto porque la traza que devuelve es exactamente lo que corrió.
    """
    run = _AUTOPILOT_RUNS.get(run_id)
    if run is None:
        # No es un fallo del usuario: el run puede haberse podado, o el bridge
        # haberse reiniciado. El JSONL sigue ahí, que es lo que permite decirlo
        # en vez de fingir que el id nunca existió.
        raise HTTPException(
            status_code=404,
            detail=f"el run {run_id} no está vivo: o terminó y se cayó del "
                   f"buffer, o el bridge se reinició. Se puede parar lo que está "
                   f"corriendo ahora, no un run ya terminado.")
    if run.get("status") != "running":
        return {"run_id": run_id, "status": run.get("status"), "parado": False,
                "detalle": "el run ya había terminado"}
    run["parar"].set()
    return {"run_id": run_id, "status": "parando", "parado": True,
            "detalle": "termina el paso en marcha y no empieza otro"}


@app.post("/autopilot/{run_id}/steer")
async def autopilot_steer(run_id: str, body: SteerIn,
                       _auth: None = Depends(exigir_token)) -> dict:
    """Mete una instrucción en un run que ya está corriendo.

    Se aplica en el **siguiente** paso, no en mitad del actual: el paso en marcha
    ya tiene su lista `messages` decidida, y cambiarlo a mitad dejaría la traza
    diciendo una cosa y el resultado de la tool siendo otro.
    """
    run = _AUTOPILOT_RUNS.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"el run {run_id} no está vivo, así que no hay a quién "
                   f"dirigir.")
    if run.get("status") != "running":
        return {"run_id": run_id, "aplicada": False,
                "detalle": "el run ya había terminado"}
    run["extra"].put_nowait(body.text)
    return {"run_id": run_id, "aplicada": True,
            "detalle": "surte efecto en el próximo paso"}


@app.get("/autopilot/{run_id}", response_model=AutopilotStatus)
async def autopilot_status(run_id: str,
                           _auth: None = Depends(exigir_token)) -> AutopilotStatus:
    """Progreso del run: pasos ya ejecutados, tools y por qué terminó.

    Si no está en el buffer en vivo —porque el bridge se reinició, o porque ya
    se cayó del tope de 50— se reconstruye desde el JSONL del disco. Un 404 aquí
    sería mentir: el run ocurrió y su traza está escrita.

    ## Por qué el `AutopilotStatus` se arma campo a campo
    El dict del run guarda también `parar`, `extra` y `task`, que son objetos
    vivos de asyncio. Un `AutopilotStatus(**run)` depende de que pydantic los
    ignore por defecto —que hoy sí, pero es un detalle de la librería, no una
    decisión— y además intentaría serializar un `Event` si alguien cambia ese
    ajuste. Nombrar los campos que salen es lo que hace que este endpoint no
    pueda romperse al añadir control de un run.
    """
    run = _AUTOPILOT_RUNS.get(run_id)
    if run is None:
        return _autopilot_desde_disco(run_id)
    return AutopilotStatus(
        run_id=run_id,
        status=run.get("status") or "running",
        steps=run.get("steps") or 0,
        trace=run.get("trace") or [],
        answer=run.get("answer"),
        fin=run.get("fin"),
        error=run.get("error"),
        estado=run.get("estado") or "",
        completado=bool(run.get("completado")),
        resumen=run.get("resumen") or "",
        duracion_s=float(run.get("duracion_s") or 0.0),
    )


def _autopilot_desde_disco(run_id: str) -> AutopilotStatus:
    """Reconstruye el estado de un run de autopilot desde su JSONL."""
    try:
        d = leer_run(run_id, max_eventos=10_000)
    except HTTPException as exc:
        raise HTTPException(status_code=404,
                            detail=f"run de autopilot desconocido: {run_id}") from exc
    info = d.get("run") or {}
    herramientas = info.get("herramientas") or []
    # El motivo de cierre vive en el payload del evento terminal. Antes solo se
    # miraba `run.failed.detail`, así que un run reconstruido decía siempre
    # `fin: null`: se sabía que acabó pero no por qué, que es justo el dato que
    # hace falta para entender la traza.
    fin = None
    estado = ""
    resumen = ""
    duracion = 0.0
    for ev in d.get("eventos") or []:
        nombre = ev.get("event") or ""
        payload = ev.get("payload") or {}
        if nombre == "run.failed.detail":
            fin = "fallo"
        elif nombre.startswith("task.") and isinstance(payload, dict):
            if payload.get("fin"):
                fin = str(payload["fin"])
            # El veredicto viaja en el terminal del JSONL. Se **lee**, no se
            # recalcula: recalcularlo aquí daría un número distinto del que tuvo
            # el run, porque el `answer` del JSONL va recortado a 1.000 chars.
            if payload.get("estado"):
                estado = str(payload["estado"])
                resumen = str(payload.get("resumen") or "")
        elif nombre == "run_duration_s" and ev.get("s"):
            try:
                duracion = float(ev.get("s") or 0.0)
            except (TypeError, ValueError):
                pass
    return AutopilotStatus(
        run_id=run_id,
        status=info.get("estado") or "completed",
        steps=len(herramientas),
        trace=[],
        fin=fin,
        error=info.get("error") or None,
        estado=estado,
        completado=estado == "completado",
        resumen=resumen,
        duracion_s=duracion,
    )


# -- Lo que Aegis sabe y lo que recuerda ---------------------------------------
#
# Hasta aquí el móvil veía siete endpoints y el resto de la capacidad de Aegis
# era invisible: la memoria existía (35 nodos, 588 aristas, episodios reales) y
# no había forma de consultarla desde el móvil. Un asistente que no puede decir
# lo que recuerda se comporta como si no tuviera memoria, que es exactamente lo
# que pasa si el recuerdo es cierto y no se muestra.

class MemoriaOut(BaseModel):
    """Un episodio, en metadatos. Nunca el texto completo.

    ## Por qué no el texto
    El episodio guarda el prompt que le escribiste y la respuesta del modelo.
    Exponer eso desde el móvil significa que **todo lo que le has contado a Aegis
    queda a un GET de distancia** de cualquier otra cosa en la red. Y no aporta:
    para saber "qué hice" con qué, con cuántas herramientas y si salió bien, la
    fila del grafo ya tiene todo. El texto se queda en su almacén.
    """
    run_id: str
    agente: str = ""
    proyecto: str = ""
    herramientas: list[str] = []
    pasos: int = 0
    ok: bool = True
    epoca: str = ""


class RunOut(BaseModel):
    """Un run del historial, leído de disco."""
    run_id: str
    proyecto: str = ""
    iniciado: str = ""
    finalizado: str = ""
    estado: str = "desconocido"
    pasos: int = 0
    herramientas: list[str] = []
    duracion_s: float = 0.0
    error: str = ""


@app.get("/memoria", )
async def memoria(consulta: str = "", limite: int = 20,
              _auth: None = Depends(exigir_token)) -> dict:
    """Lo que Aegis recuerda, y solo lo que se resolvió de verdad.

    ## Por qué solo `success`
    El `recall` devuelve lo más cercano **sin mirar el outcome**, y eso lo inyecta
    al prompt bajo el rótulo "Episodios similares resueltos antes". Un `failed`
    presentado como solución es instrucción contraria, y el modelo la copia.
    Está medido: con tres episodios falsos en el prompt, el tool calling bajó de
    7/8 a 0/8 (A-016). Aquí el filtro es el mismo, y además es visible: si
    solo hay un `sin_evidencia` guardado, la lista sale vacía y se dice por qué.
    """
    import json as _json
    from .memory import get_memory as _mem

    mem = _mem()
    if mem is None:
        return {"episodios": [], "nota": "la memoria no está inicializada"}

    if consulta:
        crudos = await mem.recall(consulta, k=limite)
        # La clave es `episodes`. Con `episodios` esta rama devolvía [] con
        # HTTP 200, es decir «no hay nada» como respuesta a una búsqueda que sí
        # tenía resultados. No lo veía nadie porque la app nunca manda `consulta`,
        # y un 200 con lista vacía es indistinguible de una memoria vacía.
        filas = (crudos.get("episodes") or [])
    else:
        filas = _episodios_del_grafo(limite * 2)

    salida: list[MemoriaOut] = []
    filtrados = 0
    for f in filas:
        meta = f.get("metadata") if isinstance(f, dict) else None
        if not meta:
            continue
        if meta.get("outcome") != "success":
            filtrados += 1
            continue
        salida.append(MemoriaOut(
            run_id=str(meta.get("run_id") or ""),
            agente=str(meta.get("agent") or ""),
            proyecto=_proyecto_de(str(meta.get("prompt") or "")),
            herramientas=_herramientas_de(str(meta.get("summary") or "")),
            pasos=_pasos_de(str(meta.get("summary") or "")),
            ok=True,
            epoca=str(meta.get("at") or meta.get("created_at") or ""),
        ))
        if len(salida) >= limite:
            break
    nota = (f"{filtrados} episodio(s) sin evidencia no se enseñan: un fallo "
            f"presentado como solución es instrucción contraria." if filtrados else "")
    return {"episodios": [e.model_dump() for e in salida], "nota": nota,
            "estado": mem.status()}


def _episodios_del_grafo(limite: int) -> list[dict]:
    """Episodios crudos del grafo, los más recientes primero.

    Antes esto alcanzaba `graph._conn` con dos `getattr` y un
    `__import__("app.memory")`. Cuatro capas de reach para hacer un `SELECT`, y
    dependía de que `run.sh` exporte `PYTHONPATH=app` para que el `__import__`
    resolviera: si alguien lanza el bridge de otra forma, esto devolvía `[]` en
    silencio y `/memoria` parecía una memoria vacía. Ahora es un método público del
    grafo, que es donde vive la consulta.
    """
    mem = get_memory()
    graph = getattr(mem, "graph", None) if mem else None
    if graph is None:
        return []
    filas = graph.episodes_recientes(limite)
    return [{"metadata": {"run_id": r.get("run_id", ""),
                          "agent": r.get("agent", ""),
                          "outcome": r.get("outcome", ""),
                          "prompt": r.get("prompt", ""),
                          "summary": r.get("summary", ""),
                          "at": r.get("created_at", "")}}
            for r in filas]


def _proyecto_de(prompt: str) -> str:
    """El `[alias]` con el que `main.py` etiqueta el prompt de un episodio."""
    if prompt.startswith("[") and "]" in prompt:
        return prompt[1:prompt.index("]")]
    return ""


def _herramientas_de(summary: str) -> list[str]:
    """Las tools del campo `tools=[...]` del resumen del episodio."""
    import ast
    if "tools=" not in summary:
        return []
    bruto = summary.split("tools=", 1)[1].split(";", 1)[0].strip()
    try:
        lista = ast.literal_eval(bruto)
    except (ValueError, SyntaxError):
        return []
    return [str(x) for x in lista] if isinstance(lista, (list, tuple)) else []


def _pasos_de(summary: str) -> int:
    for parte in summary.split(";"):
        if "pasos=" in parte:
            try:
                return int(parte.split("pasos=", 1)[1])
            except ValueError:
                return 0
    return 0


@app.get("/runs", )
async def runs(limite: int = 20, proyecto: str = "",
             _auth: None = Depends(exigir_token)) -> dict:
    """El historial de runs, leído de los JSONL de disco.

    ## Por qué del disco y no de memoria
    Antes estos datos vivían en `_AUTOPILOT_RUNS`, un dict **en memoria** con un
    tope de 50. Eso no era una caché: era una pérdida de datos disfrazada de
    feature. Al reiniciar el bridge se olvidaban los 50 últimos runs, y a partir
    del 51 nunca hubo nada. Los ficheros de `data/logs/runs/` no tienen ese
    problema, y son lo que se escribe cuando el run ocurre.

    Por eso este endpoint **sustituye** al dict en vez de acompañarlo: dos
    fuentes de verdad para lo mismo es una que se desincroniza sin avisar.
    """
    return {"runs": leer_runs(limite=limite, proyecto=proyecto)}


@app.get("/runs/{run_id}", )
async def run_detalle(run_id: str, eventos: int = 200,
                     _auth: None = Depends(exigir_token)) -> dict:
    """Un run y sus eventos. Los `text.delta` van plegados.

    Un run largo tiene ~11.700 líneas de `text.delta` y devolverlas todas hace
    que el móvil se atasque parseando una respuesta que no va a pintar. Se pliegan
    en un único `texto` y el resto de eventos (tools, puertas, errores) se
    devuelven enteros: eso es lo que se mira.
    """
    return leer_run(run_id, max_eventos=eventos)


def _runs_dir() -> Path:
    return Path(settings.log_dir) / "runs"


def leer_runs(limite: int = 20, proyecto: str = "") -> list[dict[str, Any]]:
    """Lee los runs del disco. Nunca lanza: un JSONL corrupto se salta."""
    d = _runs_dir()
    if not d.is_dir():
        return []
    salida: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                    reverse=True):
        if len(salida) >= limite:
            break
        info = _resumir_run(d / f.name)
        if info and (not proyecto or info["proyecto"] == proyecto):
            salida.append(info)
    return salida


def _resumir_run(ruta: Path) -> Optional[dict[str, Any]]:
    """Un run en una línea: cuándo, qué tools, cómo acabó.

    Se lee el fichero entero, pero **no se guarda nada**: es un resumen para
    pintar una lista. Un historial de 82 ficheros con 11.000 líneas cada uno se
    lee en cuanto lo pides una vez y no se cachea, porque una caché de historial
    es un historial que miente en cuanto el fichero cambia.
    """
    proyecto, herramientas, pasos = "", [], 0
    iniciado = finalizado = ""
    duracion = 0.0
    estado = "desconocido"
    error = ""
    n_eventos = 0
    try:
        with ruta.open(encoding="utf-8") as fh:
            for linea in fh:
                try:
                    d = json.loads(linea)
                except ValueError:
                    continue
                ev = d.get("event") or ""
                # Se cuentan `tool.started` y `tool.completed`: los runs de
                # Hermes emiten el primero y los de autopilot solo el segundo.
                # Contar solo uno de los dos hacía que la mitad de los runs
                # aparecían con cero pasos, que se lee como "no hizo nada".
                if ev.startswith("tool.started") or ev.startswith("tool.completed"):
                    herramientas.append(str((d.get("payload") or {}).get("tool") or "?"))
                if "metric" in d:
                    if d.get("metric") == "run_duration_s":
                        try:
                            duracion = float(d.get("value") or d.get("s") or 0.0)
                        except (TypeError, ValueError):
                            pass
                if ev == "task.created" or ev == "status.changed":
                    if not iniciado:
                        iniciado = str(d.get("at") or "")
                    payload = d.get("payload") or {}
                    if isinstance(payload, dict):
                        proyecto = str(payload.get("project") or proyecto or "")
                if ev == "run.failed.detail":
                    error = str(d.get("error") or "")[:300]
                if ev in ("task.done", "task.failed", "task.stopped"):
                    estado = ev.split(".")[-1]
                    finalizado = str(d.get("at") or "")
                n_eventos += 1
    except OSError:
        return None
    if not iniciado:
        try:
            iniciado = __import__("datetime").datetime.fromtimestamp(
                ruta.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            iniciado = ""
    return {
        "run_id": ruta.stem,
        "proyecto": proyecto,
        "iniciado": iniciado,
        "finalizado": finalizado,
        "estado": estado,
        "pasos": len(herramientas),
        "herramientas": herramientas[:40],
        "duracion_s": duracion,
        "error": error,
        "eventos": n_eventos,
    }


def leer_run(run_id: str, max_eventos: int = 200) -> dict:
    """Un run con su traza. Los deltas de texto van plegados en uno."""
    f = _runs_dir() / f"{run_id}.jsonl"
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"no hay ningún run '{run_id}'")
    eventos: list[dict[str, Any]] = []
    texto: list[str] = []
    resumen = _resumir_run(f) or {}
    try:
        with f.open(encoding="utf-8") as fh:
            for linea in fh:
                try:
                    d = json.loads(linea)
                except ValueError:
                    continue
                ev = d.get("event") or ""
                if ev == "text.delta":
                    texto.append(str((d.get("payload") or {}).get("data") or ""))
                    continue
                if not ev or "metric" in d:
                    continue
                eventos.append({"at": d.get("at"), "event": ev,
                                "payload": d.get("payload")})
                if len(eventos) >= max_eventos:
                    break
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"run": resumen,
            "eventos": eventos,
            "texto": "".join(texto)[-8000:]}


# -- El camino rápido: texto que no necesita modelo ----------------------------
#
#
# ## Por qué esto existe, con el número
# Un run del agente tarda **~58 segundos** para «lista los proyectos». El motivo
# no es el modelo: es que **todo** pasa por él, y un run paga 37.057 chars de
# prompt antes del primer token. Pero «qué hora es» son **0,022 milisegundos** y
# «pon una alarma» es una fila en SQLite.
#
# ## Por qué es un endpoint y no un cambio dentro de /autopilot
# Porque **quien habla, escribe**. `/voces` es el camino rápido, y quien no
# reconoce cae al modelo por su cuenta. Los dos hacen lo mismo; uno tarda
# milisegundos y el otro, minutos. `/autopilot` sigue existiendo intacto, y una
# petición de voz que no casa con ningún intent llega exactamente igual que
# siempre.
#
# ## Y por qué el móvil también va aquí
# Porque el objetivo no es «voz»: es «que Aegis conteste en menos de un
# segundo», y la voz es el caso que lo expone. Escribir «pon una alarma a las 7»
# también es instantáneo, y va por la misma puerta.

class VocesIn(BaseModel):
    texto: str = Field(min_length=1, max_length=2_000)
    #: De dónde viene: `movil`, `portatil`, `teclado`. Va en la traza y nada más.
    #: No decide nada: es lo que te deja ver después quién preguntó qué.
    nodo: str = Field(default="teclado", max_length=32)
    proyecto: str = Field(default="", max_length=64)


@app.post("/voces")
async def voces(body: VocesIn, _auth: None = Depends(exigir_token)) -> dict:
    """El camino rápido. T0 si puede, T1 si no.

    ## El orden de las tres líneas es el invariante
    **preparar → decide → aplicar.** Es la puerta entre las dos primeras y la
    tercera, y si se invirtiera el sistema preguntaría después de escribir, que
    es exactamente lo que `AGENTS.md` llama «un informe que llega tarde».

    `intents.preparar()` **no escribe** (calcular y aplicar están separados a
    propósito), así que aquí el permiso se consulta antes de que exista efecto
    ninguno. Es lo que la Fase 1 convierte en puerta.

    ## Y qué devuelve cuando abstain
    `clase: ""` con un 200. **No** un error: abstener es la respuesta correcta
    para casi todo lo que alguien dice, y un 4xx haría que el cliente dijera
    «error» cada vez que no reconoce una frase.
    """
    from . import intents as intents_mod

    plan = intents_mod.preparar(body.texto)
    if plan is None:
        return {"clase": "", "respuesta": "", "sin_modelo": True,
                "cae_a": "T1", "texto": body.texto}

    if plan.escribe:
        # Solo lo que escribe necesita veredicto. Una lectura no pide permiso
        # para leer, pero sí se registra: `sin_modelo` en la traza es lo que
        # sostiene el presupuesto de T0.
        # `autonomy_modulo.decide`, no `autonomy.decide`: en este fichero
        # `autonomy` es la **función** `almacen` (importada con alias), y `decide`
        # es de módulo. Escribí `autonomy.decide` primero y falló en el primer
        # test con «function almacen has no attribute decide» — que es la clase
        # de error que solo aparece cuando alguien ejecuta de verdad.
        veredicto = autonomy_modulo.decide(
            tool=plan.tool or "tarea_crear",
            args=dict(plan.args),
            run_id=f"voces-{uuid.uuid4().hex[:8]}",
            paso=0,
        )
        if not veredicto.ok:
            # La puerta dijo que no. No se escribe, y se devuelve el motivo en vez
            # de caer al modelo: si la petición es «pon una alarma» y eso está
            # prohibido, mandarla al modelo solo produce otro intento de alarma.
            return {"clase": "", "respuesta": veredicto.motivo,
                    "sin_modelo": True, "cae_a": "", "bloqueado": True,
                    "texto": body.texto, "tool": plan.tool}

    import time as _time
    t0 = _time.perf_counter()
    try:
        texto = intents_mod.aplicar(plan)
    except Exception as exc:  # noqa: BLE001 — un intent roto no tumba la puerta
        log.warning("voces %s: %s: %s", plan.intent.nombre, type(exc).__name__, exc)
        return {"clase": "", "respuesta": "", "cae_a": "T1", "sin_modelo": False,
                "texto": body.texto, "error": f"{type(exc).__name__}: {exc}"}

    ms = round((_time.perf_counter() - t0) * 1000, 2)
    log.info("voces %s · %s · %s · %.2f ms", body.nodo, plan.intent.nombre,
             plan.intent.clase, ms)
    return {
        "clase": plan.intent.clase, "respuesta": str(texto),
        "intent": plan.intent.nombre, "tool": plan.tool,
        "args": dict(plan.args), "sin_modelo": True, "ms": ms,
        "cae_a": "", "texto": body.texto,
    }


# -- Tus cosas: notas, tareas y recordatorios ---------------------------------

class NotaIn(BaseModel):
    titulo: str = Field(default="", max_length=200)
    cuerpo: str = Field(default="", max_length=20_000)
    proyecto: str = Field(default="", max_length=64)
    etiquetas: list[str] = Field(default_factory=list)


class TareaIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    notas: str = Field(default="", max_length=5_000)
    proyecto: str = Field(default="", max_length=64)
    #: Fecha acordada, `YYYY-MM-DD`. Vacía = sin fecha, que **no** vence nunca.
    para: str = Field(default="", max_length=32)


class TareaPatch(BaseModel):
    titulo: Optional[str] = Field(default=None, max_length=300)
    notas: Optional[str] = Field(default=None, max_length=5_000)
    para: Optional[str] = Field(default=None, max_length=32)
    estado: Optional[str] = None


@app.get("/notas", )
async def notas_listar(proyecto: str = "", limite: int = 100,
                     _auth: None = Depends(exigir_token)) -> dict:
    return {"notas": notas().notas(proyecto=proyecto, limite=limite)}


@app.post("/notas", )
async def nota_crear(body: NotaIn, _auth: None = Depends(exigir_token)) -> dict:
    from .notas import NotasError
    try:
        return notas().nota_crear(titulo=body.titulo, cuerpo=body.cuerpo,
                                  proyecto=body.proyecto,
                                  etiquetas=body.etiquetas)
    except NotasError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/notas/{nid}", )
async def nota_borrar(nid: str, _auth: None = Depends(exigir_token)) -> dict:
    if not notas().nota_borrar(nid):
        raise HTTPException(status_code=404, detail=f"no hay ninguna nota '{nid}'")
    return {"borrada": nid}


@app.get("/tareas", )
async def tareas_listar(estado: str = "", proyecto: str = "", limite: int = 100,
                      _auth: None = Depends(exigir_token)) -> dict:
    return {"tareas": notas().tareas(estado=estado, proyecto=proyecto, limite=limite)}


@app.post("/tareas", )
async def tarea_crear(body: TareaIn, _auth: None = Depends(exigir_token)) -> dict:
    from .notas import NotasError
    try:
        return notas().tarea_crear(titulo=body.titulo, notas=body.notas,
                                  proyecto=body.proyecto, para=body.para)
    except NotasError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/tareas/{tid}", )
async def tarea_actualizar(tid: str, body: TareaPatch,
                       _auth: None = Depends(exigir_token)) -> dict:
    from .notas import NotasError
    try:
        return notas().tarea_actualizar(
            tid, titulo=body.titulo, notas=body.notas, para=body.para,
            estado=body.estado)
    except NotasError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- La autonomía: qué puede hacer sin preguntar ------------------------------

class ModoAutonomiaIn(BaseModel):
    modo: str


class ProyectoPermisoIn(BaseModel):
    permiso: str = "escribir"


@app.get("/autonomy", )
async def autonomy_estado(_auth: None = Depends(exigir_token)) -> dict:
    """El estado completo: el modo, qué proyectos están marcados y qué hay
    esperando tu OK.

    Va todo en un endpoint porque el móvil lo necesita entero para pintar la
    cabecera, y pedir tres cosas para pintar una línea es pedir dos veces más de
    lo que hace falta.
    """
    a = autonomy()
    proyectos = a.proyectos()
    return {
        "modo": a.modo(),
        "modos": list(MODOS),
        "escritura": proyectos,
        "resumen": a.resumen(),
        "pendientes": a.pendientes(),
    }


@app.post("/autonomy/modo", )
async def autonomy_modo(body: ModoAutonomiaIn,
                    _auth: None = Depends(exigir_token)) -> dict:
    """Cambia el nivel de autonomía. No hay modo que dispense de la cola."""
    try:
        return {"modo": autonomy().set_modo(body.modo)}
    except AutonomiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/autonomy/{alias}", )
async def autonomy_marcar(alias: str, body: ProyectoPermisoIn,
                       _auth: None = Depends(exigir_token)) -> dict:
    """Marca un proyecto como "puedes escribir aquí".

    ## Por qué esto es el permiso de verdad
    Un proyecto sin marcar es de **solo lectura** para Aegis. No es un matiz: es
    la línea. Y hay una razón detrás: tres de los proyectos del registro no
    tienen verificador, así que sus tests ni siquiera se pueden correr. Dar
    permiso de escritura sobre algo que no se puede verificar sería autonomía sin
    forma de saber si salió bien.
    """
    from .projects import PROJECTS
    if alias not in PROJECTS:
        raise HTTPException(status_code=404, detail=f"'{alias}' no está en el registro")
    cfg = PROJECTS[alias]
    if not cfg.verify:
        raise HTTPException(
            status_code=409,
            detail=f"'{alias}' no tiene verificador declarado en app/projects.py, "
                   f"así que no hay contra qué comprobar que el trabajo quedó bien. "
                   f"Decláralo antes de darle permiso de escritura.")
    autonomy().marcar(alias, body.permiso)
    return {"alias": alias, "escritura": autonomy().proyectos()}


@app.delete("/autonomy/{alias}", )
async def autonomy_desmarcar(alias: str,
                          _auth: None = Depends(exigir_token)) -> dict:
    """Quita el permiso. Es la forma de parar a Aegis sobre un proyecto sin
    tener que cambiar el modo entero."""
    if not autonomy().desmarcar(alias):
        raise HTTPException(status_code=404, detail=f"'{alias}' no estaba marcado")
    return {"alias": alias, "escritura": autonomy().proyectos()}


@app.get("/aprobaciones", )
async def aprobaciones_listar(run_id: str = "",
                           _auth: None = Depends(exigir_token)) -> dict:
    """Lo que Aegis quiere hacer y no se atreve a hacer solo.

    Vienen **dos** listas, y no es un detalle de forma:

    - `pendientes`: te están preguntando. Aquí no hay token, porque aún no has
      decidido nada.
    - `aprobadas`: ya dijiste que sí, el token está emitido y **nadie lo ha
      gastado**. Es lo que hace posible cerrar el ciclo desde el móvil: relanzar
      el run con ese token y que la llamada se ejecute sin volver a preguntar.

    Sin la segunda lista, aprobar era un callejón sin salida: el token venía en
    la respuesta del POST, la app lo descartaba, y si se cerraba antes de
    relanzar ya no había dónde recuperarlo. Eso es un permiso que se cobra y
    luego se tira, no una puerta.
    """
    return {"pendientes": autonomy().pendientes(run_id),
            "aprobadas": autonomy().aprobadas_sin_gastar(run_id)}


@app.post("/aprobaciones/{pet_id}", )
async def aprobacion_resolver(pet_id: str, body: DeployDecision,
                            _auth: None = Depends(exigir_token)) -> dict:
    """Aprueba o deniega, y devuelve un token de un solo uso.

    Igual que la puerta de despliegue: el token lo gasta la propia tool y el
    agente nunca lo ve. Si lo manejara el agente, bastaría con que se lo
    imprimieran una vez para que la puerta dejara de existir.
    """
    try:
        p = autonomy().resolver(pet_id, body.decision)
    except AutonomiaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": p["id"], "estado": p["estado"], "token": p.get("token")}


@app.post("/aprobaciones/{pet_id}/motivo", )
async def aprobacion_motivo(pet_id: str, body: FichaIn,
                          _auth: None = Depends(exigir_token)) -> dict:
    """**Por qué** denegas. Esto es lo que hace que la confianza crezca.

    No es que Aegis aprenda a tener cuidado: es que tú se lo dijiste una vez y lo
    tiene en cuenta la próxima. Sin motivo, denegar es un "no" que no se puede
    aplicar a la siguiente situación parecida.
    """
    try:
        p = autonomy().denegar_con_motivo(pet_id, body.contenido)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not p:
        raise HTTPException(status_code=404, detail=f"no hay ninguna petición '{pet_id}'")
    return {"id": p["id"], "estado": p["estado"], "motivo": p["razon_denegacion"]}


#: Prefijos con los que una tool **dice que no** sin lanzar. Las tools de Aegis
#: devuelven el motivo como texto, y ese texto es el que hay que mirar: un
#: "hecho" en la interfaz sobre un "ALTA RECHAZADA" detrás es la misma mentira
#: que se pagó en A-016 (el veredicto que salía de `final_text`).
#:
#: Es una lista corta y a propósito: preferimos un `ok` algo optimista en un caso
#: raro a un `ok` que adivine. El `result` sigue siendo la autoridad.
_MOTIVOS_DE_RECHAZO = (
    "ALTA RECHAZADA",
    "ESCRITURA DENEGADA",
    "escritura RECHAZADA",
)


#: Las tools que **ya** publican su propio desenlace en el aviso.
#:
#: `install_apk` avisa desde `instalar_en_telefono`, que es la única que sabe si
#: `adb install` salió bien de verdad; hacerlo aquí también publicaría dos veces
#: y el orden entre dos broadcasts distintos no está garantizado.
_AVISAN_ELLAS_MISMAS = frozenset({"install_apk"})


def _avisa_por_si_mismo(tool: str) -> bool:
    return tool in _AVISAN_ELLAS_MISMAS


@app.post("/aprobaciones/{pet_id}/ejecutar")
async def aprobacion_ejecutar(pet_id: str,
                              _auth: None = Depends(exigir_token)) -> dict:
    """Ejecuta **la llamada que aprobaste**, con los argumentos que aprobaste.

    ## Por qué esto existe y no es un atajo
    El token valida la llamada, no el run (A-033). Para gastarlo había que
    relanzar el run entero y confiar en que el modelo emitiera **la misma** tool
    con **los mismos** argumentos. Medido con `project_create`: de cuatro
    intentos, solo uno casó. Relanzar no es "ejecutar lo que aprobaste", es
    pedirle al modelo que vuelva a pedir lo mismo, y si lo pide distinto hay que
    volver a aprobar.

    Aquí no hay modelo en medio: se ejecuta lo que está en la fila, que es
    literalmente lo que leíste antes de decir que sí. Es más fiel a la
    aprobación, no menos.

    ## Los límites, que son los que importan
    - Solo tools de **nivel 3**: son las únicas que generan aprobaciones. Una
      tool de otro nivel por aquí sería saltarse la puerta que decidió el nivel.
    - **De un solo uso**: se gasta el token al ejecutarlo. Si la tool falla, el
      permiso se gastó igual —reintentar es volver a la cola, a propósito.
    - La tool vuelve a pasar por **sus** guardarraíles (whitelist, secretos,
      rollback de sintaxis, ficha completa): ejecutar no salta ninguno.
    - Exige `X-Aegis-Token`, como todo lo que concede poder.

    Y queda escrito en `data/logs/runs/aprobacion-{id}.jsonl`, con el mismo
    formato que los runs, porque una escritura sin rastro no es una ejecución: es
    un accidente con buena pinta.
    """
    from . import autonomy as auto_mod
    from .autopilot import ToolNotAllowed, _execute

    fila = auto_mod.almacen().buscar(pet_id)
    if not fila:
        raise HTTPException(status_code=404, detail=f"no hay ninguna petición '{pet_id}'")
    if fila["estado"] == "gastada":
        raise HTTPException(status_code=409, detail="ese permiso ya se usó")
    if fila["estado"] != "aprobada":
        raise HTTPException(
            status_code=409,
            detail=f"esa petición está {fila['estado']}: no hay nada aprobado que ejecutar")
    tool = fila["tool"]
    if auto_mod.nivel_de(tool) != "requiere_ok":
        # Por aquí solo pasan tools de nivel 3. Cualquier otra cosa sería
        # ejecutar saltándose la puerta que decidió su nivel.
        raise HTTPException(
            status_code=400,
            detail=f"'{tool}' no es de nivel 3, así que no necesita aprobación: "
                   "pasa por su nivel normal, no por la cola")
    try:
        argumentos = json.loads(fila["argumentos"] or "{}")
    except ValueError:
        raise HTTPException(status_code=500,
                            detail="los argumentos guardados no son JSON legible") from None
    if not isinstance(argumentos, dict):
        raise HTTPException(status_code=500,
                            detail="los argumentos guardados no son un objeto")

    token = fila["token"]
    gastado = auto_mod.almacen().gastar(token)
    if not gastado:
        raise HTTPException(status_code=409,
                            detail="ese permiso se gastó en otro sitio a la vez")

    # La ejecución va en un hilo y la respuesta sale **ya**. La razón está
    # escrita en `_ejecutar_aprobacion_en_segundo_plano`: una tool de nivel 3
    # puede ser la puerta completa del despliegue, que son minutos, y el cliente
    # del móvil se cansa a los 10 s. Aquí se canseba antes.
    asyncio.get_running_loop().run_in_executor(
        None, _lanza_ejecucion, pet_id, fila, tool, argumentos)

    return {"id": pet_id, "tool": tool, "estado": "en_curso",
            "detalle": "la llamada arranca ya; el rastro y el aviso confirman al "
                       "terminar",
            "proyecto": fila["proyecto"]}


def _ejecutar_aprobacion_en_segundo_plano(pet_id: str, fila: dict, tool: str,
                                          argumentos: dict) -> None:
    """Ejecuta la llamada aprobada y deja el rastro, sin retener la respuesta.

    ## Por qué esto está en un hilo y no awaited
    Medido (A-066): `install_apk` no es una llamada, es **la puerta completa** —
    `flutter analyze`, `flutter test` y el humo en el emulador, que en esta
    máquina son minutos. Con `/ejecutar` esperando, el móvil se cansaba a los 10 s de
    su `receiveTimeout` y pintaba «No pude ejecutar», con el token ya gastado y
    la instalación a medias de hacer: un gesto que se hizo bien y se cuenta como
    fallido.

    Es el mismo argumento que ya está escrito en `POST /deploys/{id}/instalar`
    («si se bloqueara la respuesta, pulsar "sí" se sentiría como la app colgada, y
    quien aprueba desde el móvil no tiene a nadie a quien preguntarle qué pasó»).
    Estaba aplicado a un endpoint y no al otro, que es justo el modo de fallo que
    estas lecciones persiguen.

    ## Y qué se pierde, dicho claro
    La respuesta ya no trae el `result` de la tool. Viene con
    `estado: "en_curso"`, y el desenlace se lee del JSONL y del aviso. Es una
    pérdida real y es el precio: una tool de nivel 3 puede tardar lo que quiera, y
    un HTTP no puede quedarse abierto ese tiempo sin que el cliente lo lea como
    un fallo.
    """
    # El import va aquí y no arriba del módulo: `ToolNotAllowed` y `_execute`
    # viven en `app.autopilot`, que importa el `main` (a través de memoria). Sin
    # este import la función moría con `NameError` **en el hilo**, después de
    # haber gastado el permiso y de haber contestado al móvil: el peor sitio
    # posible, porque el cliente ya tiene su respuesta y no hay nadie mirando.
    from .autopilot import ToolNotAllowed, _execute
    from .deploy import avisar_fallo_telefono, avisar_telefono, avisar_trabajando

    # «En marcha» antes de empezar. Antes solo se avisaba del fallo, así que una
    # operación que salía bien terminaba **muda**: el aviso pedía tu OK, lo dabas,
    # y a partir de ahí Aegis no te decía nada. Un canal que solo avisa de que
    # algo va mal es peor que no tener canal, porque entrena a ignorar el que sí
    # habla.
    avisar_trabajando(pet_id, f"ejecutando {tool}")

    ok, resultado, error = True, "", ""
    try:
        resultado = _execute(tool, argumentos)
    except ToolNotAllowed as exc:
        ok, error = False, str(exc)
    except Exception as exc:  # noqa: BLE001 — el motivo se queda escrito
        ok, error = False, f"{type(exc).__name__}: {exc}"[:500]
    if ok and any(resultado.startswith(m) for m in _MOTIVOS_DE_RECHAZO):
        ok = False
        error = resultado[:500]
    _escribir_jsonl_de_aprobacion(pet_id, fila, argumentos, resultado, ok, error)
    log.info("aprobacion %s: %s terminó (ok=%s): %s",
             pet_id, tool, ok, resultado[:200])
    # El desenlace va al aviso **solo si** esta ruta no publica el suyo. Una
    # instalación avisa desde `instalar_en_telefono`, que es quien sabe que `adb`
    # salió bien; si avisáramos aquí también, «instalado» podría llegar antes que
    # «en marcha» y la bandeja terminaría diciendo que está instalando algo que ya
    # terminó.
    if not _avisa_por_si_mismo(tool):
        if ok:
            avisar_telefono({"id": pet_id, "razon": f"{tool} hecho"})
        else:
            avisar_fallo_telefono(pet_id, error or resultado[:300])


def _lanza_ejecucion(pet_id: str, fila: dict, tool: str, argumentos: dict) -> None:
    """El `run_in_executor` de verdad: un hilo cuyo fallo **no se propaga**.

    ## Por qué hace falta y no es paranoia
    Un `run_in_executor` entrega el callable a un hilo del pool: si ese callable
    lanza, la excepción se queda en ese hilo y **nadie la ve**. Ni el móvil —que
    ya recibió su respuesta y se le dijo que empezó—, ni los tests, que solo
    miran la respuesta HTTP.

    Pasó de verdad al escribir esto: la función usaba `ToolNotAllowed` sin
    importarlo (el import estaba dentro del endpoint) y moría con `NameError`
    **después** de gastar el permiso y de contestar. El móvil tenía un «en curso»,
    no pasaba nada, y no había error en ninguna parte.

    ## Por qué el aviso al teléfono y no solo el log
    Un log que nadie mira no arregla un gesto que alguien hizo a distancia. El
    aviso es lo mismo que usa `POST /deploys/{id}/instalar`: si no se puede
    cumplir, se dice en el móvil, que es el único sitio donde quien aprobó puede
    enterarse.
    """
    try:
        _ejecutar_aprobacion_en_segundo_plano(pet_id, fila, tool, argumentos)
    except Exception as exc:  # noqa: BLE001 — un hilo no puede propagar y punto
        log.exception("la ejecución de la aprobación %s (%s) murió sin dejar "
                      "rastro", pet_id, tool)
        detalle = f"no pude ejecutar {tool}: {type(exc).__name__}: {exc}"[:300]
        try:
            _escribir_jsonl_de_aprobacion(pet_id, fila, argumentos, detalle,
                                          False, detalle)
        except Exception:  # noqa: BLE001 — ya estamos en el camino del fallo
            log.exception("además no pude escribir el rastro de %s", pet_id)
        try:
            from .deploy import avisar_fallo_telefono
            avisar_fallo_telefono(pet_id, detalle)
        except Exception:  # noqa: BLE001 — el aviso es lo último que puede fallar
            log.exception("además no pude avisar del fallo de %s", pet_id)


def _escribir_jsonl_de_aprobacion(pet_id: str, fila: dict, argumentos: dict,
                                  resultado: str, ok: bool, error: str) -> None:
    """La ejecución de una aprobación, en el mismo formato que un run.

    Mismo formato a propósito: dos formatos para lo mismo obligan a dos lectores,
    y uno de los dos miente un día.
    """
    import datetime as _dt
    d = _runs_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        ahora = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")
        with (d / f"aprobacion-{pet_id}.jsonl").open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": ahora, "run_id": f"aprobacion-{pet_id}",
                "event": "task.created", "agent": "aprobacion", "at_run": fila["run_id"],
                "payload": {"project": fila["proyecto"], "tool": fila["tool"],
                            "arguments": argumentos, "origen": "aprobacion.ejecutar"},
            }, ensure_ascii=False) + "\n")
            fh.write(json.dumps({
                "at": ahora, "run_id": f"aprobacion-{pet_id}",
                "event": "tool.completed", "agent": "aprobacion", "at_run": fila["run_id"],
                "payload": {"tool": fila["tool"], "ok": ok, "step": 1},
            }, ensure_ascii=False) + "\n")
            fh.write(json.dumps({
                "at": ahora, "run_id": f"aprobacion-{pet_id}",
                "event": "task.done" if ok else "task.failed",
                "agent": "aprobacion", "at_run": fila["run_id"],
                "payload": {"steps": 1, "fin": "aprobacion.ejecutar",
                            "answer": resultado[:2000], "error": error},
            }, ensure_ascii=False) + "\n")
    except OSError as exc:  # noqa: BLE001 — no tumbar la ejecución por el log
        log.warning("no pude escribir la traza de %s: %s", pet_id, exc)


def _escribir_jsonl_de_autopilot(run_id: str, project: str,
                                  result: dict[str, Any]) -> None:
    """Deja la traza de un run de autopilot en `data/logs/runs/{run_id}.jsonl`.

    ## Por qué hace falta
    `relay.run_event` escribe el JSONL de los runs de **Hermes**. Los de
    autopilot no pasaban por ahí, así que su rastro solo vivía en
    `_AUTOPILOT_RUNS`, un dict en memoria con tope de 50. Consecuencia medida:
    `GET /runs` no encontraba los runs de autopilot, y reiniciar el bridge los
    perdía. No era que faltara un endpoint: faltaba **escribir**.

    ## Por qué el formato es el de `leer_run`
    Porque el que ya existe. Un segundo formato para lo mismo obligaría a tener
    dos lectores y a que uno de los dos mienta un día.
    """
    d = _runs_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        ahora = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="milliseconds")
        with (d / f"{run_id}.jsonl").open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": ahora, "run_id": run_id, "event": "task.created",
                "agent": "autopilot", "at_run": "",
                "payload": {"project": project, "model": result.get("model", "")},
            }, ensure_ascii=False) + "\n")
            for paso in result.get("trace") or []:
                if not paso.get("tool"):
                    continue
                fh.write(json.dumps({
                    "at": ahora, "run_id": run_id, "event": "tool.completed",
                    "agent": "autopilot", "at_run": "",
                    "payload": {"tool": paso["tool"], "ok": paso.get("ok"),
                                "step": paso.get("step")},
                }, ensure_ascii=False) + "\n")
            # Antes era `"s": 0.0` **hardcodeado**, con la forma de metric lista
            # para recibir el numero. Es decir: el hueco estava excavado y
            # plantado. `docs/motores.md` §1.3 lo senala como el hecho que
            # bloquea los presupuestos de latencia, y era verdad — un informe de
            # duraciones sobre estos ficheros decia "todos los runs duraron 0
            # segundos", que es un numero, y por eso no se nota que es falso.
            fh.write(json.dumps({
                "at": ahora, "run_id": run_id, "metric": "run_duration_s",
                "s": float(result.get("duracion_s") or 0.0),
            }, ensure_ascii=False) + "\n")
            # El evento terminal tiene que ser uno del vocabulario
            # (`task.done`/`task.failed`/`task.stopped`) y el motivo va en el
            # payload. Escribir `task.max_steps` como evento deja el run en
            # "desconocido" para todo el que lo lea, y el motivo de cierre es
            # un dato, no un tipo de evento.
            #
            # Y el mapeo se declara **completo**, no con un `.get(..., done)`
            # que manda todo lo desconocido a "terminado bien". Ese default era
            # una mentira administrativa: un run que reventaba se guardaba como
            # `task.done`, y cualquier informe que contara runs bien terminados
            # contaba también los que se cayeron por el camino.
            fin = result.get("fin") or "sin_tools"
            # Si el veredicto viene, se respeta; si no, se calcula. La
            # diferencia importa: `run_autopilot` ya lo calculó con la traza
            # entera y recalcularlo aquí daría un número distinto (la traza
            # escrita va recortada). Pero un `result` sin veredicto —un test,
            # o un llamador que no pasa por el bucle— no debe grabarse como
            # `incompleto` por un campo que no ha llegado. Ausente no es
            # "fracaso": es "que lo mire quien lo lee".
            estado = result.get("estado")
            if not estado:
                from .veredicto import clasificar as _clasificar
                estado = _clasificar(fin, result.get("trace") or [],
                                     result.get("answer") or "")["estado"]
            if fin in ("failed", "modelo_caido", "reventado", "verificador_rojo",
                       "llamada_repetida"):
                terminal = "task.failed"
            elif fin in ("esperando_ok", "parado"):
                terminal = "task.stopped"
            else:
                terminal = "task.done"
            # El **veredicto** va en el terminal, y no se recalcula aquí: lo
            # calculó `autopilot.run_autopilot` con la traza entera, y
            # recalcularlo sobre lo que se acaba de escribir (tools recortadas,
            # `answer` a 1.000 chars) daría un número distinto al del run real.
            #
            # Va también en el `event`, porque el que cuenta runs terminados
            # mira ahí y no va a parsear el payload: `task.done` con
            # `estado: incompleto` es un run que se paró sin responder, y leerlo
            # como "terminó bien" era exactamente el error que A-091
            # documenta en el otro sentido.
            if estado == "completado":
                terminal = "task.done"
            elif estado in ("incompleto", "roto", "rechazado"):
                terminal = "task.failed"
            fh.write(json.dumps({
                "at": ahora, "run_id": run_id, "event": terminal,
                "agent": "autopilot", "at_run": "",
                # El error va en su propio campo y no metido dentro del
                # `answer`: un run que falló tiene que poder localisation con un
                # `jq '.payload.error'` y no leyendo prosa.
                "payload": {"steps": result.get("steps", 0), "fin": fin,
                            "estado": estado,
                            "completado": bool(result.get("completado")),
                            "resumen": (result.get("resumen") or "")[:200],
                            "error": (result.get("error") or "")[:500],
                            "answer": (result.get("answer") or "")[:1000]},
            }, ensure_ascii=False) + "\n")
    except OSError as exc:
        # El run ya terminó: que el rastro falle no debe tumbarlo, pero sí
        # tiene que quedar dicho, porque un rastro que falla en silencio es
        # un historial que miente.
        log.warning("autopilot %s: no pude escribir el JSONL del run: %s", run_id, exc)
