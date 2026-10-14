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
from . import entorno

MOBILE = entorno.MOBILE
#: El APK que se prueba en el emulador. El del teléfono es otro binario, con la
#: IP de la tailnet en vez de localhost, y vive en `APK_TELEFONO`.
APK = disp.apk_para("emulador")
APK_TELEFONO = disp.apk_para("telefono")
#: Perfil de los dos binarios. Release por defecto porque el APK baja por la red y
#: el de debug pesa casi cuatro veces más; la firma es la misma, así que uno
#: sustituye al otro sin desinstalar.
PERFIL = "release"
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

    RUTA = entorno.datos("deploy.json")

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


def _raiz_del_movil(apk: Path) -> Path | None:
    """La raíz del proyecto Flutter al que pertenece este APK, o None.

    Se deduce **del propio APK** y no de una constante: `build/app/outputs/
    flutter-apk/…` solo existe dentro de un proyecto, así que es la forma de
    saber de qué código habla el binario. Con una ruta que no está dentro de un
    proyecto no hay nada que comparar, y ese "no sé" se devuelve como "" en
    vez de como un fallo.
    """
    try:
        partes = apk.resolve().parts
    except OSError:
        return None
    for i, p in enumerate(partes[:-1]):
        if p == "mobile" and partes[i + 1] == "build":
            return Path(*partes[: i + 1])
    return None


#: Ficheros que escribe la herramienta dentro del proyecto y que **no son código
#: de nadie**: no se editan, se regeneran, y cambian por una causa que no es que
#: alguien tocara el código.
#:
#: Está fuera de la firma del APK, y lo que lo sostiene es que el juego de
#: plugins entra por `pubspec.lock`, que sí se hashea. Ver `_firma_del_codigo`.
_GENERADOS_POR_FERRAMENTA = frozenset({
    Path("android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java"),
})


def _firma_del_codigo(raiz: Path) -> str:
    """Huella del código fuente del que sale un APK.

    ## Por qué una firma y no comparar fechas
    Se probó primero con fechas y dio un falso positivo medido: un fichero de
    `lib/` tenía `mtime` posterior al APK **sin haber cambiado de contenido**
    (`git status` limpio). Bloquear una instalación por eso sería teaching el
    teléfono cada dos compilaciones, y una puerta que avisa en falso entrena: la
    siguiente vez miras el aviso por encima.

    ## Qué entra
    `pubspec.yaml`, `pubspec.lock`, `lib/**` y `android/app/src/main/**`: lo que
    cambia lo que acaba dentro del APK. `build/**` no entra, porque el propio
    binario está ahí y se compararía consigo mismo.

    ## Por qué el **contenido** y no la fecha
    La primera versión metía `mtime` y `st_size` por abaratar la cuenta, y el
    falso positivo seguía apareciendo: un `touch` cambia la fecha sin cambiar una
    letra del código. Aquí se lee el fichero entero, que son unos cientos de
    kilobytes y se tarda menos que el `adb` que viene después. Barato y cierto.

    ## Por qué `pubspec.lock` entra
    Porque es lo que determina **qué plugins se registran** en el APK, y eso no
    sale de `pubspec.yaml`: sale del grafo resuelto. Sin el lock, cambiar una
    versión de una dependencia —o añadirla— no movería la firma, y el APK se quedaría
    viejo en silencio. Con él, esa señal sigue ahí.

    ## Por qué el fichero **generado** se queda fuera
    `android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java`
    lo escribe la herramienta de Flutter en cada build, y su encabezado dice
    `Generated file. Do not edit.` No es código que nadie escribiera: es
    consecuencia del lock, que ya entra.

    Estaba dentro de la firma solo por dónde cae, y eso producía un fallo medido:
    `verificar_binario` corre `flutter analyze`/`flutter test`/el humo, que
    **regeneran** ese fichero, así que la firma cambiaba después de haber sido
    sellada y el APK salía «desactualizado» para siempre. El 409 que veía la app
    decía «recompílalo», y recompilar no lo arreglaba: la puerta se invalidaba a
    sí misma.

    Excluirlo no la debilita, la **corrige**: una puerta que avisa en falso es
    peor que ninguna. Y la señal que se sacrifica («cambió el juego de
    plugins») la sostiene el lock.
    """
    import hashlib

    h = hashlib.sha256()
    files: list[Path] = []
    for pub in ("pubspec.yaml", "pubspec.lock"):
        p = raiz / pub
        if p.exists():
            files.append(p)
    for sub in ("lib", "android/app/src/main"):
        d = raiz / sub
        if d.is_dir():
            # La comparación es **relativa a la raíz**: `rglob` devuelve rutas
            # completas, y comparar esas contra una constante con ruta relativa
            # no encontraría nunca nada. Un filtro que no filta parece que filtra,
            # que es la peor forma de que un guardarraíl falle.
            files.extend(
                f for f in d.rglob("*")
                if f.is_file() and f.relative_to(raiz) not in _GENERADOS_POR_FERRAMENTA
            )
    for f in sorted(files, key=lambda x: str(x)):
        h.update(str(f.relative_to(raiz)).encode("utf-8"))
        h.update(b":")
        try:
            h.update(f.read_bytes())
        except OSError:
            h.update(b"<ilegible>")
        h.update(b"\n")
    return h.hexdigest()[:16]


def sello_de(apk: Path) -> Path:
    """Dónde vive el sello de un APK: al lado, con otro nombre."""
    return apk.with_name(apk.name + ".sello")


def verificado_de(apk: Path) -> Path:
    """Dónde vive el **verificado**: el sello de que este binario pasó la puerta.

    ## Por qué un fichero aparte del `.sello`
    Son dos preguntas distintas y no se pueden confundir:
    - `.sello` responde «¿este binario salió del código de ahora?» — es de origen.
    - `.verificado` responde «¿este binario **pasó** analyze, tests y humo?» — es
      de calidad.

    Con un solo fichero había que elegir, y las dos respuestas se mezclaban: un
    APK compilado a mano pero nunca verificado pasaba por verificado porque su
    código era el de ahora, que es justo el falso éxito que A-016 ya pagó en otro
    sitio.
    """
    return apk.with_name(apk.name + ".verificado")


def escribir_verificado(apk: Path, detalle: str = "") -> str:
    """Deja constancia de que este APK pasó la verificación. Lo llama la puerta.

    Guarda la firma del **binario**, no la del código: si se recompila, el
    verificado deja de cuadrar aunque el código sea idéntico, que es lo correcto
    — lo que se verificó fue *ese* fichero.
    """
    firma = _huella_binario(apk)
    if not firma:
        return ""
    cuerpo = firma if not detalle else f"{firma} · {detalle.strip()[:200]}"
    try:
        verificado_de(apk).write_text(cuerpo + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("no pude escribir el verificado de %s: %s", apk.name, exc)
    return firma


def apk_verificado(p: Path | None = None) -> bool:
    """¿Pasó este APK la puerta recently, tal y como está ahora en disco?"""
    apk = p or APK_TELEFONO
    try:
        guardado = verificado_de(apk).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not guardado:
        return False
    return guardado.split(" · ")[0] == _huella_binario(apk)


def apk_sin_verificar(p: Path | None = None) -> str:
    """Por qué este APK no puede instalarse todavía, o "" si puede."""
    apk = p or APK_TELEFONO
    if apk_verificado(apk):
        return ""
    existe = verificado_de(apk).exists()
    if existe:
        return ("el APK se recompiló después de verificarse: lo que se comprobó no "
                "es el binario que hay. Vuelve a compilar y verificar.")
    return ("este APK no ha pasado la puerta todavía (analyze, tests y humo). "
            "Compílalo con build_apk(target='telefono'), que verifica antes de "
            "ofrecer instalar: así no te pido que apruebes algo que después no "
            "pasa.")


def verificar_binario(apk: Path, con_humo: bool = True) -> tuple[bool, str]:
    """La puerta cara: analyze, tests y humo. Se ejecuta **al compilar**.

    ## Por qué aquí y no al instalar
    Medido (2026-10-03): la puerta corría al instalar, después de que aprobaras.
    `flutter analyze` + `flutter test` + el humo son minutos, así que el aviso
    decía «se instala» y luego había varios minutos de silencio antes de que
    pasara algo — y si la puerta se cerraba, tu «sí» había servido para pedirte
    que aprobaras una instalación que no iba a ocurrir.

    Verificando al compilar, el aviso aparece **cuando ya no hay nada que
    comprobar**: lo que queda entre tu «sí» y el APK en el teléfono es un
    `adb install` de segundos. Y el docstring de `instalar_pendiente` ya prometía
    esto («analyze, tests y humo ya se comprobaron cuando `install_apk` pidió la
    autorización»): el código ahora cumple lo que el texto decía.

    El humo es opcional porque quien compila para su propio uso no siempre quiere
    instalar en el emulador, y porque tarde un minuto. La puerta de instalar **no**
    lo vuelve a pasar: ya está en el `.verificado`.
    """
    if (desactualizado := apk_desactualizado(apk)):
        return False, desactualizado
    fallos = []
    for nombre, fn in (("analyze", verificar_analisis), ("tests", verificar_tests)):
        ok, detalle = fn()
        if not ok:
            fallos.append(f"{nombre}: {detalle}")
    # El humo se salta si ya hay rojo. Cuesta alrededor de un minuto e instala y
    # arranca el emulador: si analyze ya está en rojo su resultado no va a cambiar
    # la conclusión, solo a hacer esperar más.
    if con_humo and not fallos:
        humo_ok, humo_detalle = humo_una_vez()
        if not humo_ok:
            fallos.append(f"humo en el emulador: {humo_detalle}")
    else:
        humo_detalle = "sin humo en esta compilación"
    if fallos:
        return False, "\n  ".join(fallos)
    detalle = "analyze, tests" + (" y humo" if con_humo else "")
    return True, f"{detalle} en verde · {humo_detalle}"


def escribir_sello(apk: Path) -> str:
    """Deja el sello que dice de qué código salió este APK. Lo llama la compilación.

    Solo la compilación puede escribirlo, y por eso es fiable: si el sello no
    coincide con el código actual, el binario es de antes de algún cambio. Sin
    sello no se afirma nada — un APK compilado a mano queda sin comprobar, que es
    distinto de estar verificado.
    """
    raiz = _raiz_del_movil(apk)
    if raiz is None:
        return ""
    firma = _firma_del_codigo(raiz)
    try:
        sello_de(apk).write_text(firma + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("no pude escribir el sello de %s: %s", apk.name, exc)
    return firma


def apk_desactualizado(p: Path | None = None) -> str:
    """Por qué el APK no representa el código de ahora, o "" si no hay motivo.

    ## El fallo que esto previene, medido
    Se aprobó e instaló en el teléfono un APK de **dos días antes** del código que
    se estaba tocando. La puerta lo dio por bueno: la huella casaba (era *un*
    binario, y verificado), y el mensaje decía «APK verificado, listo para
    instalar». Todo lo que la puerta comprobaba era cierto, y aun así lo
    instalado no era lo que se creías.

    Es la clase de fallo que este repo ya pagó por otro lado (A-016: el veredicto
    salía de `final_text`): **una puerta que comprueba una cosa y responde por
    otra**. La huella dice «es el mismo fichero que aprobaste»; no dice «es el
    código de ahora».

    ## Qué se mira, y por qué no se recompila aquí
    El **sello** que dejó la compilación, contra la firma del código de ahora. Sin
    sello no se dice nada: no se puede comprobar, y no se presume. Y no se
    recompila, porque un "instalar" que compila es un "compilar e instalar"
    disfrazado, y el fallo de una compilación rota aparecería como fallo de
    instalación. La puerta **dice la verdad y deja la decisión fuera**.
    """
    apk = p or APK_TELEFONO
    if not apk.exists():
        return ""          # que lo diga el otro aviso, el del "no hay APK"
    raiz = _raiz_del_movil(apk)
    if raiz is None:
        return ""          # una ruta que no es de un proyecto no se juzga
    try:
        sello = sello_de(apk).read_text(encoding="utf-8").strip()
    except OSError:
        return ""          # compilado a mano: sin sello, sin veredicto
    if not sello:
        return ""
    firma = _firma_del_codigo(raiz)
    if sello == firma:
        return ""
    return (
        f"El APK no corresponde al código de ahora: se compiló de otra fuente. "
        f"Compílalo antes con build_apk(target='telefono') y vuelve a pedir. "
        f"(sello {sello} · código {firma})"
    )


def pedir_deploy(razon: str, lanzar: bool = False) -> dict:
    """Deja la petición pendiente y avisa. No instala nada.

    ## Por qué el aviso va al teléfono
    Es el aviso que se repite: el agente reintenta `install_apk` y cada reintento
    vuelve a pedir. Lo que evita el inundar no es suprimir el aviso, es que sea
    **accionable** y único: la app publica un aviso con el número de pendientes y
    se aprueba desde ahí. Antes iba al emulador porque la notificación vieja no
    tenía a dónde ir y solo podía estorbar.
    """
    # Antes de dejar la petición: si el binario es viejo, decirlo **antes** de
    # pedir el OK. Pedir permiso para instalar el código de hace dos días es
    # gastar la atención de alguien en algo que no quiere.
    if desactualizado := apk_desactualizado():
        raise PuertaCerrada(desactualizado)

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




def _hay_aviso_aegis(dump: str, estado: str = "") -> bool:
    """¿Hay una notificación viva de Aegis en ese `dumpsys`, **en ese estado**?

    Se mira el **registro**, no que el comando saliera bien. Un `exit=0` con el
    aviso ausente es el peor resultado posible: parece que avisó y no avisó. Y es
    exactamente lo que pasaba (ver `_avisar_app`).

    ## Por qué el estado se comprueba y no solo la existencia
    Con un solo aviso, la existencia no dice nada: el aviso anterior sigue ahí
    mientras el nuevo se publica en otro hilo. Así que se mira la marca del
    estado. Para `pendiente` no se busca marca: su título depende de cuántas hay
    («NECESITO TU OK» o «N DECISIONES PENDIENTES») y no hay una fija.
    """
    espera = MARCA_ESTADO.get(estado, "")
    hay_aviso = any("pkg=" + PAQUETE in linea and f"id={ID_AVISO}" in linea
                    for linea in dump.splitlines())
    if not hay_aviso:
        return False
    if not espera:
        return True
    # El título va en su propia línea del registro, con `android.title=String (…)`.
    # Se busca en el volcado entero: recorrer el `NotificationRecord` para leer su
    # título es más código para el mismo dato.
    return "android.title" in dump and espera in dump


def _permiso_avisos(dev) -> str:
    """Lo que el móvil dice sobre si Aegis puede avisar. Texto, no veredicto."""
    code, out = disp._adb(["shell", "cmd", "appops", "get", PAQUETE,
                           "POST_NOTIFICATION"], timeout=60, serial=dev.serial)
    return out.strip() if code == 0 else ""


def _verificar_aviso(dev, intentos: int = 6, estado: str = "") -> str:
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
        if code == 0 and _hay_aviso_aegis(out, estado):
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


#: Los cuatro estados de un aviso, y lo único que la app necesita saber.
#:
#: ## Por qué un estado y no el par pendiente/hecho
#: Antes el aviso distinguía «necesito tu OK» (id 4101) de «ya está» (id 4102), y
#: los dos convivían porque cancelarlos era trabajo de alguien. Resultado
#: medido: un aviso de un test que llegó al móvil y **no se podía quitar**, y
#: mientras tanto los avisos de resultado nunca se verificaban, porque
#: `_hay_aviso_aegis` solo miraba el 4101.
#:
#: Con un solo estado y un solo id, «no puede haber dos avisos de Aegis» deja de
#: ser una intención y pasa a ser una propiedad: o hay un aviso, o no hay nada.
ESTADO_PENDIENTE = "pendiente"
ESTADO_TRABAJANDO = "trabajando"
ESTADO_HECHO = "hecho"
ESTADO_FALLO = "fallo"
ESTADO_LIMPIAR = "limpiar"

#: Cuánto vive un aviso final antes de borrarse solo. Un aviso que se queda para
#: siempre en la bandeja es ruido pasado un rato, y era justo lo que pasaba con
#: el 4102: nadie lo cancelaba y `setAutoCancel` solo lo quita al tocarlo.
CADUCIDAD_FINAL_MS = 45_000

#: La marca que cada estado deja en el aviso. Es lo que permite **comprobar** que
#: el estado que se quería publicar está, y no el anterior.
#:
#: ## Por qué hace falta ahora y antes no
#: Antes `_hay_aviso_aegis` solo miraba que hubiera una notificación de Aegis. Con
#: dos ids eso bastaba: publicar el resultado usaba el 4102, así que si el 4101
#: seguía ahí era porque el aviso de decisión **no** se había tocado.
#:
#: Con un id, no: los estados se sustituyen en sitio, así que «hay un aviso de
#: Aegis» es cierto **siempre**, incluso cuando lo que se acaba de publicar es otra
#: cosa. Verificado: tras `hecho`, `dumpsys` seguía enseñando `EN MARCHA` y el
#: puente respondía «entregado y verificado». Es A-042 por sexta vez: un éxito que
#: nadie comprobó, y esta vez lo caused el arreglo de ayer.
MARCA_ESTADO = {
    ESTADO_TRABAJANDO: "EN MARCHA",
    ESTADO_HECHO: "INSTALADO",
    ESTADO_FALLO: "NO SE PUDO",
}


def _avisar_app(dev, tipo: str = ESTADO_PENDIENTE, motivo: str = "",
                pet_id: str = "") -> str:
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

    ## Por qué `pet_id` y `ts` viajan ahora
    `pet_id` para que la app pueda ignorar un aviso de una petición que ya no
    existe, y `ts` para que un aviso **tardío** no pise uno más nuevo: los
    broadcasts van por `adb`, que los entrega uno a uno pero sin orden entre
    llamadas distintas, y sin esto un «instalado» que llegaba tarde podía dejar
    la bandeja diciendo «necesito tu OK» sobre algo que ya estaba hecho.
    """
    args = ["shell", "am", "broadcast", "-a", ACCION_AVISAR,
            "-n", f"{PAQUETE}/.NotificacionReceiver", "--es", "tipo", tipo]
    # El `tipo` viaja en el broadcast **solo para saber qué pintar**. Los datos
    # que deciden algo —qué hay pendiente, si se puede instalar— los va siempre a
    # preguntar la app al bridge, y no llegan en el intent. Por eso el extra no
    # es una puerta: el peor caso de que alguien mande `tipo=hecho` falseo es un
    # rótulo equivocado, y la app no habilita nada por eso.
    if motivo:
        # Solo si hay motivo. `--es motivo ""` no es un extra vacío: `adb` se come
        # el argumento y el broadcast sale con `Argument expected after "motivo"`,
        # que es un fallo de puente en el sitio más tonto posible.
        args += ["--es", "motivo", motivo[:300]]
    if pet_id:
        args += ["--es", "pet_id", pet_id]
    args += ["--es", "ts", f"{time.time():.3f}"]
    code, out = disp._adb(args, timeout=60, serial=dev.serial)
    if code != 0:
        return f"aviso falló (exit={code}): {out[:120]}"
    if "Broadcast completed" not in out:
        return f"aviso sin confirmar: {out[:120]}"
    if tipo == ESTADO_LIMPIAR:
        # No hay nada que verificar: `limpiar` no publica, cancela. Preguntar por
        # él en `dumpsys` daría «no verificado» siempre, que es ruido, no un dato.
        return "aviso limpiado"
    return _verificar_aviso(dev, estado=tipo)


def _ultimo_aviso() -> tuple[float, str]:
    """(cuando, etiqueta) del último aviso, o (0, ''). Solo en memoria."""
    global _AVISO
    return _AVISO


_AVISO: tuple[float, str] = (0.0, "")


def _destino_aviso(destino: str) -> tuple[disp.Device | None, str]:
    """A qué aparato se avisa, y a cuál se intentó. `(device, nombre)`.

    ## Por qué es un helper y no una línea en cada sitio
    `avisar_intermedio` ya tenía el "si el destino principal no está, se va al
    otro", y los otros tres lo tenían solo con `disp.telefono()`. Medido: con
    `limpiar` mandada al teléfono a propósito, el aviso del emulador no se podía
    quitar nunca. Cuatro Ways de decidir lo mismo es una forma segura de que uno
    se olvide del otro, y el que se olvida es siempre el que nadie prueba.

    ## Y por qué el destino por defecto
    `AVISO_INTERMEDIO`, igual que el aviso de decisión: el aviso que hay que
    decidir va donde se decide.
    """
    orden = (["telefono", "emulador"] if destino == "telefono"
             else ["emulador", "telefono"])
    for candidato in orden:
        try:
            d = disp.telefono() if candidato == "telefono" else disp.emulador()
        except disp.DeviceError:
            d = None
        if d is not None:
            return d, candidato
    return None, destino


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

    dev, probado = _destino_aviso(destino)
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
    return f"{_avisar_app(dev, ESTADO_PENDIENTE, pet_id=peticion.get('id', ''))} ({probado})"


def avisar_telefono(peticion: dict) -> str:
    """Aviso **final** al teléfono real: la instalación se hizo.

    ## Y por qué ahora usa el mismo id que el de «necesito tu OK»
    Antes iba a un id aparte (4102) que **nadie cancelaba nunca**, así que un
    «ya está» se quedaba en la bandeja para siempre y el aviso de decisión
    seguía encima diciendo que faltaba tu OK. Con un solo id, publicar el final
    **reemplaza** al de decisión por el mecanismo de siempre, y se dice también
    lo que hace con él la app: caduca a los 45 s.

    Es lo contrario de lo que se temía al separarlos («un 'ya está' no debe borrar
    un 'todavía necesito tu OK'»): con varios pendientes, se avisa del final y el
    siguiente broadcast de pendientes repinta el aviso de decisión. Perderlo un
    momento es mejor que mantenerlo para siempre.
    """
    dev, probado = _destino_aviso(AVISO_INTERMEDIO)
    if dev is None:
        return f"no pude avisar: no hay {probado} conectado por adb"
    return _avisar_app(dev, ESTADO_HECHO,
                       pet_id=peticion.get("id", "") if isinstance(peticion, dict) else "")


def avisar_fallo_telefono(pet_id: str, motivo: str) -> str:
    """Avisa de que la instalación aprobada **no** se hizo, y por qué.

    ## Por qué existe
    El cuadro superpuesto dice "se instala en segundo plano" y devuelve
    enseguida. Si después falla la puerta, sin este aviso el usuario queda con
    un "sí" que terminó en nada y sin ninguna señal de que pasó. Un
    fallo mudo es peor que un fallo ruidoso: el primero hace que la siguiente vez
    no apruebes nada por si acaso.

    ## Y ahora también cuando algo que no es una instalación
    `_lanza_ejecucion` lo llama cuando un hilo muere, y antes **no** había aviso
    de éxito para nada que no fuera instalar: `db_migrate` o `adb_connect`
    terminaban mudos. Con el aviso siendo el canal de estado de una operación, un
    «no se hizo» sin su «sí, se hizo» es un canal que solo sabe quejarse.
    """
    dev, probado = _destino_aviso(AVISO_INTERMEDIO)
    if dev is None:
        return f"no pude avisar: no hay {probado} conectado por adb"
    return _avisar_app(dev, ESTADO_FALLO, motivo=motivo, pet_id=pet_id)


def avisar_trabajando(pet_id: str, que: str = "instalando la app") -> str:
    """El aviso pasa a «esto está en marcha» y **no se puede quitar**.

    Se publica cuando la operación arranca, no cuando acaba, porque entre tu
    «sí» y el resultado hay un `adb install`. Es el único estado *ongoing*: si se
    pudiera quitar con un dedo, la bandeja volvería a quedarse muda justo en la
    parte que espera.
    """
    dev, probado = _destino_aviso(AVISO_INTERMEDIO)
    if dev is None:
        return f"no pude avisar: no hay {probado} conectado por adb"
    return _avisar_app(dev, ESTADO_TRABAJANDO, motivo=que, pet_id=pet_id)


def avisar_limpiar() -> str:
    """Que no quede nada de Aegis en la bandeja.

    ## Por qué existe, y por qué tiene que poder pedirse
    Un aviso que ya no vale tiene que poder irse **sin** que llegue otro aviso que
    lo tape. Pasó de verdad: quedó en la bandeja el aviso de un test y no había
    forma de quitarlo, porque solo se cancelaba cuando otro aviso de pendientes
    veía la cola vacía —y si no volvía a haber nada que decidir, ese otro aviso
    nunca llegaba.

    Se llama al abrir la app: es el único momento en que se sabe que hay un
    receptor vivo y que `/deploys` se puede preguntar de verdad.
    """
    dev, probado = _destino_aviso(AVISO_INTERMEDIO)
    if dev is None:
        return f"no pude avisar: no hay {probado} conectado por adb"
    return _avisar_app(dev, ESTADO_LIMPIAR)


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
    """Lo **barato**, y solo lo barato, antes de tocar el teléfono.

    Devuelve el **dispositivo verificado**, o lanza `PuertaCerrada` con el motivo.

    ## Lo que ya NO está aquí, y por qué
    Analyze, tests y humo se comprueban al **compilar** (`verificar_binario`) y
    quedan sellados en `<apk>.verificado`. Aquí solo se comprueba que ese sello
    siga cuadrando con el binario que hay ahora mismo.

    Antes esta función era la puerta completa, y se ejecutaba **después** de que
    aprobaras: varios minutos de silencio con tu dedo puesto en un botón, y un
    «sí» que acababa en nada si la puerta se cerraba después. Ahora, entre tu
    «sí» y el APK instalado hay un `adb install`.

    ## Lo que sigue aquí, y no por capricho
    - que el sello de origen cuadre con el código (un APK de antes no se instala);
    - que el `.verificado` cuadre con **este** binario;
    - que el teléfono esté y **alcance** al bridge. Eso último no se puede
      verificar al compilar: depende del cable, de Tailscale y de si la app está
      encendida, y cambia sin avisar.

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
    «sí». El test unitario no lo vio porque fijó el mock a un `Device`: el
    test estaba mintiendo sobre la firma real, que es la forma más común de que
    un test de contrato no sea un test de contrato. De ahí el test de tipo de
    abajo.
    """
    dev = disp.telefono()
    if dev is None:
        raise PuertaCerrada(
            "tu teléfono no está conectado por adb, así que no puedo instalar. "
            "Las pruebas siguen bien: van al emulador, que replica el galaxy a17.")
    if (desactualizado := apk_desactualizado(APK_TELEFONO)):
        raise PuertaCerrada(desactualizado)
    if (sin_verificar := apk_sin_verificar(APK_TELEFONO)):
        raise PuertaCerrada(sin_verificar)
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
    if desactualizado := apk_desactualizado():
        raise PuertaCerrada(desactualizado)
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