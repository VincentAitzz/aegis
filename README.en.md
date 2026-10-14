# Aegis

[Español](README.md) · English

An assistant that lives on your own machine. It hears what you say, acts on your
tools, remembers what matters about you, and tells you about the problems it
finds — with no cloud, no account, and not a single request to a third party.

```
┌──────────────┐   REST    ┌─────────────────┐   HTTP    ┌──────────┐
│  Flutter app │ ────────► │  FastAPI bridge │ ────────► │  Ollama  │
│  (Android)   │ ◄──────── │      :8000      │ ◄──────── │  :11434  │
└──────────────┘   trace   │  + autopilot    │   trace   └──────────┘
                          │  + memory       │
                          └─────────────────┘
```

## What it is, and what it is not

**It is** a local agent that actually executes: it calls its own tools, operates
your repositories, builds your app, and lets you watch every step. What it did is
in `bridge/data/logs/runs/<run_id>.jsonl`, step by step.

**It is not** a chat with a model. A chat hands you text; Aegis hands you what
happened, with the trace next to it — and the verdict is computed **from the
trace**, never from what the model says.

Nor is it a service: three processes you start yourself, on your machine, that go
away when you do.

## What makes it different

### The verdict comes from the trace

This is the central invariant, and it exists because of a concrete failure. The
loop marked `success` on any `task.done` without looking at what had actually run;
those fake episodes went into memory; `recall` fed them back as *"similar
episodes solved before"*; and the model learned that the answer was "OK" and
answered **without calling anything**.

Measured, with interleaved ablation (n=8):

| Memory | Tool-calling |
|---|---|
| With 3 fake episodes | **0/8** |
| Without the memory block | **7/8** |

Three fake episodes are enough. That is why only `success` episodes **with named
tools** are ever injected into the prompt, and why `app/veredicto.py` is the only
place that decides how a run ended.

### Two engines would mean two places a guardrail can live

This repo used to have a conversation engine alongside the autopilot. It was
deleted: nothing called it any more, and `docs/architecture.md` still documented
it as a live API in fifteen places. An invariant that depends on a component
nobody uses is not an invariant; it is an intention.

### The prompt is a budget

Measured on the reference machine: at 35,835 characters a run took 49.1 s; at
22,847 it took 18.5 s. 36 % less prompt, 62 % less time.

That is why lessons reach the prompt as an **index**, not whole, and why your
profile is never injected in full. See `docs/decisiones/002-camino-rapido.md`.

### Nothing irreversible on its own

Three autonomy levels. Aegis reads and checks whatever it wants without asking.
To **write**, it needs you to flag the project — and the switch only turns on if
that project has a declared verifier, because without one there is nothing to
check the work against. And anything that leaves your disk it always asks about,
with the reason written down.

Level 3 (migrate a database, install an APK, create a project) asks in **all
three modes**. There is no mode that skips the queue.

## Getting started

You need Linux, Python ≥ 3.12 and a local model. For the mobile app: Flutter, a
JDK and the Android SDK — the bridge needs none of the three.

```bash
git clone https://github.com/VincentAitzz/aegis.git && cd aegis
bash infra/setup.sh                 # venv + .env + checks
```

Start Ollama with a 64,000-token context and pull the models:

```bash
bash infra/ollama/start-ollama.sh
ollama pull qwen2.5-coder:7b       # ~4.7 GB
ollama pull nomic-embed-text       # memory embeddings, ~274 MB
ollama pull llama3.2:3b            # T1, the fast-path model
```

Start the bridge:

```bash
bash infra/stack.sh arrancar
bash infra/stack.sh estado         # health of the three + what Aegis may write
```

And talk to it:

```bash
cd bridge
bin/api GET health
bin/api POST autopilot '{"project":"aegis","prompt":"list the projects and their verifiers"}'
```

### The mobile app (optional)

```bash
bash infra/mobile/emulador.sh arrancar   # AVD replicating a 1080x2340 Android
cd mobile && flutter build apk --debug --dart-define=API_HOST=10.0.2.2
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

The emulator is the default target on purpose: a real phone is only touched when
someone asks **explicitly** and with the deploy gate green. Writing to someone's
phone without warning is also broken.

To reach the bridge from another machine, see `docs/runbook.md` §3 (Tailscale).

## Hardware

All of this is designed around **a 6 GB GPU**. The measured numbers, what fits
and what does not, are in **[`docs/hardware.md`](docs/hardware.md)**.

Short version: with 6 GB of VRAM and 16 GB of RAM, `qwen2.5-coder:7b` at 64,000
tokens of context. A 14b at 64k **does not fit**: 9 GB of weights plus ~12 GB of
KV cache against a 6 GB card.

## How it fits together

| Layer | What it does |
|---|---|
| **Autopilot** | The only engine. model → tool → observation → model. It executes. |
| **Guardrails** | `bridge/app/mcp_ops.py`. Allowlist, denylist, secret scanning, syntax rollback. |
| **Verdict** | `bridge/app/veredicto.py`. Decides how the run ended, from the trace. |
| **Memory** | Episodic (Chroma) + conceptual graph (SQLite). Degrades on its own without Chroma. |
| **Autonomy** | `bridge/app/autonomy.py`. The three levels and the approval queue. |
| **App** | Flutter. Projects, approvals, traces, and the TOTP vault. |

## What you should know about small models

The 6-7 GB models available locally **do not emit reliable `tool_calls`**: they
write the call's JSON into the text instead. That is why the autopilot exists, and
it is not an implementation detail.

The rest are measured consequences of the same thing:

- Switching models is **not** the lever; trimming the prompt is.
- `qwen3:4b` was the assumption and it was false: 212 s against 16.8 s for
  `llama3.2:3b`. Fewer parameters, worse latency, because it is a *thinking*
  model and generates the reasoning before answering.
- A scalar wrapped in an object (`repo: {"type": "aegis"}`) is repaired by
  `coerce_args`. It is the typical malformation, and it used to kill the run.

## Verifying it works

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -q   # ~700 tests
cd bridge && .venv/bin/python bin/check-imports.py               # 28 modules
cd mobile && flutter analyze && flutter test                     # 0 issues, green
```

All three run in CI. The bridge suite passes **without Flutter, a JDK or the
Android SDK**: it is the check that the repo does not depend on anyone's machine,
which is why it is in CI and not just here.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) (in Spanish). The short version: the
commands above must be green, and **every fix ships with a written lesson**.

The 121 lessons in `bridge/lessons/aegis.md` (also in Spanish) are the most useful
part of this repo. Before you touch anything, check whether it already broke once.

## Documentation

| | |
|---|---|
| [`docs/hardware.md`](docs/hardware.md) | Measured numbers: what fits on which GPU |
| [`docs/vision.md`](docs/vision.md) | What it wants to be, and where it is going |
| [`docs/architecture.md`](docs/architecture.md) | Design, contract, and the why of each decision |
| [`docs/runbook.md`](docs/runbook.md) | Operation, diagnostics, troubleshooting |
| [`docs/decisiones/`](docs/decisiones/) | ADRs. The authority for each decision |
| [`AGENTS.md`](AGENTS.md) | How this repo's supervisor works |

## License

AGPL-3.0. See [`LICENSE`](LICENSE) and the reasoning in [`NOTICE.md`](NOTICE.md).