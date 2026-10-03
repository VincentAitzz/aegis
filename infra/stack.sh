#!/usr/bin/env bash
# =============================================================================
# Aegis — encender, mirar y apagar el stack (Ollama + gateway + bridge).
#
#   bash infra/stack.sh arrancar            # los tres, en orden de dependencia
#   bash infra/stack.sh estado              # qué vive, con qué salud y con qué permiso
#   bash infra/stack.sh parar               # los tres, y verifica que mueren
#   bash infra/stack.sh parar gateway       # solo uno
#   bash infra/stack.sh reiniciar
#
# ## Por qué existe
#
# Encender eran tres comandos en tres sitios, con tres rutas de log distintas.
# Apagar era `pkill` a mano, y **falló de verdad**: `pkill -f 'ollama serve'` y
# `pkill -f 'hermes gateway run'` no mataron nada, y solo se notó al comprobar el
# puerto. Además quedaron hijos vivos (un `llama-server` de un modelo cargado
# sobrevivió al `ollama serve`). Un script cuyo "apagado" no comprueba que el
# proceso murió es un script que miente.
#
# ## Las tres reglas que lo sostienen
#
# 1. **Nada de `pkill`.** Los procesos se matan por PID, tomados del pidfile, y
#    al GRUPO de proceso (`kill -- -PID`), que es lo que se lleva por delante los
#    hijos. Un `pkill -f` depende de que el patrón siga casando con el comando.
# 2. **Nada de `sleep` a ciegas.** Cada arranque espera a su salud real: Ollama
#    a `/api/tags`, el gateway a `/health`, el bridge a `/health`. El gateway es
#    el lento: su drenaje tarda ~30 s y arrancar antes hace que el nuevo muera
#    con "A gateway already owns this host".
# 3. **Apagado que se autocomprueba.** Tras el `KILL`, el puerto tiene que estar
#    libre. Si no lo está, esto sale con error diciendo qué PID sobrevive, en vez
#    de darlo por bueno.
#
# Estado y logs en `~/.local/state/aegis/` y `~/.local/log/aegis/`, fuera del
# repo: encender Aegis no ensucia el árbol de trabajo.
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${AEGIS_STATE_DIR:-$HOME/.local/state/aegis}"
LOG_DIR="${AEGIS_LOG_DIR:-$HOME/.local/log/aegis}"
PUERTA_BRIDGE="${BRIDGE_PORT:-8000}"
PUERTA_GATEWAY=8642
PUERTA_OLLAMA=11434

mkdir -p "$STATE_DIR" "$LOG_DIR"

# --- las tres piezas: nombre · pidfile · patrón de proceso · salud -----------
SERVICIOS=(ollama gateway bridge)

pidfile() { echo "$STATE_DIR/$1.pid"; }
logfile() { echo "$LOG_DIR/$1.log"; }

patron() {
    case "$1" in
        ollama)  echo "ollama serve" ;;
        gateway) echo "hermes gateway run" ;;
        bridge)  echo "uvicorn app.main:app" ;;
    esac
}

# El grupo de proceso es el que se mata entero. Con `setsid`, el PID del líder es
# también el PGID, y así `kill -- -PID` no deja hijos de llama-server sueltos.
lanzar() {
    local svc="$1"; shift
    local log; log="$(logfile "$svc")"
    setsid nohup "$@" >"$log" 2>&1 < /dev/null &
    local pid=$!
    echo "$pid" > "$(pidfile "$svc")"
    echo "  $svc lanzado pid=$pid log=$log"
}

vivo() {
    local svc="$1" pf; pf="$(pidfile "$svc")"
    if [[ -s "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null; then
        return 0
    fi
    # Sin pidfile válido (arranque a mano, o reboot): se busca por patrón, que
    # es un respaldo, no la vía normal.
    pgrep -f "$(patron "$svc")" >/dev/null 2>&1
}

# Espera a la salud real. Imprime "ok" o "TIMEOUT", nunca "esperando".
esperar_salud() {
    local svc="$1" url="$2" segundos="${3:-60}" i=0
    while (( i < segundos )); do
        if curl -sf -m 2 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1; ((i++))
    done
    return 1
}

esperar_puerto_libre() {
    local puerto="$1" segundos="${2:-15}" i=0
    while (( i < segundos )); do
        if ! (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then
            return 0
        fi
        exec 3<&- 2>/dev/null || true
        sleep 1; ((i++))
    done
    return 1
}

arrancar_uno() {
    local svc="$1"
    if vivo "$svc"; then
        echo "  $svc ya estaba vivo (pid $(pgrep -f "$(patron "$svc")" | head -1))"
        return 0
    fi
    rm -f "$(pidfile "$svc")"
    case "$svc" in
        ollama)
            lanzar "$svc" bash "$RAIZ/infra/ollama/start-ollama.sh"
            if esperar_salud "$svc" "http://127.0.0.1:$PUERTA_OLLAMA/api/tags" 60; then
                echo "  ollama ok en :$PUERTA_OLLAMA"
            else
                echo "  ✗ ollama no respondió en 60 s. Log: $(logfile "$svc")" >&2
                return 1
            fi
            ;;
        gateway)
            bash "$RAIZ/infra/hermes/start-gateway.sh" >/dev/null
            # El script escribe el PID del hijo de setsid; se toma el proceso vivo.
            pgrep -f "$(patron "$svc")" | head -1 > "$(pidfile "$svc")" || true
            if esperar_salud "$svc" "http://127.0.0.1:$PUERTA_GATEWAY/health" 90; then
                echo "  gateway ok en :$PUERTA_GATEWAY"
            else
                echo "  ✗ gateway no respondió en 90 s (¿otro gateway sin drenar?)." \
                     "Log: $(logfile "$svc")" >&2
                return 1
            fi
            ;;
        bridge)
            # Sin --reload: en operación el vigilante recarga a mitad de run.
            lanzar "$svc" env BRIDGE_RELOAD=0 bash "$RAIZ/bridge/run.sh"
            if esperar_salud "$svc" "http://127.0.0.1:$PUERTA_BRIDGE/health" 90; then
                echo "  bridge ok en :$PUERTA_BRIDGE"
            else
                echo "  ✗ bridge no respondió en 90 s. Log: $(logfile "$svc")" >&2
                return 1
            fi
            ;;
    esac
}

arrancar() {
    echo "== Aegis arrancando =="
    local svc
    for svc in "${SERVICIOS[@]}"; do
        arrancar_uno "$svc"
    done
    echo
    estado
}

parar_uno() {
    local svc="$1" pf; pf="$(pidfile "$svc")"
    local pids=()
    if [[ -s "$pf" ]]; then
        pids+=("$(cat "$pf")")
    fi
    # Respaldo: lo que quede del patrón, por si el pidfile se perdió.
    while read -r p; do
        [[ -n "$p" ]] && pids+=("$p")
    done < <(pgrep -f "$(patron "$svc")" 2>/dev/null || true)

    if (( ${#pids[@]} == 0 )); then
        echo "  $svc no estaba vivo"
        rm -f "$pf"
        return 0
    fi

    # Cinturón antes de matar: el grupo de proceso de quien llama nunca se toca.
    # Un `kill -- -$p` sin esta comprobación, con un pidfile equivocado, se lleva
    # por delante la terminal que está ejecutando este script — y con ella, el
    # script, a mitad del apagado y sin decir nada.
    local yo_pgid
    yo_pgid="$(ps -o pgid= -p $$ | tr -d ' ')"
    local p pgid
    for p in "${pids[@]}"; do
        [[ "$p" == "$$" ]] && continue
        pgid="$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ' || true)"
        [[ "$pgid" == "$yo_pgid" ]] && continue      # es de los nuestros
        if [[ -n "$pgid" && "$pgid" == "$p" ]]; then
            kill -- "-$p" 2>/dev/null || true       # líder: al grupo entero
        else
            kill "$p" 2>/dev/null || true            # no lo es: solo al proceso
        fi
    done

    # Margen para el drenaje (el gateway tarda ~30 s), y luego KILL.
    sleep 3
    for p in "${pids[@]}"; do
        kill -0 "$p" 2>/dev/null || continue
        [[ "$p" == "$$" ]] && continue
        pgid="$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ' || true)"
        [[ "$pgid" == "$yo_pgid" ]] && continue
        if [[ -n "$pgid" && "$pgid" == "$p" ]]; then
            kill -9 -- "-$p" 2>/dev/null || true
        else
            kill -9 "$p" 2>/dev/null || true
        fi
    done
    sleep 1

    local quedan
    quedan="$(pgrep -f "$(patron "$svc")" 2>/dev/null | tr '\n' ' ' || true)"
    if [[ -n "$quedan" ]]; then
        echo "  ✗ $svc NO murió. Sobreviven: $quedan" >&2
        rm -f "$pf"
        return 1
    fi
    rm -f "$pf"
    echo "  $svc parado"
}

parar() {
    local solo="${1:-}"
    echo "== Aegis parando =="
    local svc rc=0
    if [[ -n "$solo" ]]; then
        parar_uno "$solo" || rc=1
    else
        # Al revés del arranque: primero el bridge, que cuelga de los otros dos.
        for svc in bridge gateway ollama; do
            parar_uno "$svc" || rc=1
        done
    fi
    # El puente es el único con puerto que este script abre; los otros dos se
    # comprueban por salud. Se verifica el suyo porque es el que se usa.
    if [[ -z "$solo" || "$solo" == "bridge" ]]; then
        if esperar_puerto_libre "$PUERTA_BRIDGE" 10; then
            echo "  :$PUERTA_BRIDGE libre"
        else
            echo "  ✗ :$PUERTA_BRIDGE sigue ocupado" >&2
            rc=1
        fi
    fi
    return $rc
}

estado() {
    echo "== Aegis =="

    local svc pid salud extra
    for svc in "${SERVICIOS[@]}"; do
        pid=""
        [[ -s "$(pidfile "$svc")" ]] && pid="$(cat "$(pidfile "$svc")")"
        if ! vivo "$svc"; then
            printf '  %-8s :%-6s apagado\n' "$svc" "$(puerto_de "$svc")"
            continue
        fi
        [[ -z "$pid" ]] && pid="$(pgrep -f "$(patron "$svc")" | head -1)"
        case "$svc" in
            ollama)
                salud=$(curl -sf -m 2 "http://127.0.0.1:$PUERTA_OLLAMA/api/tags" 2>/dev/null \
                    | grep -o '"name"' | wc -l || echo 0)
                extra="$((salud)) modelos"
                ;;
            gateway)
                extra=$(curl -sf -m 2 "http://127.0.0.1:$PUERTA_GATEWAY/health" 2>/dev/null \
                    | python3 -c 'import json,sys; print("hermes " + json.load(sys.stdin)["version"])' \
                    2>/dev/null || echo "sin salud")
                ;;
            bridge)
                extra=$(curl -sf -m 2 "http://127.0.0.1:$PUERTA_BRIDGE/health" 2>/dev/null \
                    | python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin)["agents"]))' \
                    2>/dev/null || echo "sin salud")
                ;;
        esac
        printf '  %-8s :%-6s ok   pid %-7s %s\n' "$svc" "$(puerto_de "$svc")" "${pid:-?}" "$extra"
    done

    # La línea que vale: no solo que el bridge vive, sino si Aegis puede escribir.
    if vivo bridge; then
        local token
        token="$(grep -E '^AEGIS_API_KEY=' "$RAIZ/bridge/.env" 2>/dev/null | cut -d= -f2- || true)"
        curl -sf -m 3 -H "X-Aegis-Token: ${token}" \
            "http://127.0.0.1:$PUERTA_BRIDGE/autonomy" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
modo = d.get("modo", "?")
escritura = ", ".join(d.get("escritura", {}).keys()) or "ninguno"
pend = len(d.get("pendientes", []))
cola = f" · {pend} esperando OK" if pend else ""
print(f"  autonomy: {modo} · escribiendo: {escritura}{cola}")
' || true
    fi
}

puerto_de() {
    case "$1" in
        ollama)  echo "$PUERTA_OLLAMA" ;;
        gateway) echo "$PUERTA_GATEWAY" ;;
        bridge)  echo "$PUERTA_BRIDGE" ;;
    esac
}

reiniciar() { parar || true; echo; arrancar; }

case "${1:-estado}" in
    arrancar|start|up)   arrancar ;;
    parar|stop|down)      parar "${2:-}" ;;
    estado|status)        estado ;;
    reiniciar|restart)    reiniciar ;;
    *)
        sed -n '3,10p' "$0"
        exit 2
        ;;
esac