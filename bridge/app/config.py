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
    agent_orchestrator: str = "orchestrator"

    @property
    def hermes_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.hermes_api_key}"}


@lru_cache
def get_settings() -> Settings:
    return Settings()