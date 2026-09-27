#!/usr/bin/env bash
# =============================================================================
# Aegis — lanzador del servidor MCP de memoria (fase 2).
#
# Hermes spawna los MCP stdio con su propio CWD/env; para que el servidor
# resuelva el paquete `app` y sus rutas de datos, fijamos el entorno AQUÍ
# (hermes mcp add no traspasa `--env` fiablmente a los stdio en v0.21).
#
# Registro en ~/.hermes/config.yaml:
#   mcp_servers:
#     aegis-memory:
#       command: /RUTA/AL/REPO/bridge/bin/mcp-memory.sh
#       args: []
#       enabled: true
# =============================================================================
set -euo pipefail

BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$BRIDGE_DIR/app"               # paquete `app` importable
export MEMORY_DIR="${MEMORY_DIR:-$BRIDGE_DIR/data/memory}"
export LOG_DIR="${LOG_DIR:-$BRIDGE_DIR/data/logs}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

cd "$BRIDGE_DIR"
exec .venv/bin/python -m app.mcp_memory