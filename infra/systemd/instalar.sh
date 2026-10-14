# Aegis — instalación como servicio de usuario (systemd --user)
#
# ## Por qué unidades de **usuario** y no de sistema
# Porque Aegis no es punto único de falla. Si el negocio depende de que un
# servicio de sistema esté vivo, apagaste la máquina de día y le cortaste el negocio, y
# eso es peor que no tenerlo. Como servicio de usuario:
#
# - arranca cuando el usuario entra, no cuando arranca el sistema;
# - **morre con la sesión**, así que cerrar la sesión es apagarlo limpio;
# - no pide sudo, no toca nada privilegiado y no sobrevive a un `logout` —que es
#   exactamente lo que se quiere de algo que ejecuta herramientas sobre tus
#   proyectos.
#
# ## Qué se instala
#   ollama   el modelo
#   gateway  el health check de la plataforma de Hermes
#   bridge   la API
#
# ## Por qué `stack.sh` sigue existiendo
# Porque las unidades no son universales: no hay `systemd --user` en macOS ni en
# un contenedor, y `infra/stack.sh` funciona en todas partes. Estas unidades son
# la forma **de que no haya que acordarse**, no la única forma de encender.
#
#   bash infra/systemd/instalar.sh     # instala y activa
#   bash infra/systemd/instalar.sh --no   # solo deja los ficheros

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESTINO="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NO_INSTALAR=0
[[ "${1:-}" == "--no" ]] && NO_INSTALAR=1

if ! command -v systemctl >/dev/null 2>&1; then
  echo "No hay systemctl en este sistema. Usa 'bash infra/stack.sh arrancar'." >&2
  exit 1
fi
if ! systemctl --user is-system-running >/dev/null 2>&1 \
   && ! systemctl --user show-environment >/dev/null 2>&1; then
  cat >&2 <<'AVISO'
No parece que systemd de usuario esté disponible. En la mayoría de distribuciones
basta con dejar el gestor de sesión explicando las unidades: eso crea
~/.config/systemd/user y arranca el servicio con la sesión.

    loginctl enable-linger "$USER"     # opcional: sobrevive sin sesión abierta

AVISO
  exit 1
fi

mkdir -p "$DESTINO"

# Se generan con la raíz real: una unit con `WorkingDirectory=/ruta/que/no/existe`
# arranca «bien» y falla en el primer log, y systemd lo reintenta tres veces.
generar() {
  local nombre="$1" descripcion="$2" exec="$3" despues="$4" reinicio="$5" extra="${6:-}"
  cat > "$DESTINO/aegis-$nombre.service" <<UNIT
[Unit]
Description=$descripcion
Documentation=https://github.com/VincentAitzz/aegis
$despues

[Service]
Type=simple
WorkingDirectory=$RAIZ/bridge
ExecStart=$exec
Restart=$reinicio
RestartSec=3
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$RAIZ/bridge/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=aegis-$nombre
$extra

[Install]
WantedBy=default.target
UNIT
}

# `After=` con `default.target` y no con la otra unidad: Ollama no depende de que
# el bridge esté arriba —el bridge arranca igual y espera a que el modelo
# responda—, y al revés tampoco. Encadenarlos convierte un fallo de arranque de
# uno en un fallo de arranque del otro.
# **Todo se invoca con `/bin/bash`**, no ejecutando el fichero.
#
# Medido el 2026-10-14 al instalar esto por primera vez: con `ExecStart` apuntando
# al script, systemd devolvió `203/EXEC — Permission denied` y lo reintentó en
# bucle. La causa: el bit de ejecución no viaja en git. En un clon recién hecho el
# fichero es `-rw-r--r--` y `infra/stack.sh` nunca se rompió porque lo invoca
# con `bash`. Aquí, invocar el binario directamente depende de un bit que git no
# garantiza —y que además se pierde al pasar por un zip o una copia entre máquinas
# con el filesystem de Windows—.
#
# Es el mismo motivo por el que no se da por hecho que `hermes` esté en una ruta:
# se busca, como en el resto del repo (`app/entorno.py`).

HERMES_BIN="$(command -v hermes || true)"
for cand in "$HOME/.local/bin/hermes" "$HOME/.hermes/bin/hermes"; do
  [[ -z "$HERMES_BIN" && -x "$cand" ]] && HERMES_BIN="$cand"
done

generar ollama "Aegis — Ollama (modelo local)" \
  "/bin/bash $RAIZ/infra/ollama/start-ollama.sh" "After=default.target" "on-failure"

# El gateway **no** se lanza con `hermes gateway run` directo en la unit.
#
# Medido: haciéndolo así, el proceso ve que su entrada no es una terminal
# (`Warning: Input is not a terminal (fd=0)`), imprime su banner y se despide
# con «Goodbye!». Es un CLI que se lee por la unit como un `simple` que expects
# hablar por stdin.
#
# Se arranca con `infra/hermes/start-gateway.sh`, que es lo mismo que usa
# `stack.sh`: lo suelta desacoplado con `setsid nohup`. Por eso la unit es
# `oneshot` y no `simple`: **la unit no es el proceso**, es quien lo lanza. Con
# `simple` habría dos procesos y systemd mataría el suyo al parar la unit,
# dejando el de verdad vivo y sin dueño — que es exactamente el modo de fallo que
# el README de `infra/stack.sh` ya documenta.
cat > "$DESTINO/aegis-gateway.service" <<UNIT
[Unit]
Description=Aegis — gateway de Hermes (health check)
Documentation=https://github.com/VincentAitzz/aegis
After=default.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash $RAIZ/infra/hermes/start-gateway.sh
ExecStop=/bin/bash -c "pkill -f '[h]ermes gateway' || true"
TimeoutStartSec=90
StandardOutput=journal
StandardError=journal
SyslogIdentifier=aegis-gateway

[Install]
WantedBy=default.target
UNIT

generar bridge "Aegis — bridge (API FastAPI)" \
  "bash $RAIZ/bridge/run.sh" "After=default.target" "always" \
  "WatchdogSec=0"

# El watchdog. `stack.sh estado` no miente: si algo está caído, sale con error.
# Aquí solo hay que avisar.
cat > "$DESTINO/aegis-vigila.service" <<UNIT
[Unit]
Description=Aegis — vigilancia
Documentation=https://github.com/VincentAitzz/aegis

[Service]
Type=oneshot
ExecStart=/bin/bash $RAIZ/infra/stack.sh estado
UNIT

cat > "$DESTINO/aegis-vigila.timer" <<'UNIT'
[Unit]
Description=Aegis — comprueba la pila cada 30 s
Documentation=https://github.com/VincentAitzz/aegis

[Timer]
OnBootSec=45s
OnUnitActiveSec=30s
AccuracySec=5s
Unit=aegis-vigila.service

[Install]
WantedBy=timers.target
UNIT

if [[ "${1:-}" == "--desinstalar" ]]; then
  systemctl --user disable --now aegis-bridge aegis-gateway aegis-ollama 2>/dev/null || true
  systemctl --user disable --now aegis-vigila.timer 2>/dev/null || true
  rm -f "$DESTINO"/aegis-*.service "$DESTINO"/aegis-*.timer
  systemctl --user daemon-reload
  echo "Unidades quitadas. Los PID que dejara stack.sh siguen vivos:"
  echo "  bash infra/stack.sh parar"
  exit 0
fi

if [[ $NO_INSTALAR -eq 1 ]]; then
  echo "Ficheros escritos en $DESTINO. No se ha activado nada."
  exit 0
fi

systemctl --user daemon-reload
for u in ollama gateway bridge; do
  systemctl --user enable --now "aegis-$u.service"
  printf '  %s  %s\n' "$(systemctl --user is-active "aegis-$u.service")" "aegis-$u"
done
# El timer se **reinicia**, no solo se activa.
#
# Medido al instalar por segunda vez: `enable --now` lo dejaba `enabled` pero
# `inactive`, sin programming ninguna, y `list-timers` no lo enseñaba. La causa es
# que el `daemon-reload` de arriba invalida el timer que estaba corriendo con el
# fichero viejo, y `--now` no lo vuelve a programar. Un `restart` sí.
systemctl --user enable aegis-vigila.timer
systemctl --user restart aegis-vigila.timer

echo
echo "Estado:"
systemctl --user --no-pager --lines=0 status aegis-ollama aegis-gateway aegis-bridge 2>/dev/null \
  | grep -E '^●' || bash "$RAIZ/infra/stack.sh" estado

cat <<'NOTA'

Para parar todo:
    systemctl --user stop aegis-bridge aegis-gateway aegis-ollama
    systemctl --user disable aegis-vigila.timer

Para quitarlo del todo:
    bash infra/systemd/instalar.sh --desinstalar

Los logs:
    journalctl --user -u aegis-bridge -f
NOTA
