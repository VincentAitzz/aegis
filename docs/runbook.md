# Runbook

Guía de operación del backend Aegis (post-reinicio), pruebas y resolución de
problemas. Máquina: CachyOS (Arch), usuario `demo`, sin sudo automático.

## 1. Arranque tras un reinicio

Ollama y el gateway de Hermes **no** son servicios de sistema; hay que levantarlos
a mano en este orden (Tailscale sí usa `systemd` y arranca solo).

```bash
# 1) Ollama con contexto 64k (imprescindible para Hermes)
env OLLAMA_HOST=127.0.0.1 OLLAMA_CONTEXT_LENGTH=64000 ~/.local/bin/ollama serve \
  > ~/.local/ollama.log 2>&1 &
# alternativa: ./infra/ollama/start-ollama.sh

# 2) Gateway/API server de Hermes
setsid nohup ~/.local/bin/hermes gateway run > ~/.hermes/logs/gateway.log 2>&1 < /dev/null &

# 3) Bridge Aegis
cd /RUTA/AL/REPO/bridge
( env BRIDGE_BIND=0.0.0.0 BRIDGE_PORT=8000 PYTHONPATH=app \
    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > ~/.local/bridge.log 2>&1 & )

# 4) Devolución de bueno
curl -s http://127.0.0.1:8000/health   # espera status ok + agents [worker, orchestrator]
```

Logs:

| Servicio | Log                                   |
|----------|---------------------------------------|
| Ollama   | `~/.local/ollama.log`                 |
| Hermes   | `~/.hermes/logs/gateway.log`          |
| Bridge   | `~/.local/bridge.log`                 |

## 2. Credenciales y secretos

| Variable         | Dónde vive                     | Uso                                      |
|------------------|--------------------------------|------------------------------------------|
| `API_SERVER_KEY` | `~/.hermes/.env`               | autenticación del API server de Hermes   |
| `HERMES_API_KEY` | `bridge/.env` (gitignored)     | el bridge se autentica ante Hermes       |

- **Nunca** se versionan `.env*` (salvo `.env.example`). `bridge/.env` está en
  `.gitignore`; verifica con `git status --ignored | grep .env` antes de commitear.
- Regeneración: `openssl rand -hex 32` → actualiza ambos `.env` y reinicia
  gateway + bridge.

## 3. Malla (Tailscale)

Diagnóstico:

```bash
tailscale status            # nodos online; espera aegis + galaxy-a17
tailscale ip -4             # 100.101.102.100
tailscale set --operator=$USER   # (una vez) para `tailscale up` sin sudo
```

Verificación con el bridge por la malla:

```bash
curl http://aegis.tailXXXXXX.ts.net:8000/health      # MagicDNS
curl http://100.101.102.100:8000/health                 # IP de malla
```

En el **acceso log del bridge** la prueba real se distingue porque el request llega
con la IP Tailscale del otro nodo (p. ej. `100.101.102.103`), no `127.0.0.1`.

ACL (endurecimiento opcional): aplicar `infra/tailnet/acl-policy.json` en
https://login.tailscale.com/admin/acls . Limita nodos Android → `aegis:8000`.
> Si el tailnet tiene MagicDNS roto por wiring de resolver local, la app aún
> conecta por IP `100.x`; `aegis.tailXXXXXX.ts.net` es el camino preferido.

## 4. App en el teléfono

Depuración inalámbrica (puertos giran):

```bash
adb mdns services                       # puerto actual mDNS
adb connect 192.168.0.5:<puerto>        # o directamente del número de pantalla
adb -s <serial> shell am start -n com.aegis.aegis_console/.MainActivity
```

- **Sin malla aún**: `adb reverse tcp:8000 tcp:8000 tcp:11434 tcp:11434` y usar
  `API_HOST=localhost` → `./infra/mobile/install-phone.sh`.
- **Con malla**: recompilar con `--dart-define=API_HOST=aegis.<tailnet>.ts.net` y
  reinstalar. La app muestra el host en la página Conectividad.
- Si ADB cae tras un reinicio: re-activar "Depuración inalámbrica" en el teléfono
  (Ajustes → Opciones de desarrollador) y re-conectar con el puerto nuevo.

## 5. Pruebas

Funcionales (host):

```bash
# E2E REST+WS (subscribe tardío → replay completo, verifica buffer)
cd bridge && .venv/bin/python tests/e2e_ws.py

# Contrato de control
curl -X POST http://127.0.0.1:8000/tasks -d '{"agent":"worker","prompt":"hola"}'
curl -X POST http://127.0.0.1:8000/tasks/$RUN/steer -d '{"text":"cancela"}'
curl -X POST http://127.0.0.1:8000/tasks/$RUN/stop
```

App:

```bash
cd mobile
flutter analyze && flutter test       # espera 0 issues / verde
flutter build apk --debug --dart-define=API_HOST=…   # luego adb install -r
```

Smoke de Hermes directo (tool-calling):

```bash
source ~/.hermes/.env
curl -H "Authorization: Bearer $API_SERVER_KEY" http://127.0.0.1:8642/health
```

## 6. Troubleshooting

| Síntoma                                | Causa probable / remedio                                             |
|----------------------------------------|---------------------------------------------------------------------|
| `httpx.Timeout must either include…`   | falta un parámetro del Timeout; ver `hermes_client.py`              |
| bridge 000 pero proceso arriba         | matado por cierre de sesión: relanzar con `setsid nohup`/subshell   |
| App: sin `text.delta` aunque completó  | dedupe truncado (bug viejo) o suscripción tardía sin replay; compilar con el código actual |
| App no conecta; chip "connecting" fijo | WS no llega: verifica MagicDNS `aegis.tailXXXXXX.ts.net` e IP 100.x |
| `pkill uvicorn` mata la propia shell   | usar patrón `[u]vicorn` (evita auto-match)                          |
| Ollama OOM a 64k                       | RAM libre ~5 GB es justo; evitar construir contexto +44k sin cache_read |
| Tailscale "Logged out" tras reboot     | `sudo tailscale up --hostname aegis` y completar login (URL impresa)|

## 7. Puertos

| Puerto | Servicio      | Bind        |
|--------|---------------|-------------|
| 11434  | Ollama        | 127.0.0.1   |
| 8642   | Hermes API    | 127.0.0.1   |
| 8000   | Bridge Aegis  | 0.0.0.0 (malla) |