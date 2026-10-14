#!/usr/bin/env bash
# =============================================================================
# Aegis — puesta en marcha desde un clon limpio.
#
# Idempotente a propósito: se puede volver a ejecutar sin romper nada. No borra
# `.env`, ni toca `bridge/data/`, ni reinstala el venv si ya está.
#
# ## Por qué existe
# Antes esto eran seis pasos sueltos en el README, y el paso 4 («pega tu
# HERMES_API_KEY») no se podía hacer sin tener Hermes. Ahora es un comando, y lo
# que falta se dice. Un README que hay que traducir a pasos manuales es un README
# que la gente no ejecuta, y un README que no se ejecuta no es documentación.
#
#   bash infra/setup.sh              # todo
#   bash infra/setup.sh --sin-modelos # no descarga nada de Ollama
#   bash infra/setup.sh --comprobar   # solo informa, no cambia nada
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIDGE="$RAIZ/bridge"
VERDE=$'\033[32m'; AMARILLO=$'\033[33m'; ROJO=$'\033[31m'; RESET=$'\033[0m'
fallos=0
avisos=0

solo_comprobar=0
con_modelos=1
for arg in "$@"; do
  case "$arg" in
    --sin-modelos) con_modelos=0 ;;
    --comprobar)   solo_comprobar=1 ;;
    -h|--help)     sed -n '2,18p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "${ROJO}Opción desconocida: $arg${RESET}" >&2; exit 2 ;;
  esac
done

ok()    { printf '  %s✔%s %s\n' "$VERDE" "$RESET" "$1"; }
aviso() { printf '  %s▲%s %s\n' "$AMARILLO" "$RESET" "$1"; avisos=$((avisos+1)); }
mal()   { printf '  %s✘%s %s\n' "$ROJO" "$RESET" "$1"; fallos=$((fallos+1)); }

# ── 1. Python ───────────────────────────────────────────────────────────────
echo
echo "1) Python"
PYTHON=""
for candidato in python3.14 python3.13 python3.12 python3; do
  if command -v "$candidato" >/dev/null 2>&1; then
    version="$("$candidato" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    mayor="${version%%.*}"; menor="${version##*.}"
    if [[ "$mayor" -gt 3 || ( "$mayor" -eq 3 && "$menor" -ge 12 ) ]]; then
      PYTHON="$candidato"; break
    fi
  fi
done
if [[ -z "$PYTHON" ]]; then
  mal "Python 3.12 o superior. Found: $(python3 --version 2>&1 || echo 'nada')"
  echo "     Debian/Ubuntu: sudo apt install python3.12-venv   ·   Fedora: sudo dnf install python3.12"
  echo "     macOS: brew install python@3.12   ·   Arch: ya está"
  exit 1
fi
ok "$($PYTHON --version) ($(command -v "$PYTHON"))"

# ── 2. Entorno virtual y dependencias ────────────────────────────────────────
echo
echo "2) Entorno virtual del bridge"
if [[ ! -d "$BRIDGE/.venv" ]]; then
  [[ $solo_comprobar -eq 1 ]] && aviso "no existe bridge/.venv (se crearía)"
  if [[ $solo_comprobar -eq 0 ]]; then
    "$PYTHON" -m venv "$BRIDGE/.venv"
    ok "creado bridge/.venv"
  fi
else
  ok "ya existe bridge/.venv"
fi

if [[ -x "$BRIDGE/.venv/bin/python" && $solo_comprobar -eq 0 ]]; then
  "$BRIDGE/.venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
  if "$BRIDGE/.venv/bin/pip" install --quiet --requirement "$BRIDGE/requirements.txt"; then
    ok "dependencias instaladas"
  else
    mal "las dependencias no se instalaron (mira el error de arriba)"
  fi
fi

# ── 3. Configuración ─────────────────────────────────────────────────────────
echo
echo "3) Configuración"
if [[ -f "$BRIDGE/.env" ]]; then
  ok "bridge/.env ya existe: no se toca"
else
  if [[ $solo_comprobar -eq 0 ]]; then
    cp "$BRIDGE/.env.example" "$BRIDGE/.env"
    # La clave de operación se genera aquí y no se imprime. Una clave en la
    # salida de un script acaba en la transcripción de un terminal, en un
    # screenshot o en un log de CI.
    clave="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    # `sed` en vez de `>>`: el `.env.example` documenta la variable, y si se
    # añadiera al final habría dos líneas con el mismo nombre.
    if grep -q '^AEGIS_API_KEY=' "$BRIDGE/.env"; then
      sed -i "s|^AEGIS_API_KEY=.*|AEGIS_API_KEY=$clave|" "$BRIDGE/.env"
    else
      printf '\nAEGIS_API_KEY=%s\n' "$clave" >> "$BRIDGE/.env"
    fi
    chmod 600 "$BRIDGE/.env"
    ok "bridge/.env creado, con una AEGIS_API_KEY nueva (no se imprime)"
  else
    aviso "no existe bridge/.env (se crearía desde .env.example)"
  fi
fi

if [[ ! -f "$BRIDGE/quien-eres.md" && -f "$BRIDGE/quien-eres.ejemplo.md" && $solo_comprobar -eq 0 ]]; then
  cp "$BRIDGE/quien-eres.ejemplo.md" "$BRIDGE/quien-eres.md"
  ok "bridge/quien-eres.md creado desde la plantilla (edítalo: es tuyo, no se versiona)"
fi

# ── 4. Toolchain opcional ────────────────────────────────────────────────────
# Ninguna de estas es necesaria para el bridge. Aegis arranca sin ellas y dice
# qué falta cuando las necesita; no se bloquea el arranque por algo que solo hace
# falta para compilar la app.
echo
echo "4) Herramientas opcionales (solo hacen falta para la app móvil)"
resolver() {
  command -v "$1" 2>/dev/null && return 0
  for dir in "${@:2}"; do [[ -x "$dir/$1" ]] && echo "$dir/$1" && return 0; done
  return 1
}

FLUTTER_BIN="$(resolver flutter "$HOME/development/flutter/bin" "$HOME/flutter/bin" || true)"
ADB_DIR="$(resolver adb "$HOME/Android/Sdk/platform-tools" || true)"
JAVA_DIR="$(resolver javac "$HOME/jdk/bin" /usr/lib/jvm/default-java/bin || true)"

[[ -n "$FLUTTER_BIN" ]] && ok "Flutter:  $FLUTTER_BIN" \
  || aviso "Flutter no está. Sin él no se compila la app; el bridge va igual."
[[ -n "$ADB_DIR" ]]    && ok "adb:      $ADB_DIR" \
  || aviso "adb no está. Sin él no hay emulador ni teléfono; el bridge va igual."
[[ -n "$JAVA_DIR" ]]    && ok "JDK:      $JAVA_DIR" \
  || aviso "JDK no está. Gradle no arranca sin él; el bridge va igual."

if [[ -z "$FLUTTER_BIN" || -z "$ADB_DIR" || -z "$JAVA_DIR" ]]; then
  echo "     Si los tienes fuera del PATH, dime dónde en bridge/.env:"
  echo "     AEGIS_FLUTTER_BIN=  AEGIS_ADB=  AEGIS_JAVA_HOME="
fi

# ── 5. Modelos ───────────────────────────────────────────────────────────────
echo
echo "5) Modelos de Ollama"
OLLAMA_BIN="$(resolver ollama "$HOME/.local/bin" "$HOME/.ollama/bin" || true)"
if [[ -z "$OLLAMA_BIN" ]]; then
  aviso "ollama no está. Instálalo de https://ollama.com/install.sh"
elif [[ $con_modelos -eq 0 || $solo_comprobar -eq 1 ]]; then
  ok "ollama presente ($OLLAMA_BIN); no se descarga nada (--sin-modelos)"
else
  ok "ollama: $OLLAMA_BIN"
  # El modelo grande, los embeddings y el de T1. Si Ollama no responde, se dice
  # y se sigue: el bridge no necesita ningún modelo para arrancar.
  for modelo in qwen2.5-coder:7b nomic-embed-text llama3.2:3b; do
    if "$OLLAMA_BIN" list 2>/dev/null | grep -q "^${modelo%%:*}"; then
      ok "$modelo ya está"
    else
      aviso "bajando $modelo (puede tardar; Ctrl-C lo para sin romper nada)"
      "$OLLAMA_BIN" pull "$modelo" >/dev/null 2>&1 && ok "$modelo" \
        || aviso "no se pudo bajar $modelo: lanza «$OLLAMA_BIN serve» y repítelo"
    fi
  done
fi

# ── 6. Comprobación ──────────────────────────────────────────────────────────
echo
echo "6) Comprobación"
if [[ -x "$BRIDGE/.venv/bin/python" && $solo_comprobar -eq 0 ]]; then
  if ( cd "$BRIDGE" && .venv/bin/python bin/check-imports.py >/dev/null 2>&1 ); then
    ok "check-imports: los módulos importan"
  else
    mal "check-imports ha fallado"
    ( cd "$BRIDGE" && .venv/bin/python bin/check-imports.py ) || true
  fi
  if ( cd "$BRIDGE" && .venv/bin/python -m unittest discover -s tests -q >/dev/null 2>&1 ); then
    ok "suite de tests en verde"
  else
    mal "algún test ha fallado"
  fi
fi

# ── Resumen ──────────────────────────────────────────────────────────────────
echo
if [[ $fallos -eq 0 ]]; then
  printf '%sListo.%s' "$VERDE" "$RESET"
  [[ $avisos -gt 0 ]] && printf ' Con %s aviso(s): eso que falta es opcional para el bridge.' "$avisos"
  echo
else
  printf '%s%d cosa(s) que no se pudieron hacer.%s\n' "$ROJO" "$fallos" "$RESET"
fi
echo
echo "Siguiente paso:"
echo "  bash infra/stack.sh arrancar      # Ollama + gateway + bridge"
echo "  bash infra/stack.sh estado       # salud y permisos"
echo "  cd bridge && bin/api POST autopilot '{\"prompt\":\"hola\"}'"
echo
exit $((fallos > 0 ? 1 : 0))