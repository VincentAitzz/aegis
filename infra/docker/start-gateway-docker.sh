#!/usr/bin/env bash
# =============================================================================
# Aegis — arranca el gateway de Hermes con el grupo `docker` activo.
#
# El gateway debe heredar el grupo docker (Gid 956) para que el backend de
# terminal del sandbox (docker) pueda hablar con /var/run/docker.sock. Si la
# sesión actual es anterior al `usermod -aG docker`, su shell no tiene el
# grupo y `docker ps` falla con permission denied; `newgrp docker` lo activa.
#
# Uso:  newgrp docker -c 'bash infra/docker/start-gateway-docker.sh'
# =============================================================================
set -euo pipefail

pkill -f '[h]ermes gateway' 2>/dev/null || true
sleep 1
mkdir -p ~/.hermes/logs
setsid nohup "$HOME/.local/bin/hermes" gateway run \
    > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &
echo "gateway-pid=$!"
echo "lanzado; espera ~6s y comprueba: curl -s 127.0.0.1:8642/health"