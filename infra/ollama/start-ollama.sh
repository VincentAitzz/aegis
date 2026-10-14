#!/usr/bin/env bash
# =============================================================================
# Aegis — Arranque de Ollama (solo loopback; nunca se expone a la malla)
# Modelo recomendado por hardware: qwen2.5-coder:7b (Q4_K_M) @ 64k ctx.
#
#   Nota hardware: Hermes exige contexto >=64k (MINIMUM_CONTEXT_LENGTH).
#   A 64k el KV del 7b cabe en RAM (≈3,6 GB) con los pesos en VRAM (4,7 GB).
#   El 14b NO es viable en esta máquina (9 GB pesos + ~12 GB KV en 64k).
# =============================================================================
set -euo pipefail

export OLLAMA_HOST=127.0.0.1          # solo loopback — seguridad
export OLLAMA_CONTEXT_LENGTH=64000     # requisito mínimo del agente Hermes
export OLLAMA_KEEP_ALIVE=30m           # modelo residente (evita recargas en swap)

# Se busca, no se supone. Antes era la ruta absoluta de una máquina concreta
# (`~/.local/bin/ollama`), que en el `PATH` de quien clone esto no existe: el
# script fallaba con «No such file or directory» sin decir qué faltaba.
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || true)}"
if [[ -z "$OLLAMA_BIN" ]]; then
  for candidato in "$HOME/.local/bin/ollama" "$HOME/.ollama/bin/ollama" \
                   /usr/local/bin/ollama /usr/bin/ollama; do
    [[ -x "$candidato" ]] && OLLAMA_BIN="$candidato" && break
  done
fi
if [[ -z "$OLLAMA_BIN" ]]; then
  echo "No encuentro ollama. Instálalo (https://ollama.com/install.sh) o pon" >&2
  echo "OLLAMA_BIN=<ruta>/ollama en el entorno." >&2
  exit 1
fi

exec "$OLLAMA_BIN" serve