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
   instalación desde el móvil. Sin eso no hay instalación. El aviso de que falta
   la autorización va al **emulador**, no al teléfono: se repite en cada
   reintento y no es cosa tuya hasta que la decisión está tomada.
3. **Solo entonces** instala. Y **lanzar** es un paso aparte, porque instalar sin
   abrir la app molesta mucho menos.

## Un aviso, y uno solo

Al teléfono real solo le llega **una** notificación: la de "ya está instalado",
justo después de instalar. Todo lo demás —petición de aprobación, estado de la
puerta, humo— va al emulador, que es donde ocurre el trabajo.

El motivo es concreto: `pedir_deploy` se llama en cada `install_apk` sin
aprobación, y el agente reintenta. Con el aviso al teléfono real, una sesión de
trabajo normal llenaba el móvil de notificaciones sobre algo que todavía no
estaba decidido, y ninguna era accionable. Un aviso que llega cuando ya no hay
nada que decidir informa; el resto solo cansa.

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

#: El aviso que publica la propia app. Estos tres tienen que coincidir con
#: `NotificacionReceiver` (Kotlin) y con el filtro del manifest; si divergen, el
#: broadcast se pierde en el sistema y no hay error en ninguna parte.
ACCION_AVISAR = "com.aegis.aegis_console.AVISAR"
ID_AVISO = 4101

#: El bridge, para preguntar por el registro de orígenes. El MCP corre en otro
#: proceso, así que esto no puede ser una variable en memoria.
BRIDGE_URL = os.environ.get("AEGIS_BRIDGE_URL", "http://127.0.0.1:8000")

#: Dónde va el aviso **intermedio** cuando no hay teléfono a mano.
#:
#: Antes esto era fijo al emulador, y la razón era buena: el aviso de «falta tu
#: autorización» se repetía cada vez que el agente reintentaba `install_apk`, y
#: con la notificación vieja eso llenaba el móvil de avisos idénticos. El
#: teléfono llevaba la prueba; la prueba no es tuya.
#:
#: Ahora el aviso es **accionable** —se aprueba desde el móvil— así que va al
#: teléfono, y la razón de antes la resuelve otro sitio: la app publica **un
#: solo aviso con el número de pendientes** (mismo ID, se actualiza en sitio) y
#: el puente deduplica por motivo. Un aviso que se actualiza no se acumula.
#:
#: `AEGIS_AVISO_INTERMEDIO=emulador` lo devuelve al emulador, que es lo que
#: quiere quien está probando y no quiere que le suene el móvil.
AVISO_INTERMEDIO = os.environ.get("AEGIS_AVISO_INTERMEDIO", "telefono")

#: Ventana en la que dos avisos iguales se consideran el mismo aviso. Sin esto,
#: instalar tres veces seguidas en tres minutos son tres notificaciones y solo
#: hay una novedad.
VENTANA_AVISO = 300


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
    autorizado, por_que = el_token_llega(APK)
    limpio = vivo and hablo and autorizado
    if limpio:
        return True, (f"humo: app viva (pid={pid.split()[0]}), el bridge recibió "
                      f"una llamada marcada 'emulador' y el token de la API "
                      f"llega ({por_que})")
    if not autorizado:
        return False, (
            f"la app arrancó y habló con el bridge, pero su token de la API no "
            f"llega: {por_que}\n"
            f"Eso significa que este APK se compiló SIN el token. Abrir y "
            f"funcionar no son lo mismo, y /health no lo nota: solo lo notan las "
            f"secciones de autonomía, agenda y memoria, que devuelven 401.\n"
            f"Recompila con build_apk: si `AEGIS_API_KEY` está vacía en "
            f"bridge/.env, el token no viaja.")
    if not vivo:
        return False, f"el proceso no arrancó en el emulador (pid='{pid}')"
    if not hablo:
        return False, ("la app arrancó pero el bridge no recibió ninguna llamada "
                       "marcada 'emulador'. ¿Compilaste con target='emulador' "
                       "(API_HOST=localhost)?")
    return False, "estado inesperado en el humo"


def _sello_de_token(destino: Path) -> Path:
    """Dónde queda anotado con qué token se compiló un APK."""
    return destino.with_suffix(destino.suffix + ".token")


def _huella(valor: str) -> str:
    """Huella de la clave. Solo para comparar, nunca para autenticar."""
    import hashlib
    return hashlib.sha256(valor.encode()).hexdigest()[:16] if valor else ""


def anotar_token_del_apk(destino: Path, token: str) -> None:
    """Deja escrito con qué token se compiló este APK.

    Es lo que hace que el humo pueda distinguir "abrió" de "funciona" sin
    inventarse una comprobación. Sin este fichero, la única forma de saberlo
    sería desensamblar el APK, y eso no es un test de humo: es una auscultación.
    """
    try:
        _sello_de_token(destino).write_text(_huella(token) + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("no pude anotar el token de %s: %s", destino, exc)


def el_token_llega(destino: Path) -> tuple[bool, str]:
    """¿El APK de este destino se compiló con el token que hay puesto **ahora**?

    Compara la huella del token actual con la que `build_apk` anotó al compilar.
    Tres casos distintos, y son distintos de verdad:

    - **Sin clave puesta**: no hay puerta que probar. No se falla, porque exigir
      algo que no existe es inventar un fallo.
    - **Con sello y la huella coincide**: comprobado. El APK lleva la clave.
    - **Con clave pero sin sello, o la huella no coincide**: el APK se compiló
      antes de que la clave existiera, o con otra. Se falla, y el motivo lo dice.

    ## Por qué esto y no "abre y dibuja"
    Con la puerta activa, un APK sin token **arranca, pinta y habla con el
    bridge**: llama a `/health` y a `/proyectos`, que no lo exigen. Lo único que
    falla son autonomía, agenda y memoria, con un 401. Es A-039, y es el fallo
    que llega a producción sin que nadie lo note.
    """
    from .config import get_settings
    actual = get_settings().aegis_api_key
    if not actual:
        return True, "el bridge no exige token (AEGIS_API_KEY vacía)"
    sello = _sello_de_token(destino)
    if not sello.exists():
        return False, (
            f"hay clave puesta pero este APK se compiló sin anotar token. "
            f"Recompílalo con build_apk: una app sin token abre y dibuja bien, y "
            f"solo falla con 401 en autonomía, agenda y memoria")
    guardada = sello.read_text(encoding="utf-8").strip()
    if guardada != _huella(actual):
        return False, (
            f"este APK se compiló con OTRO token que el que está puesto ahora "
            f"({_huella(actual)[:6]}≠{guardada[:6]}). O se rotó la clave sin "
            f"recompilar, o el APK es de antes. Recompílalo.")
    return True, f"el token coincide ({_huella(actual)[:6]}…)"


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


def _huella_binario(p: Path) -> str:
    """`tamaño-mtime` de un APK. Identifica el binario, no su nombre.

    ## Por qué hace falta
    `app-debug.apk` se sobrescribe en cada compilación. Entre que se pide tu OK
    y que pulsas "sí" pueden pasar minutos, y en ese rato alguien —o el propio
    agente, compilando otra cosa— puede dejar un APK distinto en la misma ruta.
    Lo que aprobaste entonces y lo que se instala no serían lo mismo, y la
    aprobación habría sido por un binario que ya no existe.

    Es la misma razón por la que la puerta comprueba la huella del token: lo que
    se autoriza tiene que ser exactamente lo que se ejecuta.
    """
    try:
        st = p.stat()
    except OSError:
        return "sin-fichero"
    return f"{st.st_size}-{int(st.st_mtime)}"


def pedir_deploy(razon: str, lanzar: bool = False) -> dict:
    """Deja la petición pendiente y avisa. No instala nada.

    ## Por qué el aviso va al teléfono
    Es el aviso que se repite: el agente reintenta `install_apk` y cada reintento
    vuelve a pedir. Lo que evita el inundar no es suprimir el aviso, es que sea
    **accionable** y único: la app publica un aviso con el número de pendientes y
    se aprueba desde ahí. Antes iba al emulador porque la notificación vieja no
    tenía a dónde ir y solo podía estorbar.
    """
    pet_id = f"deploy-{uuid.uuid4().hex[:10]}"
    peticion = {
        "id": pet_id, "estado": "pendiente", "razon": razon[:300],
        "lanzar": bool(lanzar), "creado": time.time(),
        # Qué binario se te está pidiendo aprobar. Sin esto, aprobar no dice
        # sobre qué: solo sobre un motivo en prosa.
        "apk": _huella_binario(APK_TELEFONO),
    }
    # ## Primero se guarda, después se avisa
    # Estaba al revés: `avisar_intermedio` va **antes** de `ESTADO.nueva`, así que
    # la app despertaba del broadcast, iba a `/deploys` y no encontraba esta
    # petición —solo las viejas—, publicaba «nada pendiente» y retiraba el aviso.
    #
    # Parecía funcionar porque en las pruebas siempre había alguna petición
    # anterior, y el aviso salía con la cuenta equivocada. Con el estado limpio,
    # que es justo cuando más importa que avise, no avisaba. Un aviso que depende
    # de restos de antes no es un aviso.
    ESTADO.nueva(peticion)
    peticion["aviso"] = avisar_intermedio(peticion)
    ESTADO.pon(pet_id, aviso=peticion["aviso"])
    return peticion


def _hay_aviso_aegis(dump: str) -> bool:
    """¿Hay una notificación viva de Aegis en ese `dumpsys`?

    Se mira el **registro**, no que el comando saliera bien. Un `exit=0` con el
    aviso ausente es el peor resultado posible: parece que avisó y no avisó. Y es
    exactamente lo que pasaba (ver `_avisar_app`).
    """
    for linea in dump.splitlines():
        if "pkg=" + PAQUETE in linea and f"id={ID_AVISO}" in linea:
            return True
    return False


def _permiso_avisos(dev) -> str:
    """Lo que el móvil dice sobre si Aegis puede avisar. Texto, no veredicto."""
    code, out = disp._adb(["shell", "cmd", "appops", "get", PAQUETE,
                           "POST_NOTIFICATION"], timeout=60, serial=dev.serial)
    return out.strip() if code == 0 else ""


def _verificar_aviso(dev, intentos: int = 6) -> str:
    """Espera a que el aviso aparezca, y si no aparece, lo dice y por qué.

    ## Por qué esto existe
    `avisar_intermedio` devolvía `"aviso enviado"` en cuanto el shell salía con
    `exit=0`. En un Samsung eso era mentira: no había notificación ninguna, el
    `appop` de la app estaba en `ignore` y el canal era del shell. El puente
    escribió «aviso enviado» y el agente —y el usuario— se lo creyeron.

    Es A-016 con otro disfraz: un éxito que no se comprobó. Por eso aquí la
    entrega se **lee del sistema** y, si falla, el motivo que se devuelve incluye
    la appop, que es justo el dato que faltaba.
    """
    for _ in range(intentos):
        code, out = disp._adb(["shell", "dumpsys", "notification", "--noredact"],
                              timeout=60, serial=dev.serial)
        if code == 0 and _hay_aviso_aegis(out):
            return "aviso entregado y verificado"
        time.sleep(1.0)

    appop = _permiso_avisos(dev)
    if "ignore" in appop:
        return (
            "AVISO NO LLEGÓ: tu móvil tiene las notificaciones de Aegis "
            "bloqueadas (appop POST_NOTIFICATION: ignore). Ábrelas en Ajustes del "
            "sistema → Aplicaciones → Aegis → Notificaciones. La app tiene un "
            "aviso en pantalla para activarlas.")
    return (
        "AVISO NO VERIFICADO: la app recibió el aviso pero no aparece en dumpsys. "
        "Suele ser que la app está en segundo plano y Android la congeló; se "
        "despierta sola al tocarla. Detalle del appop: " + (appop or "sin dato")
    )


def _avisar_app(dev, tipo: str = "pendiente", motivo: str = "") -> str:
    """Despierta al receptor de Aegis y **comprueba** que el aviso llegó.

    ## Por qué un broadcast y no `cmd notification post`
    La primera versión posteaba con `cmd notification post` desde el shell. En el
    emulador se veía; en un Samsung real, `exit=0` y nada. La razón es de fondo:
    **una notificación que postea otro no es una notificación tuya.** El aviso lo
    firmaba `com.android.shell`, con el icono del sistema, el canal del sistema y
    el permiso del shell. Por eso no podía llevar el logo de Aegis, ni su canal,
    ni abrir algo que fuera de Aegis, y ni siquiera dependía de que la app tuviera
    `POST_NOTIFICATIONS`.

    Ahora la publica la propia app: el puente solo la despierta. Así el aviso es
    de Aegis de verdad —icono, sonido, toque y permiso— y el toque abre el cuadro
    de decisión en lugar de nada.
    """
    # El `tipo` viaja en el broadcast **solo para saber qué rotular**. Los datos
    # que deciden algo —qué hay pendiente, si se puede instalar— los va siempre a
    # preguntar la app al bridge, y no llegan en el intent. Por eso el extra no
    # es una puerta: el peor caso de que alguien mande `tipo=hecho` falseo es un
    # rótulo equivocado, y la app no habilita nada por eso.
    args = ["shell", "am", "broadcast", "-a", ACCION_AVISAR,
            "-n", f"{PAQUETE}/.NotificacionReceiver", "--es", "tipo", tipo]
    if motivo:
        # Solo si hay motivo. `--es motivo ""` no es un extra vacío: `adb` se come
        # el argumento y el broadcast sale con `Argument expected after "motivo"`,
        # que es un fallo de puente en el sitio más tonto posible.
        args += ["--es", "motivo", motivo[:300]]
    code, out = disp._adb(args, timeout=60, serial=dev.serial)
    if code != 0:
        return f"aviso falló (exit={code}): {out[:120]}"
    if "Broadcast completed" not in out:
        return f"aviso sin confirmar: {out[:120]}"
    return _verificar_aviso(dev)


def _ultimo_aviso() -> tuple[float, str]:
    """(cuando, etiqueta) del último aviso, o (0, ''). Solo en memoria."""
    global _AVISO
    return _AVISO


_AVISO: tuple[float, str] = (0.0, "")


def avisar_intermedio(peticion: dict) -> str:
    """Avisa de que hay una aprobación pendiente, y devuelve si **llegó**.

    ## El aviso va al teléfono, y no se repite
    Es el aviso que se repite: el agente llama a `install_apk`, no hay
    aprobación, se vuelve a llamar, y así. Dos cosas evitan el inundar:

    - **aquí**, que si hay otra pendiente con el mismo motivo hace poco, se dice
      que ya está avisado en vez de volver a notificar;
    - **en la app**, que publica un aviso con ID fijo y el número de pendientes,
      así que aunque lleguen cinco broadcasts se ve uno.

    Un aviso que se repite no informa de nada nuevo.
    """
    destino = AVISO_INTERMEDIO
    if destino == "ninguno":
        return "avisos desactivados (AEGIS_AVISO_INTERMEDIO=ninguno)"

    # Si el destino principal no está, se va al otro. Un aviso que no se puede
    # entregar no es un aviso, y aquí ya se sabe si hay teléfono.
    orden = ["telefono", "emulador"] if destino == "telefono" else ["emulador", "telefono"]
    dev = None
    probado = destino
    for candidato in orden:
        try:
            d = disp.telefono() if candidato == "telefono" else disp.emulador()
        except disp.DeviceError:
            d = None
        if d is not None:
            dev, probado = d, candidato
            break
    if dev is None:
        return f"no pude avisar: no hay {probado} conectado por adb"

    # Eleva la misma razón a la misma clave, así "misma razón" quiere decir lo
    # mismo y no dos cadenas parecidas que no se reconocen.
    clave = f"{peticion.get('razon', '')}|{bool(peticion.get('lanzar'))}"
    ahora = time.time()
    previa, etiqueta_previa = _ultimo_aviso()
    if etiqueta_previa == clave and ahora - previa < VENTANA_AVISO:
        return (f"ya estaba avisado hace {int(ahora - previa)}s "
                f"({probado}): no repito el aviso")

    global _AVISO
    _AVISO = (ahora, clave)
    return f"{_avisar_app(dev)} ({probado})"


def avisar_telefono(peticion: dict) -> str:
    """Aviso **final** al teléfono real: la instalación se hizo.

    Este es el único aviso que llega a tu móvil por una instalación ya hecha, y
    llega una vez, cuando ya no hay nada que decidir. Si no está conectado por
    adb, se dice: no se finge que se avisó.
    """
    try:
        dev = disp.telefono()
    except disp.DeviceError as exc:
        return f"no pude avisar: {exc}"
    if dev is None:
        return "no pude avisar: tu teléfono no está conectado por adb"
    return _avisar_app(dev, tipo="hecho")


def avisar_fallo_telefono(pet_id: str, motivo: str) -> str:
    """Avisa de que la instalación aprobada **no** se hizo, y por qué.

    ## Por qué existe
    El cuadro superpuesto dice "se instala en segundo plano" y devuelve
    enseguida. Si después falla la puerta, sin este aviso el usuario queda con
    un "sí" que terminó en nada y sin ninguna señal de que pasó. Un
    fallo mudo es peor que un fallo ruidoso: el primero hace que la siguiente vez
    no apruebes nada por si acaso.
    """
    try:
        dev = disp.telefono()
    except disp.DeviceError as exc:
        return f"no pude avisar: {exc}"
    if dev is None:
        return "no pude avisar: tu teléfono no está conectado por adb"
    return _avisar_app(dev, tipo="fallo", motivo=motivo)


def aprobar(pet_id: str, decision: str = "aprobar", motivo: str = "") -> dict:
    """Resuelve una petición. `aprobar` devuelve un token de un solo uso.

    ## Por qué el motivo importa y solo se pide al denegar
    Denegar con motivo es lo que hace crecer la confianza: el motivo se inyecta
    en el prompt del siguiente run y Aegis no vuelve a proponerlo. Sin motivo,
    denegar es un "no" que no se puede aplicar a la siguiente situación parecida.
    Por eso el overlay **exige** el motivo en el "no".
    """
    p = ESTADO.peticion(pet_id)
    if not p:
        raise PuertaCerrada(f"no hay ninguna petición con id '{pet_id}'")
    if decision not in ("aprobar", "denegar"):
        raise PuertaCerrada("decision debe ser 'aprobar' o 'denegar'")
    if decision == "denegar" and not motivo.strip():
        raise PuertaCerrada(
            "un 'no' sin motivo no es una decisión: es ruido. Escribe por qué y "
            "Aegis lo tendrá en cuenta la próxima vez.")
    # Se guarda el estado en pasado, no el verbo de la decisión: antes se
    # guardaba "aprobar" y se buscaba "aprobada", así que una aprobación
    # aprobada no se encontraba y la puerta se cerraba siempre. Lo que se
    # devuelve y lo que se guarda tienen que ser lo mismo.
    estado = "aprobada" if decision == "aprobar" else "denegada"
    ESTADO.pon(pet_id, estado=estado, motivo=motivo[:300])
    if estado == "aprobada":
        token = uuid.uuid4().hex[:16]
        ESTADO.nuevo_token(token, {"id": p["id"], "razon": p["razon"],
                                   "lanzar": p["lanzar"], "gastado": False,
                                   "apk": p.get("apk", ""),
                                   "creado": time.time()})
        ESTADO.pon(pet_id, token=token)
        return {"estado": estado, "token": token}
    return {"estado": estado, "motivo": motivo[:300]}


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

def pasar_puerta_deploy(lanzar: bool = False) -> disp.Device:
    """Todo lo que tiene que estar en verde antes de tocar el teléfono.

    Devuelve el **dispositivo verificado**, o lanza `PuertaCerrada` con el motivo.
    Se comprueba aquí, no se acepta que el agente diga que comprobó.

    ## Por qué devuelve el device y no su serial
    Porque la puerta acaba de resolver *qué* teléfono es, con todos los controles
    en verde. Devolver solo el serial obliga a quien llama a volver a resolverlo,
    y esa segunda resolución puede dar **otro** dispositivo: entre las dos, el
    teléfono se desconecta y entra otro por la misma vía, y se instala sobre un
    aparato que nadie comprobó.

    ## Por qué esto estaba roto y no se vio
    Devolvía `dev.serial` (un `str`) y un llamador nuevo lo pasó a
    `instalar_en_telefono`, que espera un `Device`. Revienta con
    `AttributeError: 'str' object has no attribute 'serial'` — pero **en un
    hilo en segundo plano**, un minuto y medio después de que el usuario pulsara
    «sí». El test unitario no lo vio porque fijaba el mock a un `Device`: el
    test estaba mintiendo sobre la firma real, que es la forma más común de que
    un test de contrato no sea un test de contrato. De ahí el test de tipo de
    abajo.
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
    return dev


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

    ## Por qué se comprueba la huella del APK
    El token se creó al aprobar, y entre entonces y ahora puede haberse
    recompilado: mismo nombre de fichero, binario distinto. Sin esta comprobación
    una aprobación vieja autorizaba un binario que nadie había visto, y bastaba
    con que la mejorara el tamaño o el mtime para que colara. La puerta que
    protege una instalación tiene que decir **qué** instalación.
    """
    candidatas = [p for p in ESTADO.todas_las_peticiones().values()
                 if p.get("estado") == "aprobada"]
    candidatas.sort(key=lambda p: p.get("creado", 0), reverse=True)
    actual = _huella_binario(APK_TELEFONO)
    for p in candidatas:
        tok = p.get("token")
        if tok and not (ESTADO.token(tok) or {}).get("gastado"):
            if p.get("lanzar") != lanzar:
                continue
            aprobado = p.get("apk", "")
            if aprobado and aprobado != actual:
                # El binario que se aprobó no es el que hay. La aprobación sigue
                # viva —el token no se gasta— pero no cubre esta instalación: hay
                # que volver a pedirla, que es lo que hará `pedir_deploy`.
                continue
            return {"token": tok, "peticion": p}
    return None


def instalar_pendiente(pet_id: str) -> str:
    """Canjea la aprobación de una petición e instala, sin que pase por el agente.

    ## Por qué esto vive aquí y no en la tool
    Antes, aprobar devolvía un token y el agente tenía que volver a llamar a
    `install_apk` para gastarlo. Eso **no** es instalar en segundo plano: es que
    el agente se entere. Si el agente no está, o su run terminó, o no le apetece
    llamar otra vez, el APK aprobado se queda en el disco para siempre y tú nunca
    te enteras.

    Con este endpoint la cadena es: apruebas → el puente instala → te avisa. Sin
    intermediarios, y sin que el token salga de aquí: se gasta dentro, que es la
    única forma de que un token de un solo uso siga siendo de un solo uso.

    ## Qué no vuelve a comprobar, y por qué
    Analyze, tests y humo ya se comprobaron cuando `install_apk` pidió la
    autorización; volver a pasarlos aquí tardaría minutos con el dedo de alguien
    encima de un botón. Lo que **sí** se vuelve a comprobar es lo barato y lo que
    puede haber cambiado desde entonces: que el token siga vivo, y que el APK sea
    exactamente el binario que se te pidió aprobar.
    """
    p = ESTADO.peticion(pet_id)
    if not p:
        raise PuertaCerrada(f"no hay ninguna petición con id '{pet_id}'")
    if p.get("estado") != "aprobada":
        raise PuertaCerrada(
            f"esa petición está '{p.get('estado', '?')}', no aprobada. Apruébala "
            "primero desde el aviso.")
    token = p.get("token") or ""
    if not token:
        raise PuertaCerrada("esa aprobación no tiene token: no puedo instalar nada.")
    if (ESTADO.token(token) or {}).get("gastado"):
        raise PuertaCerrada("esa instalación ya se hizo. El token es de un solo uso.")

    # Lo que aprobaste y lo que se instala tienen que ser el mismo fichero. Entre
    # que se pide el OK y se pulsa "sí" pueden pasar minutos, y en ese rato una
    # recompilación deja otro binario en la misma ruta.
    esperado, ahora = p.get("apk", ""), _huella_binario(APK_TELEFONO)
    if esperado and esperado != ahora:
        raise PuertaCerrada(
            f"el APK cambió después de que lo aprobaras: aprobaste {esperado} y "
            f"ahora hay {ahora}. Vuelve a pedir la instalación para aprobar el "
            "binario que hay ahora, no el que ya no existe.")

    dev = pasar_puerta_deploy(lanzar=bool(p.get("lanzar")))
    return instalar_en_telefono(dev, token=token, lanzar=bool(p.get("lanzar")))


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
    # ## Por qué el APK se comprueba **antes** que la aprobación
    # Si el binario no está, ninguna aprobación puede cubrirlo —no hay nada que
    # autorizar— y el mensaje útil es "compílalo", no "pide una aprobación". Al
    # revés, la puerta respondía a «no hay APK» con «no hay aprobación», que
    # manda a aprobar algo que todavía no se puede instalar.
    if not APK_TELEFONO.exists():
        raise PuertaCerrada(
            f"no hay APK del teléfono ({APK_TELEFONO}). El que se prueba en el "
            "emulador no sirve aquí: apunta a localhost. Compila antes con "
            "build_apk(target='telefono').")
    if not token and not primera_vez:
        ap = buscar_aprobacion(lanzar=lanzar)
        if ap is None:
            raise PuertaCerrada(
                "no hay ninguna aprobación vigente para esta instalación. "
                "Pídela con install_apk(target='telefono') y apruébala en el móvil.")
        token = ap["token"]
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

    # El único aviso que llega a tu teléfono, y solo ahora que ya no hay nada
    # que decidir. Los de "falta tu autorización" van al emulador: son ruido
    # mientras la decisión está viva, y multiplicar notificaciones intermedias
    # es lo que hace que un sistema se vuelva pesado.
    aviso = avisar_telefono({"razon": peticion_razon(dev, t), "id": t.get("id", "-"),
                             "lanzar": bool(lanzar and t.get("lanzar"))})
    partes.append(aviso)
    return "\n".join(partes)


def peticion_razon(dev, token: dict) -> str:
    """El motivo legible de la instalación que se acaba de hacer.

    El token trae el `id` y el `razon` de la petición que lo originó. Si no hay
    ninguno (primera instalación, que no pidió autorización) se dice eso, que es
    la verdad.
    """
    return str(token.get("razon") or f"APK verificado en {dev.serial}")


def snapshot() -> dict:
    """Estado de la puerta, para poder mirarlo desde fuera."""
    return {
        "emulador": bool(disp.emulador()),
        "telefono": bool(disp.telefono()),
        "pendientes": pendientes(),
        "tokens_vivos": sum(1 for t in ESTADO.todos_los_tokens().values()
                           if not t.get("gastado")),
    }