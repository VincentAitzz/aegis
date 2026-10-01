#!/usr/bin/env bash
# =============================================================================
# Aegis — arranque del gateway de Hermes.
#
# No necesita grupo `docker`: el backend de terminal es `local` (ejecuta en el
# host, protegido por la whitelist y los guardarraíles de `bridge/app/mcp_ops.py`).
# El sandbox por contenedor se retiró el 2026-09-30: arrancaba un contenedor por
# run al que el agente no tenía acceso, y su `/workspace` era un directorio vacío.
#
# OJO: el `pkill` tarda ~30 s en drenar. Si arrancas antes de que muera el
# anterior, el nuevo muere con "A gateway already owns this host".
# Comprueba antes con: pgrep -f '[h]ermes gateway' || bash infra/hermes/start-gateway.sh
#
# Uso:  bash infra/hermes/start-gateway.sh
# =============================================================================
set -euo pipefail

if pgrep -f '[h]ermes gateway' >/dev/null 2>&1; then
    echo "ya hay un gateway vivo: pgrep -f '[h]ermes gateway'   → no arranco otro."
    exit 0
fi

mkdir -p ~/.hermes/logs
setsid nohup "$HOME/.local/bin/hermes" gateway run \
    > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &
echo "gateway-pid=$!"
echo "lanzado; espera ~6s y comprueba: curl -s 127.0.0.1:8642/health"