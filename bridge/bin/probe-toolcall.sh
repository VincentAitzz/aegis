#!/usr/bin/env bash
# =============================================================================
# probe-toolcall.sh — comprueba si un modelo servido por Ollama devuelve
# tool_calls ESTRUCTURADOS (no texto) vía el endpoint OpenAI-compatible.
#
# Uso:  bash bridge/bin/probe-toolcall.sh [modelo] [base_url]
#   modelo   (def: qwen2.5:7b)
#   base_url (def: http://127.0.0.1:11434)
#
# Exit: 0 = tool_calls reales (stream y/o no-stream); 1 = solo texto fantasma.
# =============================================================================
set -u

MODEL="${1:-qwen2.5:7b}"
BASE="${2:-http://127.0.0.1:11434}"
V1="$BASE/v1/chat/completions"

TOOLS='[{"type":"function","function":{"name":"build_apk","description":"Compila el APK de Aegis Console","parameters":{"type":"object","properties":{"api_host":{"type":"string"}},"required":[]}}}]'
MSG='[{"role":"user","content":"Usa la tool build_apk(api_host==\"100.101.102.100\") y cuando termine responde SOLO con la palabra OK."}]'

echo "== probe model=$MODEL via $V1 =="

# --- no-stream (opcional: algunos modelos[qwen3] cuelgan en no-stream) ---
NS=$(curl -s -m "${NS_TIMEOUT:-25}" "$V1" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"stream\":false,\"messages\":$MSG,\"tools\":$TOOLS}" 2>/dev/null)

NS_TC=$(printf '%s' "$NS" | python3 -c 'import json,sys
try:
  d=json.load(sys.stdin); m=d["choices"][0]["message"]
  tc=m.get("tool_calls"); print(len(tc) if tc else "0")
except Exception: print("ERR")')

NS_FIN=$(printf '%s' "$NS" | python3 -c 'import json,sys
try:
  d=json.load(sys.stdin); print(d["choices"][0].get("finish_reason"))
except Exception: print("ERR")')

# --- stream ---
ST=$(curl -s -m 120 -N "$V1" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"stream\":true,\"messages\":$MSG,\"tools\":$TOOLS}" 2>/dev/null)

ST_TC=$(printf '%s' "$ST" | python3 -c 'import sys,json
n=0
for line in sys.stdin:
  line=line.strip()
  if not line.startswith("data:"): continue
  p=line[5:].strip()
  if p=="[DONE]": continue
  try:
    d=json.loads(p); delta=d["choices"][0].get("delta",{})
    if delta.get("tool_calls"): n+=1
  except Exception: pass
print(n)')

echo "no-stream: tool_calls=$NS_TC finish_reason=$NS_FIN"
echo "stream   : deltas con tool_calls=$ST_TC"

if [ "$NS_TC" != "0" ] && [ "$NS_TC" != "ERR" ]; then
  echo ">>> OK: el modelo emite tool_calls reales (no-stream)."
  exit 0
elif [ "$ST_TC" != "0" ] && [ "$ST_TC" != "ERR" ]; then
  echo ">>> OK: el modelo emite tool_calls reales (stream)."
  exit 0
elif [ "$NS_TC" = "ERR" ]; then
  echo ">>> ERROR: respuesta no parseable (¿modelo existe?)."
  exit 2
else
  echo ">>> MAL: el modelo NO emite tool_calls; emite texto plano."
  exit 1
fi