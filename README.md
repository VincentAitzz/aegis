# Aegis

Cliente móvil desacoplado para un backend multiagente **local** (Hermes Agent + Ollama),
comunicándose **exclusivamente** a través de una red privada virtual de malla
(Tailscale/MagicDNS). El móvil nunca ve Internet ni IPs públicas: solo nodos de la malla.

```
┌─────────────┐  tailnet (MagicDNS)   ┌──────────────┐   loopback   ┌────────────┐  127.0.0.1  ┌────────┐
│  Android/   │  REST + WS            │  Aegis bridge│──────────────▶│  Hermes    │────────────▶│  Ollama │
│  iOS app    │──────►/──────────────►│  FastAPI     │  SSE events   │  v0.21.4   │  /v1        │ 7b@64k  │
│  (Flutter)  │  aegis.<tailnet>..ts  │  :8000       │◀──────────────│  :8642     │◀────────────│ :11434  │
└─────────────┘                       └──────────────┘               └────────────┘             └────────┘
```

## Stack

| Capa     | Tecnología                                        |
|----------|---------------------------------------------------|
| App      | Flutter 3.x + Riverpod, clean architecture         |
| Bridge   | Python 3.14 + FastAPI + Uvicorn + httpx + SSE→WS   |
| Agentes  | Hermes Agent v0.21.4 (API server)                  |
| LLM      | Ollama 0.34.x con `qwen2.5-coder:7b` @ 64k context |
| Malla    | Tailscale + MagicDNS (ACL restrictiva opcional)    |

## Repositorio

```
bridge/        Puente REST+WS (FastAPI)
mobile/        App Flutter (Aegis Console)
infra/         Scripts de aprovisionamiento (tailscale, ollama, dispositivo)
docs/          Arquitectura, contrato API y runbook
```

## Requisitos de hardware (benchmark real)

- RTX 3050 Laptop 6 GB VRAM + ~15 GB RAM.
- Solo es viable **un** modelo: `qwen2.5-coder:7b` (Q4_K_M, 4.7 GB) con
  `num_ctx=64_000` (exigencia mínima de Hermes: `MINIMUM_CONTEXT_LENGTH`).
- 14b+ @64k **no entra** (pesos 9 GB + KV ~12 GB = 21 GB); el orquestador y el
  worker son **roles lógicos** sobre el mismo 7b. La ruta a 14b queda documentada
  en `docs/architecture.md` para hardware futuro.

## Servicios

| Servicio | Host env | Puerto | Arranque                                           |
|----------|----------|--------|----------------------------------------------------|
| Ollama   | 127.0.0.1| 11434  | `infra/ollama/start-ollama.sh` (context 64k)       |
| Hermes   | 127.0.0.1| 8642   | `hermes gateway run` (`~/.hermes/.env` → API key)  |
| Bridge   | 0.0.0.0  | 8000   | `bridge/run.sh` (`bridge/.env` → clave real)       |

> Claves: nunca en el repo. Ver `docs/runbook.md` para la política de secretos.

## Puesta en marcha rápida

```bash
# 1) Backend local
./infra/ollama/start-ollama.sh            # sirve en 127.0.0.1:11434
hermes gateway run                        # API server en 127.0.0.1:8642

# 2) Bridge
cd bridge && python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # pega HERMES_API_KEY (de ~/.hermes/.env)
./run.sh

# 3) Malla (una vez por nodo, con sudo)
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up --hostname aegis        # autentica y obtén el MagicDNS

# 4) App
cd mobile
flutter build apk --debug --dart-define=API_HOST=aegis.<tailnet>.ts.net
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Sin Tailscale todavía, el desarrollo local usa `adb reverse`:

```bash
infra/mobile/install-phone.sh            # installa APK + adb reverse 8000/11434
```

## Estado

- ✅ E2E completo desde Android a través de la malla: lanzar tarea → tool calling →
  stream de deltas → respuesta final en pantalla.
- ✅ Contrato bidireccional: `POST /tasks`, WS `/ws` (suscribir/steer/approve/stop),
  replay de historial para suscriptores tardíos.
- Pendiente: ACL en admin console (`infra/tailnet/acl-policy.json`), firmado de APK.

Ver `docs/architecture.md` (diseño + contrato) y `docs/runbook.md` (operación).