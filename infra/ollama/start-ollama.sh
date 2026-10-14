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

# Contexto: 64.000 → 32.768.
#
# Los 64k eran un requisito de Hermes (`MINIMUM_CONTEXT_LENGTH`). **Hermes ya no
# es motor**: desde la Fase 1 solo queda como sonda de salud, y
# `docs/decisiones/002` explica por qué se quedó en un motor. El requisito se
# quedó sin dueño y se siguió pagando.
#
# Lo que hace falta de verdad, medido sobre el prompt que el bridge construye:
#
#     system prompt real   5.606 chars ≈  1.602 tokens
#     + peor caso (16 pasos × 3.000 chars) ≈ 15.321 tokens
#
# 32.768 deja **2,1× de margen** sobre ese peor caso, y 16.384 lo haríaPHONE
# quedar al 1,07× — un solo paso más largo y el run se trunca.
#
# Por qué se paga: el KV cache de un 7B a 64k en f16 son **≈3,6 GB de RAM**, y
# a 32k se queda en **≈1,8 GB**. Son ~1,8 GB que deja de competir con el editor.
# No es gratis de una vez: si un día un run necesita más, esto sube a 16k y se
# acepta el coste.
export OLLAMA_CONTEXT_LENGTH=32768

# El modelo se queda resident entre turnos. Con un solo modelo (ver
# `bridge/app/config.py`, `modelo_t1()`) ya no hay intercambio, así que esto
# solo tiene que aguantar entre peticiones, no entre clases de latencia.
export OLLAMA_KEEP_ALIVE=60m

# Una petición a la vez. El bucle de tools es secuencial por naturaleza, y en
# paralelo cada contexto reproduce su KV cache: con dos en vuelo, el doble de
# RAM para un trabajo que aquí corre de uno en uno.
export OLLAMA_NUM_PARALLEL=1

# Dos modelos resident, y solo dos: **el agente y el de embeddings**.
#
# Es un tope, no una suggestion. `nomic-embed-text` tiene que poder convivir
# con el 7B porque el recall lo llama entre pasos; con tope 1, cada búsqueda en
# memoria expulsaría al modelo del trabajo. Con tope 2 los dos caben y un
# tercero **no puede entrar**: que es justo el modo de fallo que motivó
# quedarse con un solo modelo de agente (`llama3.2:3b` ya no se carga).
export OLLAMA_MAX_LOADED_MODELS=2

# Flash attention: menos memoria de KV y más rápida. Sin contrapartida de
# calidad que se pueda medir, a diferencia de `OLLAMA_KV_CACHE_TYPE=q8_0`, que
# reduciría el KV a la mitad pero degrada la calidad un poco y en silencio.
# Ese es el siguiente peldaño **si** la RAM sigue justa, y por eso está
# commented: una palanca que solo se tira a propósito, no por defecto.
export OLLAMA_FLASH_ATTENTION=1

# export OLLAMA_KV_CACHE_TYPE=q8_0    # media RAM de KV, algo de calidad

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