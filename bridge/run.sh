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

# .env propio (sólo si falta): se copia el ejemplo y se rellenan los secretos.
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "⚠️  Creé .env desde .env.example."
  # La clave de la API de operación se genera aquí y **no se imprime**.
  #
  # ## Por qué esto importa más desde que hay servicio
  # `AEGIS_API_KEY=` vacía significa **sin autenticación**: cualquiera que llegue
  # al puerto 8000 puede concederle a Aegis permiso de escritura sobre tus
  # proyectos. Antes esto se activaba a mano y se veía; desde que existe
  # `aegis-bridge.service` arranca **solo**, después de un reinicio, sin que
  # nadie mire. Si el `.env` se creara aquí con la clave vacía, el bridge
  # quedaría abierto en la red sin que nadie se enterase hasta que sea tarde.
  #
  # Es el mismo motivo por el que `infra/setup.sh` la genera: una clave escrita a
  # mano acaba en un repositorio, en un screenshot o en un log de CI. Generada
  # aquí, escrita una vez y nunca mostrada.
  if grep -q '^AEGIS_API_KEY=$' .env; then
    clave="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sed -i "s|^AEGIS_API_KEY=$|AEGIS_API_KEY=$clave|" .env
    chmod 600 .env
    echo "   Generé una AEGIS_API_KEY nueva (no se imprime)."
  fi
  echo "   Edita HERMES_API_KEY si vas a usar la gateway (ver ~/.hermes/.env)."
fi

# El --reload es de desarrollo y **solo si se pide**: el valor por defecto es 0.
#
# Antes era 1, que significaba que seguir la instrucción de `AGENTS.md` §5
# —«cd bridge && bash run.sh»— arrancaba el bridge con el vigilante puesto. Ese
# vigilante recarga el proceso a mitad de un run: el run muere sin dejar JSONL, sin
# episodio en memoria y sin `fin`, que es exactamente la clase de pérdida que este
# repo no admite. Para desarrollo: `BRIDGE_RELOAD=1 bash run.sh`.
RELOAD=()
[[ "${BRIDGE_RELOAD:-0}" == "1" ]] && RELOAD=(--reload)

# El bridge es **single-process a propósito**, y no por descuido: el estado de
# control de un run en marcha (parar, dirigir) vive en un dict de memoria
# (`_AUTOPILOT_RUNS` en `main.py`), y las aprobaciones en SQLite. Con más de un
# worker, un `POST /autopilot/{id}/stop` que llegara al proceso B daría un 404
# con un mensaje que **mentiría** («se cayó del buffer») cuando el run está
# vivo y sano en el proceso A.
#
# Es peor que no escalara: escalaría *pareciendo* que escala. Así que se impide,
# aquí y no en el código Python, que es donde se nota al arrancar.
WORKERS="${BRIDGE_WORKERS:-1}"
if [[ "$WORKERS" != "1" ]]; then
  echo "✗ BRIDGE_WORKERS=$WORKERS no está soportado." >&2
  echo "  El estado de control de los runs vive en memoria del proceso: con dos" >&2
  echo "  workers, parar un run desde el otro proceso da un 404 que miente." >&2
  echo "  Para más de uno hay que persistir el estado de los runs primero." >&2
  exit 1
fi

PYTHONPATH=app .venv/bin/uvicorn app.main:app \
    --host "${BRIDGE_BIND:-0.0.0.0}" --port "${BRIDGE_PORT:-8000}" \
    --workers "$WORKERS" "${RELOAD[@]}"
