#!/usr/bin/env bash
# Emulador de Aegis, replicando el galaxy a17 (SM-A175F).
#
# Por qué existe: Aegis prueba la app aquí, no en el teléfono. Instalar y
# lanzar en el teléfono interrumpe a la persona, y el modo de fallo que nos
# importó (A-016) fue un sistema que reportaba éxito sin comprobar. Un emulador
# que nadie está usando no puede interrumpir a nadie.
#
# Copia del dispositivo real, medido con adb:
#   Android 16 (API 36) · 1080x2340 · 450 dpi · arm64-v8a
#
# Lo que NO se replica, y por qué: la ABI. El teléfono es arm64-v8a y esta
# máquina es x86_64, así que el emulador corre x86_64. Lo que sí importa para
# que una prueba signifique algo —nivel de API, geometría y densidad— se copia.
#
# Uso:
#   ./infra/mobile/emulador.sh crear      # una vez: descarga imagen y crea AVD
#   ./infra/mobile/emulador.sh arrancar   # headless, sin ventana
#   ./infra/mobile/emulador.sh estado
#   ./infra/mobile/emulador.sh parar
set -uo pipefail

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
JAVA="${JAVA_HOME:-$HOME/jdk}"
AVD="${AEGIS_AVD:-aegis-a17}"
SERIAL="${AEGIS_EMULATOR_SERIAL:-emulator-5554}"
IMAGE="system-images;android-36;aosp_atd;x86_64"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"

# Lo que se copió del SM-A175F. Si el teléfono cambia, se re-mide.
API=36
DENSITY=450
GEOMETRY="1080x2340"
# 1 GB a propósito: la máquina anda justa de RAM con el modelo cargado. Súbelo
# con AEGIS_EMU_MEM si hace falta y no hay nada más corriendo.
MEM="${AEGIS_EMU_MEM:-1024}"

log() { printf '%s\n' "$*" >&2; }

avds() { "$SDK/cmdline-tools/latest/bin/avdmanager" list avd 2>/dev/null \
         | grep -oE 'Name: [^ ]+' | sed 's/Name: //'; }

cmd_crear() {
  if [ -x "$EMU" ]; then
    log "el emulador ya está instalado"
  else
    log "descargando emulador + imagen $IMAGE (unos 2 GB)…"
    "$SDK/cmdline-tools/latest/bin/sdkmanager" "emulator" "$IMAGE" >/dev/null || {
      log "sdkmanager falló"; return 1; }
  fi
  if avds | grep -qx "$AVD"; then
    log "el AVD '$AVD' ya existe"
  else
    # Sin `echo no |`: avdmanager cierra la tubería al terminar y el `echo` se
    # come un SIGPIPE, que con `pipefail` hace que esto parezca un fallo aunque
    # avdmanager haya creado el AVD sin problema.
    "$SDK/cmdline-tools/latest/bin/avdmanager" create avd \
      --force --name "$AVD" --package "$IMAGE" --device "pixel_5" \
      </dev/null >/dev/null 2>&1
    avds | grep -qx "$AVD" || { log "avdmanager no creó el AVD"; return 1; }
    log "AVD '$AVD' creado"
  fi
  # La geometría y la densidad van en hardware-qemu.ini, que el AVD no tiene
  # forma de pedir por CLI. Se ajustan aquí para que el layout del emulador se
  # parezca al del teléfono y una prueba de UI signifique algo.
  local ini="$HOME/.android/avd/$AVD.avd/config.ini"
  if [ -f "$ini" ]; then
    grep -q '^hw.lcd.density=' "$ini" \
      && sed -i "s/^hw.lcd.density=.*/hw.lcd.density=$DENSITY/" "$ini" \
      || echo "hw.lcd.density=$DENSITY" >> "$ini"
    grep -q '^hw.lcd.width=' "$ini" \
      && sed -i "s/^hw.lcd.width=.*/hw.lcd.width=${GEOMETRY%x*}/" "$ini" \
      || echo "hw.lcd.width=${GEOMETRY%x*}" >> "$ini"
    grep -q '^hw.lcd.height=' "$ini" \
      && sed -i "s/^hw.lcd.height=.*/hw.lcd.height=${GEOMETRY#*x}/" "$ini" \
      || echo "hw.lcd.height=${GEOMETRY#*x}" >> "$ini"
    log "geometría $GEOMETRY a $DENSITY dpi aplicada"
  else
    log "aviso: no encontré $ini, la geometría queda en el valor por defecto"
  fi
}

cmd_arrancar() {
  [ -x "$EMU" ] || { log "el emulador no está instalado. Ejecuta primero: $0 crear"; return 1; }
  if "$ADB" devices | grep -q "^$SERIAL[[:space:]]"; then
    log "el emulador ya está arriba ($SERIAL)"; return 0
  fi
  log "arrancando $AVD headless ($MEM MB)…"
  ( setsid "$EMU" -avd "$AVD" -port "${SERIAL#emulator-}" \
      -no-window -no-audio -no-boot-anim -no-snapshot \
      -gpu swiftshader_indirect -memory "$MEM" \
      -partition-size 4096 \
      >"$HOME/.android/emulador-$AVD.log" 2>&1 </dev/null & )
  cmd_esperar_boot
}

cmd_esperar_boot() {
  log "esperando a que termine de arrancar (hasta 180 s)…"
  local waited=0
  while [ "$waited" -lt 180 ]; do
    if "$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null \
        | tr -d '\r' | grep -q '^1$'; then
      log "emulador listo"
      # El puerto del bridge, para que la app del emulador lo alcance por
      # localhost igual que el teléfono. Sin esto, el humo no puede hablar
      # con el bridge y la prueba no demuestra nada.
      "$ADB" -s "$SERIAL" reverse tcp:8000 tcp:8000 >/dev/null 2>&1
      return 0
    fi
    sleep 3; waited=$((waited + 3))
  done
  log "el emulador no arrancó en 180 s. Log: $HOME/.android/emulador-$AVD.log"
  return 1
}

cmd_estado() {
  if "$ADB" devices | grep -q "^$SERIAL[[:space:]]"; then
    local boot; boot=$("$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    local rel; rel=$("$ADB" -s "$SERIAL" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
    local dens; dens=$("$ADB" -s "$SERIAL" shell wm density 2>/dev/null | tr -d '\r' | grep -oE '[0-9]+')
    local size; size=$("$ADB" -s "$SERIAL" shell wm size 2>/dev/null | tr -d '\r' | grep -oE '[0-9]+x[0-9]+' | head -1)
    echo "emulador: arriba | android=$rel | $size @ ${dens}dpi | boot=$boot"
  else
    echo "emulador: apagado ($SERIAL no aparece en adb devices)"
  fi
}

cmd_parar() {
  if "$ADB" devices | grep -q "^$SERIAL[[:space:]]"; then
    "$ADB" -s "$SERIAL" emu kill >/dev/null 2>&1
    log "emulador detenido"
  else
    log "el emulador ya estaba apagado"
  fi
}

case "${1:-estado}" in
  crear)    cmd_crear ;;
  arrancar) cmd_arrancar ;;
  estado)   cmd_estado ;;
  parar)    cmd_parar ;;
  *) log "uso: $0 {crear|arrancar|estado|parar}"; exit 2 ;;
esac