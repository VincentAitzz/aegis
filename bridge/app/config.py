"""Configuración del bridge Aegis (leída de .env/variables de entorno)."""

from functools import lru_cache

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
    autopilot_max_steps: int = 6

    # -- Neon (topología de las bases que gestiona Aegis) --------------------
    # La connection string NO se guarda: se pide a Neon por API cuando hace falta
    # (app/neon.py). Aquí solo vive la key, en el entorno y no en el repo.
    neon_api_key: str = ""

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