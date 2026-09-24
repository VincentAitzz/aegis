#!/usr/bin/env bash
# Instala el APK de Aegis Console en un teléfono físico y abre el túnel adb reverse
# para que la app alcance el bridge/backend local SIN Tailscale aún.
#
# Requisitos:
#   - Teléfono con depuración USB activada (Ajustes > Opciones de desarrollador > Depuración USB).
#   - El bridge corriendo en la máquina (127.0.0.1:8000) y Ollama en 127.0.0.1:11434.
#
# Uso:  ./infra/mobile/install-phone.sh [api_host]  (api_host por defecto: localhost)
set -euo pipefail

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/RUTA/AL/SDK-ANDROID}}"
ADB="$SDK/platform-tools/adb"
APK="/RUTA/AL/REPO/mobile/build/app/outputs/flutter-apk/app-debug.apk"
API_HOST="${1:-localhost}"

command -v "$ADB" >/dev/null || { echo "adb no encontrado en $ADB"; exit 1; }
[ -f "$APK" ] || { echo "APK no encontrado. Compílalo primero: cd mobile && flutter build apk --debug"; exit 1; }

"$ADB" devices
echo
echo "[1/3] Instalando APK…"
"$ADB" install -r "$APK"
echo "[2/3] Abriendo túneles localhost (bridge:8000, ollama:11434)…"
"$ADB" reverse tcp:8000 tcp:8000
"$ADB" reverse tcp:11434 tcp:11434
echo "[3/3] Arrancando Aegis Console (API_HOST=$API_HOST)…"
"$ADB" shell am start -n com.aegis.aegis_console/.MainActivity
echo
echo "Listo. Sniffing rápido de adb reverse:"
"$ADB" reverse --list