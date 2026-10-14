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
    #
    # `~/Workspace` y no una ruta absoluta: es una convención de organización,
    # no una propiedad de la instalación. Quien clone esto puede tener sus
    # proyectos en otro sitio —y quien solo quiera correr el bridge, en ninguno—,
    # así que se cambia en `bridge/.env` (`WORKSPACE_DIR=...`) y no en el código.
    workspace_dir: str = "~/Workspace"
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
#: **Por qué `t1_model` NO es otro (esto se dio la vuelta el 2026-10-14).**
    #:
    #: Antes era `llama3.2:3b`, con este motivo: con un solo modelo, «abstenerse»
    #: significaba pagar sus 4,4 GB y su latencia, que es justo lo que el camino
    #: rápido viene a evitar. La abstención sería cara; con un 3B residente, barata.
    #:
    #: **El motivo era bueno y el coste estaba mal medido.** Lo que se comparó
    #: fue el tiempo de un *run de agente* (16,8 s contra 20,6 s, un 18 %), no
    #: el coste de tener **los dos modelos resident a la vez**. Y ese coste no es
    #: de VRAM, que es de la que no hay: es de RAM. Medido con los dos cargados:
    #:
    #: ```
    #: llama-server (7B)      6,07 GB de RAM
    #: llama-server (embed)   0,64 GB de RAM
    #: total                  6,71 GB   de 15 GB, y creciendo por rachas
    #: ```
    #:
    #: Dos modelos resident son **dos `llama-server` en RAM a la vez**, y eso
    #: multiplica la superficie en la que un OOM mata lo que esté abierto. El
    #: editor ya se cayó una vez con los dos cargados. «Que Aegis no se cuelgue
    #: ni pierda el trabajo» es uno de los cuatro sentidos de «confiable», y un
    #: diseño que multiplica la memoria en uso le juega en contra.
    #:
    #: ## Sobre el swap: hay zram, y no es de disco
    #:
    #: `/dev/zram0`, **15,3 GB con compresión zstd**, creado en cada arranque
    #: por `zram-generator` (un *systemd generator*, no un servicio). Comprime
    #: ~4:1, así que su coste en RAM real es una fracción de su tamaño.
    #:
    #: **No hay swap en disco.** Eso es lo que queda: zram es RAM comprimida, es
    #: holgura, no seguro. Si la RAM se agota, el OOM sigue pudiendo matar. Por
    #: eso el trabajo de estabilidad no es «crear un swapfile» —el zram ya está
    #: y se automantiene— sino **no pedir más memoria de la que hace falta**, que
    #: es lo que hace este cambio.
    #:
    #: ## Lo que cuesta la decisión, medido
    #:
    #: | | T1 (con otro modelo) | T1 (el mismo 7B, sin schema) |
    #: |---|---|---|
    #: | primer token en conversación | 0,14 s | 0,37 s |
    #: | RAM resident | 2 modelos (~8 GB) | 1 modelo (~6 GB) |
    #: | intercambio por petición de trabajo | **6–15 s** | **0** |
    #:
    #: Se paga **0,23 s por turno de conversación** y se ahorran **6–15 s por
    #: petición de trabajo**. El equilibrio está en ~1 trabajo por cada 15 turnos de
    #: conversación, y por encima de ahí tener las dos solo empeora. El uso real es
    #: sobre todo trabajo, así que gana por un factor de 25 o más.
    #:
    #: ## Y T1 no desaparece por esto
    #:
    #: T1 pasa a ser **«el mismo modelo, sin schema»**, que era la idea desde el
    #: principio: sin schema no hay nada que llamar, y no puede inventarse una
    #: llamada. Lo que se elimina es el intercambio, no la clase de latencia.
    #:
    #: **Empty por defecto a propósito.** Un valor que tiene que coincidir con
    #: otro es un valor que divergirá; por eso no se pone `qwen2.5:7b` aquí, sino
    #: `""` y `modelo_t1()` lo resuelve. Cambiar el modelo base sigue siendo
    #: cambiar una línea, y las dos clases no pueden quedar desincronizadas solas.
    t1_model: str = ""

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

    def modelo_t1(self) -> str:
        """El modelo que responde en T1. Vacío significa «el de siempre».

        Existe para que el caso de un solo modelo sea el **valor por defecto** y
        no un estado que hay que mantener. Un `t1_model` que se parece a
        `autopilot_model` diverge en cuanto alguien cambia uno y no el otro, y
        esa divergencia no da ningún error: solo aparece como un intercambio de
        6–15 s en la traza, semanas después. Con `""` no hay nada que mantener.

        Poner aquí un nombre sigue funcionando, y es lo que hace falta para
        medir un modelo pequeño al lado del grande sin tocar nada más.
        """
        return self.t1_model.strip() or self.autopilot_model


@lru_cache
def get_settings() -> Settings:
    return Settings()