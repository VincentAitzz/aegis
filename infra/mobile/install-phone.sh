#!/usr/bin/env bash
# **INSTALACIÓN** de Aegis Console en el teléfono físico, por USB.
#
# ## Este script NO actualiza. Actualizar es otra cosa
#
# Hay **dos** caminos para poner una build en el teléfono, y confundirlos cuesta
# una tarde:
#
#   - Este script (USB por cable) = **Instalación**. La primera vez, y también
#     cuando hay que cambiar de firma. Requiere que el teléfono esté enchufado.
#   - «Actualizar Aegis», en Ajustes de la app = **Actualización**. El día a día,
#     sin cable. Pide la build al bridge por `GET /apk/telefono`.
#
# La diferencia de fondo no es el cable: es **quién compila y con qué clave**.
# Por USB instala un binario que hay en tu disco, compilado ahora. Por la app
# instala un binario que el bridge sirvió, que el bridge selló y que ya sabe que
# es más nuevo que lo que hay dentro. Instalar por USB una build vieja hace que
# la app no vea actualización pendiente y no avise de nada.
#
# ## Requisitos
#   - Teléfono con depuración USB (Ajustes > Opciones de desarrollador).
#   - `AEGIS_PHONE_SERIAL` en `bridge/.env`, o un teléfono por cable y ya está.
#   - Tailscale **encendido en el teléfono**. Sin él la app no llega al bridge:
#     la build del teléfono apunta a la IP de la malla, no a `localhost`.
#
# ## Antes de ejecutarlo, la build tiene que existir
#
#   cd bridge && bin/api POST autopilot/start \
#     '{"project":"aegis","prompt":"compila el apk de release para el telefono"}'
#
# que deja el binario sellado en
# `mobile/build/app/outputs/flutter-apk/app-release-telefono.apk`.
#
# ## Por qué el APK de release y no el de debug
#
# El `app-debug.apk` firma con la clave **de debug**, que es la del SDK de
# Android y tiene la contraseña publicada. Cualquiera puede generar un APK con
# esa misma firma, y Android indexa el Keystore por paquete **y** certificado:
# misma firma, mismo acceso a las semillas TOTP que hay dentro. Instalado en
# debug, este teléfono queda abierto por construcción —y no hace falta tener el
# teléfono, solo el APK.
set -euo pipefail

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
ADB="$SDK/platform-tools/adb"
PAQUETE="com.aegis.aegis_console"
# El **de release** y con el nombre del destino. Flutter deja los dos perfiles en
# el mismo directorio, así que un nombre que no diga cuál es cuál acabaría
# instalando el binario equivocado por el camino equivocado.
APK="${APK:-$(dirname "$0")/../../mobile/build/app/outputs/flutter-apk/app-release-telefono.apk}"

command -v "$ADB" >/dev/null || { echo "adb no encontrado en $ADB"; exit 1; }

[ -f "$APK" ] || {
  echo "No está el APK de release del teléfono: $APK"
  echo
  echo "Compílalo por el bridge, que es lo que además le pone el sello del token:"
  echo "  cd bridge && bin/api POST autopilot/start \\"
  echo "    '{\"project\":\"aegis\",\"prompt\":\"compila el apk de release para el telefono\"}'"
  exit 1
}

# La firma se comprueba **antes** de instalar, no después.
#
# No es una formalidad: instalar por el camino de siempre y que el binario venga
# firmado con la clave de debug produce una app que funciona perfectamente y que
# deja las semillas TOTP expuestas a cualquiera que genere un APK con la misma
# clave pública. Y el síntoma no aparece nunca en la app: abre, muestra las
# cuentas y genera códigos correctos. Solo se ve mirando la firma.
APKSIGNER="$(ls "$SDK"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1)"
KEYPROPS="${AEGIS_KEY_PROPERTIES:-$HOME/.config/aegis/key.properties}"

if [ -x "$APKSIGNER" ] && [ -f "$KEYPROPS" ]; then
  huella_de_la_apk() {
    "$APKSIGNER" verify --print-certs "$1" 2>/dev/null \
      | awk '/certificate SHA-256 digest/ {print $NF; exit}'
  }
  ALMACEN="$(grep '^storeFile=' "$KEYPROPS" | cut -d= -f2-)"
  ALIAS="$(grep '^keyAlias=' "$KEYPROPS" | cut -d= -f2-)"
  CONTRASENA="$(grep '^storePassword=' "$KEYPROPS" | cut -d= -f2-)"

  # `keytool` imprime `SHA256: FA:30:7A:...` con dos puntos de por medio y
  # `apksigner` los Imprime seguidos. Se quitan todos de los dos lados antes de
  # comparar: comparar los crudos daba "no coincide" con dos APK **idénticas**.
  esperada="$(keytool -list -v -keystore "$ALMACEN" -alias "$ALIAS" \
                -storepass "$CONTRASENA" 2>/dev/null \
              | awk '/SHA256:/ {v=$NF; gsub(/[^0-9A-Fa-f]/,"",v); print tolower(v); exit}')"
  obtenida="$(huella_de_la_apk "$APK" | tr -d ':' | tr 'A-Z' 'a-z')"

  if [ -n "$esperada" ] && [ -n "$obtenida" ]; then
    if [ "$esperada" = "$obtenida" ]; then
      echo "Firma verificada: la APK va con tu clave de release."
    else
      echo "ABORTO: la APK no está firmada con tu clave de release."
      echo "  esperada (tu clave): $esperada"
      echo "  obtenida (la APK):   $obtenida"
      echo
      echo "  Si coincide con la clave de debug del SDK, alguien —o un build por"
      echo "  el camino viejo— seguirá firmando en debug. Instalar eso deja este"
      echo "  teléfono con el Keystore abierto a cualquiera que genere un APK con"
      echo "  la misma firma. Compila por el bridge y vuelve a intentarlo."
      exit 1
    fi
  else
    echo "Aviso: no pude leer una de las dos huellas; sigo sin comprobar la firma."
  fi
else
  echo "Aviso: sin apksigner o sin key.properties no puedo comprobar la firma."
  echo "  Sin ese chequeo, instala solo APKs que se hayan compilado por el bridge."
fi

"$ADB" devices
echo
echo "[1/3] Instalando por USB (INSTALACIÓN, no actualización)…"
"$ADB" install -r "$APK"

echo
echo "[2/3] Arrancando Aegis Console…"
"$ADB" shell am start -n "$PAQUETE/.MainActivity"

echo
echo "[3/3] ¿Llega al bridge? (esto prueba Tailscale, no la app)"
if "$ADB" shell ping -c 1 -W 2 "$(tailscale ip -4 2>/dev/null || echo 127.0.0.1)" >/dev/null 2>&1; then
  echo "  Sí: el túnel está arriba y la app debe ver el bridge."
else
  echo "  NO: el túnel no responde. Sin Tailscale la app abre pero no ve nada —"
  echo "  es el fallo más difícil de ver, porque la app parece Sana."
  echo "  Enciéndelo en el teléfono y vuelve a mirar 'puente: contesta' en la app."
fi

echo
echo "Instalado. Las siguientes actualizaciones van por la app:"
echo "  Ajustes → «Actualizar Aegis»"
echo "Este script es solo para la primera vez o para cambiar de firma."