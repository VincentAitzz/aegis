#!/usr/bin/env bash
# =============================================================================
# Aegis — lanzador del servidor MCP "aegis-ops" (build + adb del host).
#
# Hermes spawna los MCP stdio con su propio CWD/env; aquí fijamos el entorno
# para que se resuelva el paquete `app` y el toolchain del host.
# Registro en ~/.hermes/config.yaml:
#   mcp_servers:
#     aegis-ops:
#       command: /RUTA/AL/REPO/bridge/bin/mcp-ops.sh
#       args: []
#       enabled: true
# =============================================================================
set -euo pipefail

BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$BRIDGE_DIR/app"

cd "$BRIDGE_DIR"
exec .venv/bin/python -m app.mcp_ops