"""Memoria episódica: ChromaDB embebido + embeddings locales de Ollama.

Cada episodio (run resuelto o fallido) se guarda como embedding del texto
`TAREA + SOLUCIÓN + CÓDIGO + ERROR EVITADO`, con metadata (agente, outcome,
conceptos, fecha). La recuperación es semántica por similitud coseno.

Dependencias opcionales a tu cargo (instalación manual):
    .venv/bin/pip install chromadb
y el modelo de embeddings en Ollama:
    ollama pull nomic-embed-text

Si ChromaDB falta o Ollama cae, la fachada degrada con elegancia: el grafo
(SQLite) sigue funcionando y este store simplemente no persiste.
"""

import logging
import os
import uuid
from typing import Any, Optional

log = logging.getLogger("aegis.bridge.memory.episodic")


def build_episode_doc(episode: dict[str, Any]) -> str:
    parts: list[str] = []
    if episode.get("prompt"):
        parts.append("TAREA: " + episode["prompt"])
    if episode.get("summary"):
        parts.append("SOLUCIÓN: " + episode["summary"])
    code = episode.get("code") or []
    if code:
        parts.append("CÓDIGO GENERADO:\n" + "\n---\n".join(code))
    if episode.get("error"):
        parts.append("ERROR EVITADO: " + episode["error"])
    return "\n".join(p for p in parts if p) or episode.get("run_id", "episodio")


class EpisodicMemory:
    """Almacén vectorial de episodios (embeddings via embedder, índice Chroma)."""

    def __init__(self, persist_dir: str, embedder: Any,
                 embed_model: str = "nomic-embed-text",
                 collection: str = "episodes") -> None:
        self.embedder = embedder
        self.embed_model = embed_model
        self.enabled = False
        self._collection: Any = None
        self._client: Any = None
        os.makedirs(persist_dir, exist_ok=True)
        try:
            import chromadb  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            log.error("chromadb no instalado (%s) — memoria episódica desactivada", exc)
            return
        try:
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=collection, metadata={"hnsw:space": "cosine"})
            self.enabled = True
            log.info("memoria episódica lista en %s (embed: %s)", persist_dir, embed_model)
        except Exception as exc:  # noqa: BLE001
            log.error("ChromaDB no arrancó (%s) — memoria episódica desactivada", exc)

    async def add_episode(self, episode: dict[str, Any]) -> Optional[str]:
        if not self.enabled:
            return None
        doc = build_episode_doc(episode)
        emb = await self.embedder.embed_texts([doc], self.embed_model)
        if not emb:
            return None
        run_id = (episode.get("run_id") or "").strip() or str(uuid.uuid4())
        meta = {
            "agent": (episode.get("agent") or "")[:64],
            "outcome": (episode.get("outcome") or "")[:16],
            "concepts": ",".join(episode.get("concepts") or [])[:500],
            "at": (episode.get("at") or "")[:40],
        }
        self._collection.upsert(ids=[run_id], embeddings=emb,
                                documents=[doc], metadatas=[meta])
        return run_id

    async def search(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        emb = await self.embedder.embed_texts([query], self.embed_model)
        if not emb:
            return []
        res = self._collection.query(
            query_embeddings=emb, n_results=max(k, 1),
            include=["documents", "metadatas", "distances"])
        out: list[dict[str, Any]] = []
        docs = res.get("documents") or [[]]
        metas = res.get("metadatas") or [[]]
        dists = res.get("distances") or [[]]
        for doc, meta, dist in zip(docs[0], metas[0], dists[0]):
            out.append({"document": (doc or "")[:2000],
                        "metadata": meta or {},
                        "distance": round(dist, 4)})
        return out

    def count(self) -> int:
        if not self.enabled:
            return 0
        return self._collection.count()