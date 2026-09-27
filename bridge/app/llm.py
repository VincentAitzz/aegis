"""Introspección, calentamiento de modelos y embeddings en Ollama."""

import logging
from typing import Any, Optional

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

    # -- embeddings (memoria) ------------------------------------------------
    async def embed_texts(self, texts: list[str], model: str = "nomic-embed-text") -> Optional[list[list[float]]]:
        """Embeddings locales vía /api/embed de Ollama (sin salida a Internet).

        Devuelve None si el modelo de embeddings no está en Ollama (fallo
        degradable: la memoria episódica simplemente no persiste ese episodio).
        """
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=None)) as client:
                r = await client.post(f"{self.base_url}/api/embed",
                                      json={"model": model, "input": texts})
                r.raise_for_status()
                return r.json().get("embeddings")
        except httpx.HTTPError as exc:
            log.warning("embeddings %s fallaron: %s", model, exc)
            return None


ollama = Ollama(get_settings().ollama_base_url)