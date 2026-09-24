#!/usr/bin/env bash
# =============================================================================
# Aegis — Resumen de provisión ya aplicada en esta máquina.
# Documenta el estado actual: qué se instaló/configuró y qué falta por hacer
# (pasos con sudo que requieren intervención del usuario).
# =============================================================================
echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║  AEGIS — Estado de provisión (CachyOS)                            ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"

echo ""
echo "1️⃣  Herramientas instaladas (espacio de usuario, sin root):"
echo "   ✔ Flutter   ~/development/flutter  ($(/RUTA/A/FLUTTER/bin/flutter --version 2>/dev/null | head -1))"
echo "   ✔ Ollama    ~/.local/bin/ollama     ($(/RUTA/A/BIN/ollama --version 2>&1 | tail -1))"
echo "   ✔ Hermes    ~/.local/bin/hermes     ($(/RUTA/A/BIN/hermes --version 2>/dev/null | head -1 | cut -c1-50))"
echo "   ✔ uv        ~/.local/bin/uv         ($(/RUTA/A/BIN/uv --version 2>/dev/null | head -1))"

echo ""
echo "2️⃣  Estado de servicios:"
echo "   ✔ Ollama  serve  @ 127.0.0.1:11434  (64k ctx, CUDA RTX 3050)"
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