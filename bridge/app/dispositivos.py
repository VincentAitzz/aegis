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
    return [Device(serial=s, state="device") for s in vistos.values()]


def emulador() -> Device | None:
    """El emulador de Aegis, si está conectado."""
    for d in dispositivos():
        if d.emulador and d.disponible:
            return d
    return None


def telefono() -> Device | None:
    """El teléfono del usuario, si está conectado.

    Se reconoce por el mDNS (`_adb-tls-connect`) o por el serial configurado.
    Nunca se devuelve "el que quede": si hay varios, es un error.
    """
    cands = [d for d in dispositivos()
             if not d.emulador and d.disponible
             and ("_adb-tls-connect" in d.serial
                  or (PHONE_SERIAL_ENV and d.serial == PHONE_SERIAL_ENV))]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        return None
    raise DeviceError(
        f"hay {len(cands)} teléfonos conectados ({', '.join(d.serial for d in cands)}). "
        f"Dilo cuál con target='telefono:<serial>'."
    )


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