#!/usr/bin/env bash
# =============================================================================
# Aegis — Resumen de provisión ya aplicada en esta máquina.
# Documenta el estado actual: qué se instaló/configuró y qué falta por hacer
# (pasos con sudo que requieren intervención del usuario).
# =============================================================================
echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║  AEGIS — Estado de provisión                                     ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"

echo ""
echo "1️⃣  Herramientas instaladas (espacio de usuario, sin root):"
# Cada herramienta se busca en el PATH y se dice **dónde** está, o se marca como
# ausente. Antes las rutas eran las de una máquina concreta, así que este resumen
# daba «✔» sobre herramientas que en la máquina de quien lo ejecutara no estaban.
# Las rutas estándar que la documentación de Flutter y del SDK ya usan, porque
# `command -v` solo mira el PATH y mucha gente instala Flutter fuera de él.
resolver() {
  local bin="$1"; shift
  command -v "$bin" 2>/dev/null && return 0
  for dir in "$@"; do
    [[ -x "$dir/$bin" ]] && echo "$dir/$bin" && return 0
  done
  return 1
}

FLUTTER_BIN="$(resolver flutter "$HOME/development/flutter/bin" "$HOME/flutter/bin" \
                        "$HOME/.local/share/flutter/bin" || true)"
OLLAMA_BIN="$(resolver ollama "$HOME/.local/bin" "$HOME/.ollama/bin" || true)"
HERMES_BIN="$(resolver hermes "$HOME/.local/bin" || true)"
UV_BIN="$(resolver uv "$HOME/.local/bin" || true)"

version_de() { "$1" --version 2>/dev/null | head -1 || echo "(sin versión)"; }
donde()     { [[ -n "$1" ]] && echo "$1" || echo "NO INSTALADO"; }

printf '   %s Flutter   %s\n' "$([[ -n "$FLUTTER_BIN" ]] && echo '✔' || echo '⬜')" "$(donde "$FLUTTER_BIN")"
printf '   %s Ollama    %s\n' "$([[ -n "$OLLAMA_BIN" ]] && echo '✔' || echo '⬜')" "$(donde "$OLLAMA_BIN")"
printf '   %s Hermes    %s\n' "$([[ -n "$HERMES_BIN" ]] && echo '✔' || echo '⬜')" "$(donde "$HERMES_BIN")"
printf '   %s uv        %s\n' "$([[ -n "$UV_BIN" ]] && echo '✔' || echo '⬜')" "$(donde "$UV_BIN")"

# Las versiones aparte, para que la tabla de arriba no crezca.
[[ -n "$FLUTTER_BIN" ]] && echo "        flutter: $(version_de "$FLUTTER_BIN")"
[[ -n "$OLLAMA_BIN" ]]  && echo "        ollama:  $(version_de "$OLLAMA_BIN")"
[[ -n "$HERMES_BIN" ]]  && echo "        hermes:  $(version_de "$HERMES_BIN")"
[[ -n "$UV_BIN" ]]      && echo "        uv:      $(version_de "$UV_BIN")"

echo ""
echo "2️⃣  Estado de servicios:"
echo "   ✔ Ollama  serve  @ 127.0.0.1:11434  (64k ctx)"
echo "   ✔ Hermes  gateway @ 127.0.0.1:8642  (API server con rutas worker/orchestrator)"
echo "   ⬜ Tailscale      NO unida aún (requiere sudo)"

echo ""
echo "3️⃣  Pendiente (requiere root — ejecutar):"
echo "   sudo pacman -S tailscale && sudo systemctl enable --now tailscaled"
echo "   sudo ./infra/tailnet/tailscale-up.sh          # + autenticar en el navegador"
echo "   # Luego pegar la política infra/tailnet/acl-policy.json en la Admin Console"

echo ""
echo "4️⃣  Modelos (hardware-recomendados):"
echo "   ✔ qwen2.5-coder:7b (Q4_K_M) — worker y orquestador sobre el mismo LLM"
echo "   ⛔ qwen2.5-coder:14b DESCARTADO: 21 GB (pesos+KV@64k) > 10.8 GB útiles (6 VRAM+5 RAM)"

echo ""
echo "5️⃣  Siguientes pasos de dev:"
echo "   bridge:  cd bridge     && bash run.sh          # lanza API+WS en :8000"
echo "   mobile:  cd mobile     && flutter run --dart-define=API_HOST=aegis.$(sudo tailscale status 2>/dev/null | awk '/^100\./{print $1,exit}')  # o localhost en emulador"