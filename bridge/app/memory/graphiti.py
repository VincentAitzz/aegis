"""Backend de grafo avanzado (opt-in): Graphiti + FalkorDB.

> **Sin verificar.** `graphiti-core` y `falkordb` están comentados en
> `requirements.txt`, este modulo no tiene **ningún test** y no se ha ejecutado
> nunca en esta máquina. El backend por defecto es SQLite desde 2026-09-27.
>
> Se conserva, y no por creencia: está a un `pip install` de activarlo y es la
> dirección obvia si el grafo temporal hace falta. Pero una opción que nadie ha
> ejecutado es una **promesa, no una capacidad**, y debe decirse como tal. Si vas
> a activarla, hazlo en un branch con un test que la exercite: leer este
> docstring creyendo que funciona es el modo de fallo más caro que hay, porque
> el que no falla es el código que nadie llega a ejecutar.

El 'cerebro completo': knowledge-graph **temporal** con entidades y aristas
extraídas por LLM en cada episodio, consultable semánticamente. Diseñado para
memoria de agentes a largo plazo (getzep/graphiti).

Cómo activarlo (a tu cargo, requisitos de instalación):
    .venv/bin/pip install falkordb graphiti-core
    .venv/bin/pip install -r requirements.txt   # ya incluye lo anterior si descomentas
    ollama pull nomic-embed-text                # embeddings (ya usados por el storage episódico)
    echo "MEMORY_GRAPH_BACKEND=graphiti" >> bridge/.env
    reiniciar el bridge

El LLM local (qwen via endpoint OpenAI-compatible de Ollama) actúa como
extractor de entidades/relaciones. NOTA: la API de `graphiti-core` evoluciona
rápido; este wrapper aísla los puntos de contacto en dos métodos privados
(`_build_episode`, `_search`) para que un cambio de firma se corrija en un solo
lugar. Si la construcción o la importación fallan, la fachada degrada a SQLite.
"""

import logging
from typing import Any, Optional

log = logging.getLogger("aegis.bridge.memory.graphiti")


class GraphitiBrain:
    """Envoltorio local a `graphiti_core.Graphiti` sobre el grafo felino (FalkorDB embebido)."""

    def __init__(self, settings: Any, uri: Optional[str] = None) -> None:
        self.settings = settings
        try:
            from graphiti_core import Graphiti  # noqa: PLC0415
            from graphiti_core.embeddings import OllamaEmbedding  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "backend graphiti requiere 'pip install graphiti-core falkordb'") from exc

        # FalkorDB embebido (sin servidor) o remoto vía `falkor://host:6379`
        self._uri = uri or getattr(settings, "graphiti_uri", None) or "falkor://localhost:6379"
        self._embed_model = getattr(settings, "embed_model", "nomic-embed-text")
        self._ollama_url = getattr(settings, "ollama_base_url", "http://127.0.0.1:11434") + "/v1"

        # LLM extractor = qwen local vía API OpenAI-compatible de Ollama.
        self._llm = _OllamaOpenAI(settings, self._ollama_url)
        self._embeddings = OllamaEmbedding(
            model=self._embed_model, base_url=self._ollama_url.rstrip("/v1"))

        try:
            self._graphiti = Graphiti(
                uri=self._uri,
                llm_client=self._llm,
                embeddings=self._embeddings,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Graphiti no arrancó: {exc}") from exc
        log.info("GraphitiBrain listo (uri=%s, embed=%s)", self._uri, self._embed_model)

    async def save_episode(self, episode: dict[str, Any], concepts: list[str]) -> None:
        run_id = episode.get("run_id", "?")
        try:
            await self._graphiti.add_episode(
                self._episode_body(episode), source_name=run_id)
            log.info("graphiti: episodio %s ingerido", run_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("graphiti no ingirió %s: %s", run_id, exc)

    async def search(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        try:
            results = await self._graphiti.search(query, limit=k)
            return [{"document": getattr(r, "content", ""), "metadata": {}, "distance": None}
                    for r in results]
        except Exception as exc:  # noqa: BLE001
            log.warning("graphiti search falló: %s", exc)
            return []

    async def neighbors(self, concepts: list[str], depth: int = 1, limit: int = 12) -> list[dict[str, Any]]:
        return await self.search(" ".join(concepts), k=limit)

    async def match_episodes(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        return await self.search(query, k=limit)

    def close(self) -> None:
        pass

    @staticmethod
    def _episode_body(episode: dict[str, Any]) -> str:
        parts: list[str] = []
        if episode.get("prompt"):
            parts.append("TAREA: " + episode["prompt"])
        if episode.get("summary"):
            parts.append("SOLUCIÓN: " + episode["summary"])
        code = episode.get("code") or []
        if code:
            parts.append("CÓDIGO:\n" + "\n---\n".join(code))
        if episode.get("error"):
            parts.append("ERROR EVITADO: " + episode["error"])
        return "\n".join(parts) or "EPISODIO"


class _OllamaOpenAI:
    """Cliente LLM mínimo OpenAI-compatible hacia Ollama, para el extractor de Graphiti.

    `graphiti_core` acepta un cliente `LLMClient`; este adaptador intenta el
    constructor más común (`ModelClient`) y degrada con aviso de ajuste si la
    firma cambia entre versiones.
    """

    def __init__(self, settings: Any, base_url: str) -> None:
        self.base_url = base_url
        self.model = getattr(settings, "agent_worker", "worker") or "qwen2.5-coder:7b"
        try:
            from graphiti_core.llm_client import ModelClient  # noqa: PLC0415
            self._client = ModelClient(model=self.model, base_url=base_url)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "API de graphiti_core cambió: ajusta _OllamaOpenAI "
                f"(constructor ModelClient falló: {exc})") from exc