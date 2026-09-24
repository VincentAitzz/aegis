#!/usr/bin/env bash
# =============================================================================
# Aegis — Arranque de la malla Tailscale (requiere root)
# Única vía de comunicación dispositivo → bridge. Sin IPs estáticas: MagicDNS.
#
# Uso:
#   sudo ./tailscale-up.sh            # primer arranque (interactivo: auth URL)
#   sudo ./tailscale-up.sh --authkey  # headless con auth key de la tailnet
#
# Requisitos: tailscale instalado (pacman -S tailscale; sudo systemctl enable --now tailscaled)
# =============================================================================
set -euo pipefail

HOSTNAME="${AEGIS_TS_HOSTNAME:-aegis}"   # nombre MagicDNS: aegis.<tailnet>.ts.net
TAG="${AEGIS_TS_TAG:-tag:server}"

# Se recomienda -snat-subnet-routes=false y hacer el up con --advertise-tags.
# El --hostname mantiene un nombre estable (resuelto vía MagicDNS) aunque
# la IP privada de LAN cambie.
AUTHKEY=""
if [[ "${1:-}" == "--authkey" && -n "${2:-}" ]]; then
  AUTHKEY="${2}"
fi

echo "↗  Uniendo Aegis a la tailnet como '${HOSTNAME}' (tag: ${TAG})..."
sudo tailscale up \
  --hostname="${HOSTNAME}" \
  --advertise-tags="${TAG}" \
  --accept-dns \
  --accept-routes \
  ${AUTHKEY:+--authkey="${AUTHKEY}"}

echo "✔  Estado de la malla:"
sudo tailscale status
echo
echo "✔  MagicDNS — hostname del bridge: ${HOSTNAME}.<tailnet>.ts.net"
echo "   La app móvil usa --dart-define=API_HOST=AEGIS_HOST podría resolverse"
echo "   con: tailscale whois <ip>  |  tailscale dns status"