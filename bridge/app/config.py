"""Configuración del bridge Aegis (leída de .env/variables de entorno)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bridge_bind: str = "0.0.0.0"
    bridge_port: int = 8000

    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str = ""

    ollama_base_url: str = "http://127.0.0.1:11434"

    agent_worker: str = "worker"

    # Workspace donde viven los proyectos. Es la única raíz desde la que se
    # puede dar de alta un proyecto nuevo: la de un alta siempre se DERIVA de
    # área + alias, nunca se escribe a mano en el registro (ver app/projects.py).
    workspace_dir: str = "/RUTA/AL/WORKSPACE"
    #: Áreas donde Aegis puede crear un proyecto. Refleja la organización real.
    workspace_areas: str = "apps,web,mobile"

    # Modelo que planifica las tools en /autopilot. qwen2.5:7b es el único local
    # que produce llamadas utilizables (qwen2.5-coder:7b no emite tool_calls).
    autopilot_model: str = "qwen2.5:7b"
    # `autopilot_max_steps` se borro en la Fase 1: ningun lector. El tope de
    # pasos viene del cuerpo de la peticion (`main.AutopilotIn.max_steps`), y el
    # techo duro vive en `main._run_autopilot_once`. Un default en config que
    # no decide nada es un segundo sitio donde alguien va a cambiar el numero.

    # -- Clases de latencia (docs/vision.md §5, docs/motores.md §2) ----------
    #
    #: **Por qué una tabla y no un `if` en el bucle.** `docs/motores.md` §6 lo
    #: prohibe: «ninguna heurística en el bucle». Si algo decide, está en la tabla
    #: y en la traza. Y una tabla se puede testear, revertir con una variable y
    #: auditar sin abrir el bucle.
    #:
    #: **Por qué `t1_model` es otro.** Antes solo había un modelo: el 7B para
    #: todo. Con un solo modelo, «abstenerse» significaba pagar sus 4.400 MB y su
    #: latencia, que es exactamente lo que el camino rápido viene a evitar. Con
    #: T1 siendo un modelo pequeño **residente**, la abstención cuesta poco.
    #: El 7B queda para T2, por turnos.
    #:
    #: **Y esto es una hipótesis hasta que se mida.** Se espera que el 4B sea más
    #: rápido por ser más pequeño; nadie lo ha cronometrado todavía. Está medido
    #: en `docs/decisiones/002`. Si sale peor, se cambia esta línea y nada más:
    #: el modelo ya viaja por petición (`AutopilotIn.model`).

    #: Modelo de T1: corto, tool-calling, **residente**.
    #:
    #: ## Medido, no supuesto (2026-10-05, n=2-3 por modelo, mismo encargo)
    #:
    #: | modelo | mediana | ¿tool-calling? | VRAM |
    #: |---|---|---|---|
    #: | **`llama3.2:3b`** | **16,8 s** | sí | 1,9 GB |
    #: | `qwen2.5:7b` | 20,6 s | sí | 4,4 GB |
    #: | `qwen2.5-coder:7b` | 31,4 s | sí | 4,4 GB |
    #: | `gemma3:4b` | — | **roto** | 3,3 GB |
    #: | `qwen3:4b` | **212 s** | sí | 2,4 GB |
    #:
    #: **`qwen3:4b` era la suposición original y era falsa**: 10 veces más
    #: lento. Es un modelo de *thinking* y genera el razonamiento antes de
    #: responder; en un bucle que va a 9.000 tokens de prompt, eso lo hunde. Menos
    #: parámetros, peor latencia.
    #:
    #: ## Y el margen es pequeño, y eso es el dato importante
    #: 16,8 contra 20,6 es un 18 % — no el 10× que se esperaba. Porque **el
    #: bottleneck no es el modelo, es el prompt**: con 35.835 chars tardaba 49,1 s
    #: y con 22.847 tardaba 18,5 s. Un 36 % menos de prompt, un 62 % menos de
    #: tiempo.
    #:
    #: Cambiar de modelo es barato y ayuda, pero **no es la palanca**. Recortar el
    #: prompt sí lo es, y ahí van los 19.083 chars del schema de tools, que es
    #: lo único que se paga en cada paso sin condición.
    t1_model: str = "llama3.2:3b"

    #: Tope de pasos de T1. Menor que el de T2 a propósito: una petición corta que
    #: necesita ocho pasos ya no es una petición corta.
    t1_max_steps: int = 4

    #: Presupuesto de T0 en milisegundos. Lo declara la visión; lo comprueba
    #: `tests/test_intents.py::TestPresupuestoDeLatencia`. Si cambia uno, cambia
    #: el otro, y el diff lo enseña.
    t0_presupuesto_ms: int = 300

    # -- Neon (topología de las bases que gestiona Aegis) --------------------
    # La connection string NO se guarda: se pide a Neon por API cuando hace falta
    # (app/neon.py). Aquí solo vive la key, en el entorno y no en el repo.
    neon_api_key: str = ""

    #: Clave de la API de operación. Vacía = **sin auth**, que es lo que había
    #: antes y lo que hay hoy para todo lo existente.
    #:
    #: ## Por qué existe y por qué está vacía por defecto
    #: El bridge no tenía autenticación y el CORS era `*`. Mientras la única
    #: superficie era "lanzar una tarea y ver su traza", eso era asumible: la
    #: cola es privada por construcción. Pero los endpoints que añaden poder —
    #: dar permisos de escritura, denegar aprobaciones, leer notas— cambian de
    #: categoría: sin clave, cualquiera que llegue a la tailnet puede concederle
    #: permiso de escritura a Aegis sobre tus proyectos.
    #:
    #: **No es un salto al vacío.** Lo viejo se queda como está y lo nuevo nace
    #: cerrado: así la app no se rompe el día que la gires. Y se gira por nombre
    #: versionado (`AEGIS_API_KEY_V2` → `V3`), nunca sobreescribiendo la que
    #: está en uso.
    aegis_api_key: str = ""

    #: Serial adb del teléfono, cuando lo declara la persona a mano.
    #:
    #: El alias no es opcional: pydantic mapea `phone_serial` a la variable
    #: `PHONE_SERIAL`, no a `AEGIS_PHONE_SERIAL`. Sin alias, ponerlo en el `.env`
    #: no hacía nada —y una variable documentada que no hace nada es peor que no
    #: documentarla, porque parece que la intentaste.
    #:
    #: Y vive aquí y no solo en `os.environ` porque nadie exporta el `.env` al
    #: entorno: es la forma de que lo declarado en `bridge/.env` llegue de verdad.
    phone_serial: str = Field(default="", validation_alias="AEGIS_PHONE_SERIAL")

    #: IP del bridge para el APK del teléfono, cuando no es la de la tailnet.
    #:
    #: Se necesita cuando el teléfono no tiene Tailscale: se comprueba, y si no
    #: hay salida Aegis se niega a instalar — una app en el teléfono que no ve el
    #: bridge no es una app installed, es un icono.
    bridge_tailnet_ip: str = Field(default="",
                                   validation_alias="AEGIS_BRIDGE_TAILNET_IP")

    # -- Observabilidad -----------------------------------------------------
    log_dir: str = "data/logs"

    # -- Memoria del proyecto ('cerebro') -----------------------------------
    memory_enabled: bool = True
    memory_dir: str = "data/memory"
    memory_recall_k: int = 3
    memory_graph_backend: str = "sqlite"          # sqlite | graphiti | off
    embed_model: str = "nomic-embed-text"

    @property
    def hermes_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.hermes_api_key}"}


@lru_cache
def get_settings() -> Settings:
    return Settings()