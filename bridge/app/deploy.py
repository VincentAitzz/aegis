"""La puerta de despliegue: no se toca el teléfono sin pasar por aquí.

## Qué protege

El usuario trabaja con el móvil en la mano. Si Aegis instala y **lanza** la app
encima a mitad de otra cosa, lo interrumpe. Y lo peor no es la interrupción: es
que Aegis no avise y aun así reporte éxito.

Así que `install_apk(target="telefono")` hace tres cosas, en este orden, y se
niega en la primera que falle:

1. **Verificación real**: `flutter analyze`, `flutter test`, y un **humo en el
   emulador** que además comprueba que la app habla con el bridge. Nada de
   "creo que compila": el gate lo corre.
2. **Autorización de un solo uso**: alguien tiene que haber aprobado *esta*
   instalación desde el móvil. Sin eso no hay instalación, y se manda un aviso
   al teléfono para que no se entere después.
3. **Solo entonces** instala. Y **lanzar** es un paso aparte, porque instalar sin
   abrir la app molesta mucho menos.

## Por qué el emulador

`infra/mobile/emulador.sh` levanta un AVD que replica el galaxy a17: Android 16,
1080x2340, 450 dpi. Misma versión de Android y misma geometría hacen que una
prueba de layout signifique algo, y no interrumpe a nadie. La ABI no se replica:
el teléfono es arm64 y esta máquina es x86_64.

## La cabecera de origen

El emulador y el teléfono llegan al bridge los dos por `adb reverse`, así que los
dos aparecen como `127.0.0.1` y son indistinguibles en el log. La app manda
`X-Aegis-Origen` y el bridge lo registra: eso permite demostrar que el humo vino
del emulador, y de paso responde a la pregunta de fondo — *¿cuándo tocó Aegis mi
teléfono?* — con un log, no con una conjetura.
"""

import json
import os
import time
import uuid

import httpx
from pathlib import Path

from . import dispositivos as disp

MOBILE = Path(os.path.expanduser("~/Workspace/aegis/mobile"))
#: El APK que se prueba en el emulador. El del teléfono es otro binario, con la
#: IP de la tailnet en vez de localhost, y vive en `APK_TELEFONO`.
APK = disp.apk_para("emulador")
APK_TELEFONO = disp.apk_para("telefono")
FLUTTER = disp.FLUTTER
PAQUETE = "com.aegis.aegis_console"
ORIGEN_HEADER = "X-Aegis-Origen"

#: El bridge, para preguntar por el registro de orígenes. El MCP corre en otro
#: proceso, así que esto no puede ser una variable en memoria.
BRIDGE_URL = os.environ.get("AEGIS_BRIDGE_URL", "http://127.0.0.1:8000")


class PuertaCerrada(ValueError):
    """No se pasa. El mensaje dice qué faltó y qué hacer."""


# -- 1. Verificación ---------------------------------------------------------

def verificar_analisis() -> tuple[bool, str]:
    proc = disp.subprocess.run([f"{FLUTTER}/flutter", "analyze", "--no-pub"],
                               capture_output=True, text=True, cwd=str(MOBILE),
                               timeout=600)
    salida = (proc.stdout + proc.stderr).strip()
    limpio = proc.returncode == 0
    if limpio:
        return True, "flutter analyze: sin problemas"
    ultimo = [l for l in salida.splitlines() if l.strip()][-1:] or ["(sin detalle)"]
    return False, f"flutter analyze: {ultimo[0][:200]}"


def verificar_tests() -> tuple[bool, str]:
    proc = disp.subprocess.run([f"{FLUTTER}/flutter", "test"],
                               capture_output=True, text=True, cwd=str(MOBILE),
                               timeout=1800)
    salida = (proc.stdout + proc.stderr).strip()
    ok = proc.returncode == 0
    resumen = [l for l in salida.splitlines() if "All tests passed" in l
               or "tests passed" in l or "Some tests failed" in l
               or "No tests" in l]
    return ok, "flutter test: " + (resumen[-1].strip()[:120] if resumen
                                  else ("OK" if ok else "falló"))


# -- 2. Humo en el emulador --------------------------------------------------

def _hubo_llamada_de(origen: str, desde: float) -> bool:
    """¿El bridge vio una llamada de ese origen desde `desde`?

    Se pregunta **por HTTP** y no por memoria a propósito: el MCP de `aegis-ops`
    corre como un proceso aparte del bridge FastAPI, así que un registro en
    memoria aquí estaría siempre vacío y el humo fallaría siempre — un fallo
    que se ve solo cuando ya está desplegado.

    Mirar el access log tampoco sirve: el emulador y el teléfono llegan los dos
    por `adb reverse` y los dos se ven como `127.0.0.1`. De ahí la cabecera.
    """
    try:
        r = httpx.get(f"{BRIDGE_URL}/origen", timeout=10)
        ultimo = (r.json() or {}).get("ultimo") or {}
        return float(ultimo.get(origen, 0.0)) >= desde
    except Exception:  # noqa: BLE001 — sin bridge no hay humo, y eso ya se dirá
        return False


def humo_emulador(origen_registrado=_hubo_llamada_de) -> tuple[bool, str]:
    """Instala, lanza y comprueba que la app del emulador habla con el bridge.

    `origen_registrado(origen, desde_epoch)` es la función que dice si el bridge
    ha visto una petición de ese origen desde ese instante. Se puede inyectar
    para probar la lógica sin tocar un dispositivo.
    """
    dev = disp.emulador()
    if dev is None:
        return False, ("el emulador no está corriendo. Arráncalo con "
                       f"`bash {disp.EMULATOR_SCRIPT} arrancar`")
    if not APK.exists():
        return False, (f"no hay APK del emulador ({APK}). "
                       "Compila con build_apk(target='emulador'):"
                       " el que se prueba aquí es el que habla por localhost.")

    antes = time.time()
    code, out = disp._adb(["install", "-r", str(APK)], timeout=600, serial=dev.serial)
    if code != 0:
        return False, f"install en el emulador falló (exit={code}): {out[:160]}"
    disp._adb(["reverse", "tcp:8000", "tcp:8000"], timeout=60, serial=dev.serial)

    momento = time.time()
    disp._adb(["shell", "am", "force-stop", PAQUETE], timeout=60, serial=dev.serial)
    disp._adb(["shell", "am", "start", "-n", f"{PAQUETE}/.MainActivity"],
              timeout=90, serial=dev.serial)

    # La app pide /health y /proyectos al arrancar. Se le da margen: en un
    # emulador sin KVM suficiente esto tarda, y un humo que falla por impaciencia
    # teaches a ignorar la puerta.
    hablo = False
    for _ in range(20):
        time.sleep(2)
        if origen_registrado("emulador", antes):
            hablo = True
            break
    pid = disp._adb(["shell", "pidof", PAQUETE], timeout=60,
                    serial=dev.serial)[1].strip()
    vivo = bool(pid)
    limpio = vivo and hablo
    if limpio:
        return True, (f"humo: app viva (pid={pid.split()[0]}) y el bridge recibió "
                      f"una llamada marcada 'emulador'")
    if not vivo:
        return False, f"el proceso no arrancó en el emulador (pid='{pid}')"
    if not hablo:
        return False, ("la app arrancó pero el bridge no recibió ninguna llamada "
                       "marcada 'emulador'. ¿Compilaste con target='emulador' "
                       "(API_HOST=localhost)?")
    return False, "estado inesperado en el humo"


_HUMO = {}
"""Veredictos de humo ya pagados, por APK. Un fallo nunca se cachea."""


def huella_apk() -> str:
    """Identifica el binario, no su nombre.

    `app-debug.apk` es siempre el mismo fichero: se sobrescribe en cada
    compilación. Dos APKs distintos se distinguen por tamaño y mtime, que es lo
    que importa para decidir si el humo anterior sigue sirviendo.
    """
    try:
        st = APK.stat()
    except OSError:
        return "sin-apk"
    return f"{st.st_size}-{int(st.st_mtime)}"


def humo_una_vez(max_edad: int = 1800) -> tuple[bool, str]:
    """Como `humo_emulador()`, pero sin repetir el trabajo para el mismo APK.

    ## Por qué existe
    La puerta corre **dos** veces en una instalación real: al pedir autorización
    y al volver ya aprobado. El humo cuesta alrededor de un minuto (instala,
    arranca y espera a que la app hable). Repetirlo para el mismo binario solo
    alarga la espera del usuario.

    ## Por qué solo los aciertos
    Un fallo cacheado sería una puerta que se auto-cierra y ya no deja
    reintentar, que es justo lo contrario de lo que sirve. Un acierto cacheado,
    en cambio, es un hecho: aquel APK arrancó y habló con el bridge. Si el
    fichero cambia, la huella cambia, y el humo vuelve a correr.

    ## Su alcance: el proceso, no el disco
    El veredicto vive en memoria, porque quien pide la puerta es el MCP, que es
    un proceso de larga vida: pedir autorización y volver ya aprobado pasan por
    el mismo. Un proceso nuevo paga el humo otra vez, y con un APK de 170 MB y un
    emulador ya caliente son unos segundos. Preferible a guardar en disco un
    "ya pasó" que sobreviva a un cambio que nadie midió.
    """
    clave = huella_apk()
    previo = _HUMO.get(clave)
    if previo and time.time() - previo[0] < max_edad:
        return True, previo[1] + f" (humo ya verificado, hace {int(time.time() - previo[0])}s)"
    ok, detalle = humo_emulador()
    if ok:
        _HUMO.clear()
        _HUMO[clave] = (time.time(), detalle)
    return ok, detalle


# -- 3. Autorización de un solo uso ------------------------------------------

class _Estado:
    """Peticiones de despliegue y tokens, compartidos entre dos procesos.

    ## Por qué a disco y no en memoria

    El MCP de `aegis-ops` corre como **proceso aparte** del bridge FastAPI, y el
    móvil habla con el bridge. Con el estado en memoria, la petición la creaba un
    proceso y la leía otro: el móvil nunca enseñaría el botón de aprobar y
    `install_apk` esperaría una aprobación que nadie puede dar.

    Es la misma trampa que el registro de orígenes en A-020: **dos procesos, un
    solo estado**. Se escribe atómicamente porque los dos pueden tocarlo.

    ## Por qué no por HTTP

    El estado dura minutos y lo leen dos procesos. Un fichero de un kilobyte es
    más simple que acoplar el MCP al bridge por red; si mañana el estado pasa a
    importar de verdad, este es el único sitio que hay que cambiar.
    """

    RUTA = Path(os.path.expanduser("~/Workspace/aegis/bridge/data/deploy.json"))

    def __init__(self) -> None:
        self.RUTA.parent.mkdir(parents=True, exist_ok=True)

    def _leer(self) -> dict:
        try:
            return json.loads(self.RUTA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"peticiones": {}, "tokens": {}}

    def _escribir(self, datos: dict) -> None:
        tmp = self.RUTA.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.RUTA)

    def limpiar(self) -> None:
        self._escribir({"peticiones": {}, "tokens": {}})

    # -- operaciones, con nombre en vez de diccionario a pelo --
    def nueva(self, peticion: dict) -> None:
        d = self._leer(); d["peticiones"][peticion["id"]] = peticion; self._escribir(d)

    def peticion(self, pet_id: str) -> dict:
        return self._leer()["peticiones"].get(pet_id, {})

    def pon(self, pet_id: str, **campos) -> dict:
        d = self._leer()
        d["peticiones"].setdefault(pet_id, {}).update(campos)
        self._escribir(d)
        return d["peticiones"][pet_id]

    def todas_las_peticiones(self) -> dict:
        return self._leer()["peticiones"]

    def nuevo_token(self, token: str, datos: dict) -> None:
        d = self._leer(); d["tokens"][token] = datos; self._escribir(d)

    def token(self, token: str) -> dict | None:
        return self._leer()["tokens"].get(token)

    def gasta_token(self, token: str) -> dict | None:
        d = self._leer()
        t = d["tokens"].get(token)
        if t is None:
            return None
        t["gastado"] = True
        self._escribir(d)
        return t

    def todos_los_tokens(self) -> dict:
        return self._leer()["tokens"]


ESTADO = _Estado()


def pedir_deploy(razon: str, lanzar: bool = False) -> dict:
    """Deja la petición pendiente y avisa al teléfono. No instala nada."""
    pet_id = f"deploy-{uuid.uuid4().hex[:10]}"
    peticion = {
        "id": pet_id, "estado": "pendiente", "razon": razon[:300],
        "lanzar": bool(lanzar), "creado": time.time(),
    }
    peticion["aviso"] = avisar_telefono(peticion)
    ESTADO.nueva(peticion)
    return peticion


def avisar_telefono(peticion: dict) -> str:
    """Notificación en el teléfono: hay un despliegue esperando aprobación.

    Sin Google Play services en la app, no hay FCM. Se usa la vía del shell,
    que ya se comprobó que llega: `cmd notification post`. Es un aviso local, así
    que solo suena si adb está conectado — que es justo cuando Aegis está
    trabajando.
    """
    dev = disp.telefono()
    if dev is None:
        return "no pude avisar: tu teléfono no está conectado por adb"
    titulo = "AEGIS · despliegue listo"
    cuerpo = (f"{peticion['razon']}\n"
              f"{'Instalar y abrir' if peticion['lanzar'] else 'Solo instalar'}"
              f" · id={peticion['id']}\nAbre la app para aprobar.")
    code, out = disp._adb(
        # La firma es `post [-t <título>] <tag> <texto>`: el `-t` es el título y
        # el primer posicional es el TAG. Con los tres en el orden equivocado el
        # aviso sale con el tag de título y el título de texto, y parece que
        # funciona cuando no dice nada.
        ["shell", "cmd", "notification", "post", "-S", "bigtext",
         "-t", disp.shell_quote(titulo), "aegis", disp.shell_quote(cuerpo)],
        timeout=60, serial=dev.serial)
    return "aviso enviado" if code == 0 else f"aviso falló (exit={code}): {out[:120]}"


def aprobar(pet_id: str, decision: str = "aprobar") -> dict:
    """Resuelve una petición. `aprobar` devuelve un token de un solo uso."""
    p = ESTADO.peticion(pet_id)
    if not p:
        raise PuertaCerrada(f"no hay ninguna petición con id '{pet_id}'")
    if decision not in ("aprobar", "denegar"):
        raise PuertaCerrada("decision debe ser 'aprobar' o 'denegar'")
    # Se guarda el estado en pasado, no el verbo de la decisión: antes se
    # guardaba "aprobar" y se buscaba "aprobada", así que una aprobación
    # aprobada no se encontraba y la puerta se cerraba siempre. Lo que se
    # devuelve y lo que se guarda tienen que ser lo mismo.
    estado = "aprobada" if decision == "aprobar" else "denegada"
    ESTADO.pon(pet_id, estado=estado)
    if estado == "aprobada":
        token = uuid.uuid4().hex[:16]
        ESTADO.nuevo_token(token, {"id": p["id"], "razon": p["razon"],
                                   "lanzar": p["lanzar"], "gastado": False,
                                   "creado": time.time()})
        ESTADO.pon(pet_id, token=token)
        return {"estado": estado, "token": token}
    return {"estado": estado}


def gastar_token(token: str) -> dict:
    """Canjea un token. Un token, una instalación: si ya se gastó, se niega."""
    # Primero se mira, después se gasta. Al revés, un token reusado se gastaría
    # dos veces y la puerta dejaría de ser de un solo uso.
    t = ESTADO.token(token)
    if t is None:
        raise PuertaCerrada(
            "ese token no existe. Pide una instalación de nuevo: la autorización "
            "es de un solo uso y caduca.")
    if t.get("gastado"):
        raise PuertaCerrada("ese token ya se usó. Pide otra aprobación.")
    ESTADO.gasta_token(token)
    return t


def pendientes() -> list[dict]:
    return [p for p in ESTADO.todas_las_peticiones().values()
            if p.get("estado") == "pendiente"]


# -- La puerta completa ------------------------------------------------------

def pasar_puerta_deploy(lanzar: bool = False) -> str:
    """Todo lo que tiene que estar en verde antes de tocar el teléfono.

    Devuelve `"ok"` o lanza `PuertaCerrada` con el motivo. Se comprueba aquí, no
    se acepta que el agente diga que comprobó.
    """
    dev = disp.telefono()
    if dev is None:
        raise PuertaCerrada(
            "tu teléfono no está conectado por adb, así que no puedo instalar. "
            "Las pruebas siguen bien: van al emulador, que replica el galaxy a17.")
    ok, detalle = verificar_analisis()
    if not ok:
        raise PuertaCerrada(f"analyze en rojo, no instalo:\n  {detalle}")
    ok, detalle = verificar_tests()
    if not ok:
        raise PuertaCerrada(f"los tests fallan, no instalo:\n  {detalle}")
    ok, detalle = humo_una_vez()
    if not ok:
        raise PuertaCerrada(
            "el humo en el emulador no pasa, así que no instalo en tu teléfono. "
            f"Prueba primero ahí, que no interrumpe a nadie:\n  {detalle}")
    # El APK del teléfono lleva la dirección del bridge dentro. Si el teléfono no
    # la alcanza, la app instala, abre y no ve nada: sin error y sin aviso.
    try:
        host = disp.api_host_para("telefono")
    except disp.DeviceError as exc:
        raise PuertaCerrada(f"no sé a qué dirección apunta el APK del teléfono. {exc}")
    ok, detalle = disp.telefono_alcanza(host)
    if not ok:
        raise PuertaCerrada(
            "instalarlo ahora sería instalar una app que no ve el bridge:\n"
            f"  {detalle}")
    return dev.serial


def es_primera_instalacion(dev) -> bool:
    """¿La app está o no está en ese teléfono?

    Lo consulta `install_apk` **antes** de decidir si pide autorización, y no solo
    `instalar_en_telefono`: la tool soltaba una petición de aprobación y volvía
    sin llegar a instalar, así que la excepción de la primera vez —que existe
    porque el botón de aprobar vive en la app que aún no está— nunca se activaba
    por el camino de la tool. Dos sitios decidiendo lo mismo, uno de ellos
    inalcanzable.
    """
    return not disp.instalado(dev)


def buscar_aprobacion(lanzar: bool = False) -> dict | None:
    """La aprobación viva más reciente que cubre esta instalación, si existe.

    Existe para que **el agente no llegue a manejar el token**. Approbar desde
    el móvil deja aquí un token de un solo uso; Aegis solo tiene que volver a
    llamar a `install_apk`. Si el token anduviera en manos del agente, bastaría
    con que se lo imprimiera una vez para que la puerta dejara de existir.
    """
    candidatas = [p for p in ESTADO.todas_las_peticiones().values()
                 if p.get("estado") == "aprobada"]
    candidatas.sort(key=lambda p: p.get("creado", 0), reverse=True)
    for p in candidatas:
        tok = p.get("token")
        if tok and not (ESTADO.token(tok) or {}).get("gastado"):
            if p.get("lanzar") == lanzar:
                return {"token": tok, "peticion": p}
    return None


def instalar_en_telefono(dev, token: str = "", lanzar: bool = False) -> str:
    """Instala en el teléfono. Sin token explícito, usa la aprobación más reciente.

    ## La primera vez no hace falta que apruebes nada
    El botón de aprobación **está dentro de la app**. Si instalar exigiera
    aprobación, y la aprobación estuviera en la app, no habría forma de instalar
    nunca: se pediría una autorización que solo se puede dar con algo que todavía
    no está instalado. Es un deadlock, y se resolvió quitándole el problema en vez
    de añadir una puerta más.

    Lo que protege la puerta es **no interrumpirte mientras usas la app**, y un
    paquete que no está instalado no interrumpe nada. Por eso la excepción es
    solo para la primera instalación, y sigue exigiendo:

    - que la llames nombrando `target='telefono'`, sin valor por defecto;
    - que analyze, los tests y el humo en el emulador estén en verde;
    - que **no se abra** la app al instalarla.

    En cuanto el paquete está presente, la puerta vuelve a ser completa.
    """
    primera_vez = not disp.instalado(dev)
    if not token and not primera_vez:
        ap = buscar_aprobacion(lanzar=lanzar)
        if ap is None:
            raise PuertaCerrada(
                "no hay ninguna aprobación vigente para esta instalación. "
                "Pídela con install_apk(target='telefono') y apruébala en el móvil.")
        token = ap["token"]
    if not APK_TELEFONO.exists():
        raise PuertaCerrada(
            f"no hay APK del teléfono ({APK_TELEFONO}). El que se prueba en el "
            "emulador no sirve aquí: apunta a localhost. Compila antes con "
            "build_apk(target='telefono').")
    t = {"lanzar": False} if primera_vez else gastar_token(token)
    code, out = disp._adb(["install", "-r", str(APK_TELEFONO)], timeout=600,
                          serial=dev.serial)
    if code != 0:
        # Si falla, el token no se devuelve: el intento falló y el usuario no
        # pidió más de una cosa.
        raise PuertaCerrada(f"install falló (exit={code}): {out[:200]}")
    partes = [f"instalado en {dev.serial}"]
    if primera_vez:
        partes.append("primera instalación: no hacía falta tu autorización porque "
                      "el botón para aprobar vive en la app que aún no estaba. "
                      "A partir de ahora, instalar sí te pregunta.")
    if lanzar and t.get("lanzar"):
        scode, sout = disp._adb(
            ["shell", "am", "start", "-n", f"{PAQUETE}/.MainActivity"],
            timeout=90, serial=dev.serial)
        partes.append(f"abierto (exit={scode})")
    else:
        partes.append("NO se abrió la app: instalar no es lo mismo que lanzar")
    return "\n".join(partes)


def snapshot() -> dict:
    """Estado de la puerta, para poder mirarlo desde fuera."""
    return {
        "emulador": bool(disp.emulador()),
        "telefono": bool(disp.telefono()),
        "pendientes": pendientes(),
        "tokens_vivos": sum(1 for t in ESTADO.todos_los_tokens().values()
                           if not t.get("gastado")),
    }