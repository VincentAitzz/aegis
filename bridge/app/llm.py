"""Introspección y calentamiento de modelos en Ollama."""

import logging
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("aegis.bridge.llm")


class Ollama:
    """Acceso mínimo a Ollama (status de modelos y warm-up de carga)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                return r.json().get("models", [])
        except httpx.HTTPError:
            return []

    async def loaded_models(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/api/ps")
                r.raise_for_status()
                return r.json().get("models", [])
        except httpx.HTTPError:
            return []

    async def ensure_model(self, name: str) -> None:
        """Fuerza la carga del modelo en GPU/RAM (warm-up vacío). No bloquea el API."""
        import asyncio
        async def _warm() -> None:
            try:
                loaded = {m.get("name") for m in await self.loaded_models()}
                if name in loaded:
                    return
                log.info("cargando modelo %s en Ollama…", name)
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=None)) as client:
                    await client.post(f"{self.base_url}/api/generate",
                                      json={"model": name, "prompt": "", "stream": False})
            except httpx.HTTPError as exc:
                log.warning("warm-up de %s falló: %s", name, exc)
        asyncio.create_task(_warm())


ollama = Ollama(get_settings().ollama_base_url)