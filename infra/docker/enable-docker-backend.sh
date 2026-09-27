#!/usr/bin/env bash
# =============================================================================
# Aegis — actívación del aislamiento por contenedor (capa 1)
#
# Cambia el backend del terminal de Hermes de "local" (ejecución directa en el
# host) a "docker" (cada comando dentro de un contenedor aegis-sandbox).
#
# PRE-REQUISITOS (instalación manual — a tu cargo):
#   sudo pacman -S docker
#   sudo systemctl enable --now docker
#   sudo usermod -aG docker "$USER"   → cerrar y abrir sesión (o 'newgrp docker')
#
# Uso:  ./infra/docker/enable-docker-backend.sh
#   - Construye la imagen aegis-sandbox → docker build -t aegis-sandbox .
#   - Aplica la config con 'hermes config set' (no toca el YAML a mano).
#   - Te recuerda reiniciar el gateway de Hermes (el backend de terminal se lee
#     al arrancar el agente).
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="aegis-sandbox:latest"

echo "▸ 1. Comprobando Docker…"
if ! command -v docker >/dev/null 2>&1; then
  echo "✗ docker no está instalado. Instálalo primero:"
  echo "    sudo pacman -S docker"
  echo "    sudo systemctl enable --now docker"
  echo "    sudo usermod -aG docker \"\$USER\"   # luego reinicia sesión"
  exit 1
fi

echo "▸ 2. Construyendo imagen $IMAGE…"
docker build -t "$IMAGE" "$REPO_ROOT/infra/docker"

echo "▸ 3. Aplicando configuración de Hermes (terminal → docker)…"
hermes config set terminal.backend docker
hermes config set terminal.cwd "/workspace"
hermes config set terminal.docker_image "$IMAGE"
hermes config set terminal.docker_mount_cwd_to_workspace true
hermes config set terminal.docker_run_as_host_user true
# Límites pensados para un host de ~15 GB RAM + Ollama a 64k de contexto:
# 4 GB por contenedor, 2 CPU, hasta 24 GB de disco.
hermes config set terminal.container_cpu 2
hermes config set terminal.container_memory 4096
hermes config set terminal.container_disk 24576
hermes config set terminal.container_persistent true

echo
echo "✓ Config aplicada. CÓMANDOS NUEVOS:"
hermes config get terminal.backend
hermes config get terminal.docker_image

echo
echo "⚠️  Reinicia el gateway para que el agente cargue el nuevo backend:"
echo "    pkill -f '[h]ermes gateway'"
echo "    setsid nohup '$HOME/.local/bin/hermes' gateway run > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &"
echo "    hermes gateway status   # o 'curl -s 127.0.0.1:8642/health'"
echo
echo "Verificación con una tarea que ejecute un comando:"
echo "  docker ps — verás un contenedor 'aegis-sandbox' (o el prefijo del job) mientras corre."
echo "Para revertir: hermes config set terminal.backend local"