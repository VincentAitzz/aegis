#!/usr/bin/env bash
# =============================================================================
# Bridge Aegis — arranque de desarrollo
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "→ creando venv e instalando dependencias…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

# .env propio (sólo si falta): se copia el ejemplo y se pide la clave real
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "⚠️  Creé .env desde .env.example — edita HERMES_API_KEY (ver ~/.hermes/.env)."
fi

PYTHONPATH=app .venv/bin/uvicorn app.main:app --host "${BRIDGE_BIND:-0.0.0.0}" --port "${BRIDGE_PORT:-8000}" --reload