"""Dispositivos adb: cuál es el emulador y cuál es el teléfono.

## La regla

**El teléfono no se elige solo.** Antes `_resolve_device()` devolvía el galaxy
por mDNS o Tailscale, y `install_apk` lanzaba la app encima. Eso significa que
una prueba de Aegis te puede interrumpir a media cosa, sin avisar. Aquí el
teléfono solo se toca cuando alguien lo pide **explícitamente** y con la puerta
de despliegue en verde.

El emulador es el destino por defecto, por dos razones: no interrumpe a nadie,
y está configurado para replicar el galaxy a17 (Android 16, 1080x2340, 450 dpi).
Misma versión de Android y misma geometría significan que una prueba de layout
significa algo.

## Por qué un módulo aparte

Son ~200 líneas de lógica de dispositivos que no toquen los guardarraíles de
ruta, y que tienen sus propias pruebas. En `mcp_ops.py` competían con lo que
importa: la whitelist y el escaneo de secretos.
"""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SDK = os.environ.get("ANDROID_SDK_ROOT",
                     os.environ.get("ANDROID_HOME",
                                    os.path.expanduser("~/Android/Sdk")))
ADB = f"{SDK}/platform-tools/adb"
FLUTTER = os.path.expanduser("~/development/flutter/bin")
JAVA_HOME = os.path.expanduser("~/jdk")
EMULATOR_SCRIPT = os.path.expanduser("~/Workspace/aegis/infra/mobile/emulador.sh")

#: Serial del emulador de Aegis. Es el que crea `infra/mobile/emulador.sh`.
EMULATOR_SERIAL = os.environ.get("AEGIS_EMULATOR_SERIAL", "emulator-5554")

#: El teléfono: lo que el usuario lleva encima. No se elige por descarte.
PHONE_SERIAL_ENV = os.environ.get("AEGIS_PHONE_SERIAL", "")

TARGETS = ("emulador", "telefono")
PAQUETE = "com.aegis.aegis_console"

#: adb marca el duplicado de un mismo dispositivo como `nombre (2)`, y el
#: contador va EN MEDIO del serial (antes del sufijo de mDNS), no al final.
_DUP_SUFIJO = re.compile(r"\s*\(\d+\)")


@dataclass
class Device:
    serial: str
    state: str

    @property
    def emulador(self) -> bool:
        return self.serial.startswith("emulator-")

    @property
    def disponible(self) -> bool:
        return self.state == "device"

    @property
    def etiqueta(self) -> str:
        if self.emulador:
            return "EMULADOR"
        return "TELEFONO"


class DeviceError(RuntimeError):
    """No hay dispositivo del tipo pedido, o adb no respondió."""


def shell_quote(texto: str) -> str:
    """Entrecomilla un argumento para el shell **del dispositivo**.

    `adb shell` concatena los argumentos y los manda al shell del teléfono, que
    los vuelve a parsear. Un argumento con espacios se parte en varios: se
   se parte en varios y se pierde: queda `--title PRUEBA` con el tag
    equivocado. Comprobado: el aviso salía
    con el título y el tag intercambiados y parecía funcionar.

    Por eso los textos con espacios van entrecomillados aquí, no en la llamada.
    """
    return "'" + str(texto).replace("'", "'\\''") + "'"


def _adb(args: list[str], timeout: int = 60,
         serial: str = "") -> tuple[int, str]:
    """Ejecuta adb. Un dispositivo inalcanzable no rompe la tool: avisa."""
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([f"{JAVA_HOME}/bin", FLUTTER, f"{SDK}/platform-tools",
                                   env.get("PATH", "")])
    cmd = [ADB] + (["-s", serial] if serial else []) + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"adb {args[0]} agotó {timeout}s (dispositivo inalcanzable)"
    return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())


def dispositivos() -> list[Device]:
    """Los dispositivos que adb ve, con su etiqueta de emulador o teléfono."""
    code, out = _adb(["devices"], timeout=30)
    if code != 0:
        raise DeviceError(f"adb devices falló (exit={code}): {out[:200]}")
    vistos: dict[str, str] = {}
    for serial, state in ((p[0].strip(), p[1].strip()) for p in
                          (line.split("\t") for line in out.splitlines()[1:])
                          if len(p) >= 2):
        if not serial:
            continue
        # adb registra el mismo dispositivo por mDNS más de una vez y marca el
        # duplicado con ` (2)`. No son dos teléfonos: es el mismo, y contarlos
        # dos hace que `telefono()` se queje de que hay un montón.
        base = _DUP_SUFIJO.sub("", serial)
        if base not in vistos or not _DUP_SUFIJO.search(serial):
            # Se prefiere el serial sin contador: el duplicado `(2)` de adb es
            # volátil, y quedarse con él rompe cuando adb deja de anunciarlo.
            vistos[base] = serial
    return _unificar_por_identidad(
        [Device(serial=s, state="device") for s in vistos.values()])


def _identidad_hardware(dev: Device) -> str:
    """El número de serie **del aparato**, no el de la conexión.

    ## Por qué hace falta
    Un mismo teléfono se puede registrar en adb por dos vías a la vez: el nombre
    mDNS y el `host:puerto` de un `adb connect`. Son dos seriales, un solo
    aparato. Contarlos como dos teléfonos hacía que `telefono()` se quejara de
    «hay 2 teléfonos» y **todo** lo del teléfono se detuviera, con el móvil
    delante.

    `ro.serialno` es del hardware, no de la conexión, así que es lo que dice si
    son el mismo.

    ## Por qué se valida lo que viene
    Porque la consecuencia de equivocarse aquí es instalar en el aparato
    equivocado. Si la salida no parece un número de serie —viene vacía, trae
    varias líneas, o es un mensaje de error— se devuelve el **serial de la
    conexión**, que no unifica nada. Ante la duda, dos: peor contar dos teléfonos
    que uno que se puede pedir, que unificar dos aparatos distintos.
    """
    code, out = _adb(["-s", dev.serial, "shell", "getprop", "ro.serialno"],
                     timeout=20, serial=dev.serial)
    limpio = out.strip()
    if code == 0 and limpio and "\n" not in limpio and "\t" not in limpio \
            and len(limpio) <= 64:
        return f"hw:{limpio}"
    return f"con:{dev.serial}"


def _unificar_por_identidad(devs: list[Device]) -> list[Device]:
    """Un aparato, una entrada, aunque adb lo vea por dos vías.

    ## Por qué el emulador se queda aparte
    Un emulador y un teléfono físico pueden devolver el mismo `ro.serialno` —en
    una AVD clonada es fácil— y unificarlos dejaría al emulador sin su entrada:
    se acabaría instalando una prueba de `localhost` en un aparato real, que es el
    fallo que los nombres de fichero existen para evitar. El emulador se
    identifica por su propio serial (`emulator-NNNN`), que ya es único.
    """
    por_identidad: dict[str, Device] = {}
    for d in devs:
        ident = d.serial if d.emulador else _identidad_hardware(d)
        previa = por_identidad.get(ident)
        if previa is None:
            por_identidad[ident] = d
            continue
        # Se queda el mDNS: es estable, no cambia de puerto en cada reinicio, y
        # es el que usa `adb connect` por defecto. Quedarse con el otro
        # significaría que el serial cambia solo.
        if "_adb-tls-connect" in d.serial and "_adb-tls-connect" not in previa.serial:
            por_identidad[ident] = d
    return list(por_identidad.values())


def emulador() -> Device | None:
    """El emulador de Aegis, si está conectado."""
    for d in dispositivos():
        if d.emulador and d.disponible:
            return d
    return None


def telefono() -> Device | None:
    """El teléfono del usuario, si está conectado.

    Se reconoce por el mDNS (`_adb-tls-connect`), por el serial configurado, o
    por ser un `adb connect host:puerto` a una IP. Nunca se devuelve "el que
    quede": si hay varios, es un error.

    ## Por qué la IP cuenta como teléfono
    Porque es lo que produce la ruta manual que documenta el runbook:
    `adb mdns services` → `adb connect <ip>:<puerto>`. En esa forma el serial es
    `100.101.102.103:46119`, **sin** `_adb-tls-connect`, así que la puerta decía
    «tu teléfono no aparece en adb» con el teléfono ahí, conectado y respondiendo
    — la tool, suplicando que lo conectaras mientras estaba delante (A-046).

    Lo que se descarta sigue siendo el emulador y el propio host, así que «un
    dispositivo que no es el emulador y se conectó por una IP» no se está
    suponiendo: se está leyendo. Y si hay dos, sigue pidiendo que digas cuál.
    """
    cands = [d for d in dispositivos()
             if not d.emulador and d.disponible and _parece_telefono(d.serial)]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        return None
    raise DeviceError(
        f"hay {len(cands)} teléfonos conectados ({', '.join(d.serial for d in cands)}). "
        f"Dilo cuál con target='telefono:<serial>'."
    )


_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _parece_telefono(serial: str) -> bool:
    """¿Este serial puede ser el teléfono del usuario?

    Tres formas, y solo tres:

    1. el nombre que publica el teléfono por mDNS (`_adb-tls-connect`);
    2. el serial que alguien configuró a mano (`AEGIS_PHONE_SERIAL`);
    3. `host:puerto` de un `adb connect` a una IP que no sea el loopback.

    La tercera es la que faltaba. La condición es «IP, no loopback» y no «hay un
    `:` en el serial», porque `emulator-5554` no tiene puerto pero cualquier
    `adb connect` a `localhost` tampoco, y `localhost` no es el teléfono de nadie.
    """
    if "_adb-tls-connect" in serial:
        return True
    if PHONE_SERIAL_ENV and serial == PHONE_SERIAL_ENV:
        return True
    host, sep, puerto = serial.rpartition(":")
    if not sep or not puerto.isdigit():
        return False
    return bool(host) and host not in _LOOPBACK


def resolver(target: str = "emulador") -> Device:
    """El dispositivo para `target`. Falla con un mensaje que dice qué hacer.

    No hay valor por defecto "el que aparezca primero": el emulador es el
    destino de las pruebas, y el teléfono requiere nombrarlo.
    """
    target = (target or "emulador").strip()
    if ":" in target:
        target, _, serial = target.partition(":")
        for d in dispositivos():
            if d.serial == serial and d.disponible:
                return d
        raise DeviceError(
            f"'{serial}' no aparece en adb devices. Revisa con adb_devices().")
    if target not in TARGETS:
        raise DeviceError(f"target inválido: {target!r}. Usa {TARGETS}.")
    if target == "emulador":
        d = emulador()
        if d is None:
            raise DeviceError(
                "el emulador no está corriendo. Arráncalo con:\n"
                f"  bash {EMULATOR_SCRIPT} arrancar\n"
                "Las pruebas van ahí, no en tu teléfono: el emulador replica el "
                "galaxy a17 (Android 16, 1080x2340, 450 dpi) y no te interrumpe.")
        return d
    d = telefono()
    if d is None:
        raise DeviceError(
            "tu teléfono no aparece en adb. Conéctalo:\n"
            f"  adb connect <host>:<puerto>   # el puerto sale de: adb mdns services\n"
            "Si no lo encuentras, Aegis no puede instalar ahí — y no va a intentarlo "
            "a ciegas.")
    return d


def tailnet_ip() -> str:
    """La IP de **esta máquina** en la tailnet, o "" si no se puede saber.

    El teléfono habla con el bridge por Tailscale, así que necesita la dirección
    de la máquina que lo aloja. No se adivina: o se pregunta a `tailscale`, o se
    usa lo que el usuario exporte, o no se compila.
    """
    ip = os.environ.get("AEGIS_BRIDGE_TAILNET_IP", "").strip()
    if ip:
        return ip
    try:
        proc = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip().splitlines()[0] if proc.returncode == 0 else ""


def instalado(dev: Device) -> bool:
    """¿Está la app en ese dispositivo?

    Importa más de lo que parece: es lo que separa "instalar por primera vez" de
    "volver a instalar encima de lo que estás usando", y esas dos cosas no pueden
    ser lo mismo.

    ## Fallar cerrado
    `pm path` sale 1 tanto si el paquete no existe como si adb no llegó al
    dispositivo, y confundirlos abriría la puerta: un teléfono inalcanzable se
    leería como "primera vez" y se instalaría sin preguntar. Los tres casos se
    distinguen por lo que contestan:

    - `package:...` → está instalada;
    - nada de salida → el paquete no existe, y es la primera vez;
    - mensaje de adb → el dispositivo no se pudo consultar, y se dice, en vez de
      asumir.
    """
    code, out = _adb(["-s", dev.serial, "shell", "pm", "path", PAQUETE], timeout=60)
    if "package:" in out:
        return True
    if not out:
        return False
    raise DeviceError(
        f"no pude preguntar a {dev.serial} si tiene la app: {out[:160]}\n"
        "No lo doy por no instalado, porque eso dejaría la puerta abierta. "
        "Revisa la conexión adb y vuelve a intentarlo.")


def api_host_para(target: str) -> str:
    """La dirección del bridge que debe llevar la app según el destino.

    El emulador llega al bridge por `adb reverse`, así que `localhost`. El
    teléfono, por Tailscale. Confundirlos produce una app que arranca pero no ve
    nada, que es el fallo más difícil de ver en una prueba.

    ## Por qué no lleva una IP de reserva
    Antes llevaba `100.101.102.103` de valor por defecto, y esa es la IP **del
    teléfono**. Un teléfono al que se le pone su propia dirección compila, se
    instala, arranca y no ve el bridge: cuatro pasos correctos y un fallo que no
    aparece hasta que se busca. Si no se puede averiguar la IP del bridge, aquí
    se dice en voz alta en lugar de devolver algo plausible.
    """
    if not target.startswith("telefono"):
        return "localhost"
    host = tailnet_ip()
    if not host:
        raise DeviceError(
            "no sé la IP de esta máquina en la tailnet, que es a donde debe "
            "apuntar la app del teléfono.\n"
            "  Con la tailnet viva:  tailscale ip -4\n"
            "  O explícitamente:      export AEGIS_BRIDGE_TAILNET_IP=<ip-del-bridge>\n"
            "No compilo un APK con una dirección inventada.")
    return host


def telefono_alcanza(host: str, puerto: int = 8000, timeout: int = 6) -> tuple[bool, str]:
    """¿Puede el teléfono abrir TCP contra `host:puerto`? Lo pregunta al teléfono.

    ## Por qué hay que preguntar
    `api_host_para("telefono")` devuelve una dirección **razonable**, no una
    comprobada. El caso real de A-022 grew: la tailnet estaba bien en el portátil,
    Tailscale instalado en el teléfono pero sin sesión, así que un APK de teléfono
    instalado con esa dirección abría y no veía nada. Ni error ni aviso: la app
    arranca, dibuja su HUD y está muerta.

    ## Cómo se mide
    `nc` del teléfono, que es lo único de red que trae de serie: sale 0 si abre
    la conexión y 1 si se agota el tiempo. Si `nc` no existe se dice, porque "no
    pude comprobar" y "no llega" no son lo mismo y aquí la diferencia decide si se
    instala o no.
    """
    dev = telefono()
    if dev is None:
        return False, "el teléfono no está conectado por adb, así que no puedo " \
                      "comprobar si lo alcanza. Sin esa comprobación, instalar un " \
                      "APK con una dirección sin verificar sería instalar a ciegas."
    code, out = _adb(["-s", dev.serial, "shell",
                      f"nc -w {timeout} {host} {puerto} </dev/null"],
                     timeout=timeout + 20)
    if "inaccessible" in out or "not found" in out:
        return False, (f"el teléfono no tiene `nc`, así que no pude comprobar si "
                       f"llega a {host}:{puerto}. Sin esa comprobación, instalar "
                       "un APK con una dirección sin verificar sería a ciegas.")
    if code == 0:
        return True, f"el teléfono abre TCP contra {host}:{puerto}"
    return False, (f"el teléfono NO llega a {host}:{puerto} (nc exit={code}). "
                   "Si esperabas la tailnet, Tailscale no está conectado en el "
                   "teléfono; si esperabas la red local, mira `ufw` en el "
                   "portátil, que bloquea lo que entra.")


def apk_para(base: str) -> Path:
    """El APK de un destino, con nombre propio.

    ## Por qué un fichero por destino
    Los dos binarios son distintos: el del emulador lleva `API_HOST=localhost`, y
    el del teléfono la IP de la tailnet. Con un único `app-debug.apk` —que es lo
    que hace Flutter— compilar para el teléfono deja en el emulador un APK que no
    ve nada, e instalar en el telefone un APK que se queda en localhost. Ambos
    fallos son silenciosos: la app abre y no se entera de nada.

    `build_apk` mueve la salida a este nombre, así que el nombre dice a quién
    pertenece y no hay que acordarse de qué se compiló la última vez.
    """
    return Path(os.path.expanduser("~/Workspace/aegis/mobile")) / (
        f"build/app/outputs/flutter-apk/app-debug-{base}.apk")


def apk_legacy() -> Path:
    """El nombre que Flutter deja por defecto. Solo para diagnóstico."""
    return apk_para("x").with_name("app-debug.apk")


def estado_humano() -> str:
    """`adb devices` etiquetado, para que se sepa cuál es cuál de un vistazo.

    Con los dos conectados, la salida cruda de adb no los distingue y es donde
    más fácil es instalar en el que no es.
    """
    devs = dispositivos()
    if not devs:
        return "adb no ve ningún dispositivo."
    filas = ["dispositivos adb:"]
    for d in devs:
        estado = "conectado" if d.disponible else d.state
        filas.append(f"  {d.etiqueta:9} {d.serial:52} {estado}")
    emu = next((d for d in devs if d.emulador), None)
    tel = next((d for d in devs if not d.emulador), None)
    filas.append("")
    filas.append(f"  destino por defecto de las pruebas: "
                 f"{'emulador ' + emu.serial if emu else 'emulador (apagado)'}")
    filas.append(f"  tu teléfono: "
                 f"{tel.serial if tel else 'no conectado'} "
                 f"— requiere target='telefono' y la puerta de despliegue")
    return "\n".join(filas)


def arrancar_emulador() -> tuple[int, str]:
    """Levanta el emulador. Idempotente: si ya está, no hace nada."""
    if emulador() is not None:
        return 0, "el emulador ya estaba corriendo"
    if not os.path.exists(EMULADOR_SCRIPT):
        return 1, f"no encuentro {EMULATOR_SCRIPT}"
    proc = subprocess.run(["bash", EMULADOR_SCRIPT, "arrancar"],
                          capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout + proc.stderr).strip()[-500:]


def logcat_fatal(serial: str, desde: float) -> str:
    """Excepciones fatales de la app en logcat desde `desde` (epoch segundos).

    Con `-T <epoch>` Android filtra por tiempo, así que no sale lo de arranques
    anteriores y el humo no se ensucia con historia vieja.
    """
    stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(desde))
    _, out = _adb(["logcat", "-d", "-T", stamp, "-b", "crash"], timeout=60, serial=serial)
    _, full = _adb(["logcat", "-d", "-T", stamp], timeout=60, serial=serial)
    texto = out + "\n" + full
    marcas = [l for l in texto.splitlines()
              if "aegis_console" in l and re.search(
                  r"FATAL EXCEPTION|Unhandled Exception|E/flutter", l)]
    return "\n".join(marcas[:12])