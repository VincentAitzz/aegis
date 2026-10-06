"""Introspección, calentamiento de modelos y embeddings en Ollama.

## Por qué ya no queda un solo `read=None` en este fichero
Los había tres. Dos eran un **riesgo de disponibilidad**, no una comodidad:

- **`embed_texts`** con `read=None` se awaita **al empezar y al terminar cada
  run**: `main._memory_context` (línea ~184) lo llama antes de construir el
  prompt, y `main._registrar_run` lo llama al guardar el episodio. Un endpoint de
  `/api/embed` que acepta la conexión y nunca contesta —un Ollama sin
  `nomic-embed-text` cargado, una cola de inference llena, una GPU ocupada
  generando— dejaba el run **colgado sin límite y sin motivo**: no había ni
  timeout ni `fin` que lo explicara. La memoria es un accesorio (degradable, y el
  propio código lo trata como tal en todas partes) y no puede ser lo que decide
  si Aegis contesta.
- **`ensure_model`** con `read=None` es menos grave porque va en
  `asyncio.create_task` (nadie lo espera), pero una tarea que no termina nunca
  acumula sockets. Además era **código muerto**: su único llamador era
  `_submit_task`, que se fue con el motor de Hermes en la Fase 1. No se arregla,
  se borra.

## El número
`EMBED_TIMEOUT_S = 60`. Embeddings de una resentment corta con un modelo de
embeddings (no de lenguaje) tardan milisegundos. Sesenta segundos es ya tres
órdenes de magnitud de margen: si se agota, el problema es que algo está roto,
y un run que falla en un minuto es diagnosticable; uno que no vuelve nunca no lo
es.
"""

import logging
from typing import Any, Optional

import httpx

from .config import get_settings

log = logging.getLogger("aegis.bridge.llm")

#: Tope de una llamada a `/api/embed`. Ver el docstring del módulo.
EMBED_TIMEOUT_S = 60.0


class Ollama:
    """Acceso mínimo a Ollama: qué modelos hay, y vectores para la memoria."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _timeout(self, read: float) -> httpx.Timeout:
        return httpx.Timeout(connect=5.0, read=read, write=10.0, pool=5.0)

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

    # -- embeddings (memoria) ------------------------------------------------
    async def embed_texts(self, texts: list[str],
                          model: str = "nomic-embed-text") -> Optional[list[list[float]]]:
        """Embeddings locales vía `/api/embed` de Ollama (sin salida a Internet).

        Devuelve `None` si falla —el modelo de embeddings no está en Ollama, o
        tardó demasiado—. Es **degradable a propósito**: quien llama
        (`ProjectMemory.remember` y `recall`) trata `None` como "sin memoria
        ahora" y sigue. Un accesorio no puede tumbar lo que.accessory.accessory
        """
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout(EMBED_TIMEOUT_S)) as client:
                r = await client.post(f"{self.base_url}/api/embed",
                                      json={"model": model, "input": texts})
                r.raise_for_status()
                return r.json().get("embeddings")
        except httpx.HTTPError as exc:
            log.warning("embeddings %s fallaron: %s", model, exc)
            return None


ollama = Ollama(get_settings().ollama_base_url)
