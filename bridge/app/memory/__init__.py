"""Memoria del proyecto Aegis: 'cerebro' de dos niveles.

  (a) Episódica  — ChromaDB embebido + embeddings locales (Ollama). Semántica.
  (b) Conceptual — grafo persistente en SQLite (solo stdlib).

Ciclo de vida:
  * `main._registrar_run`  →  `remember(episodio)`. Lo llama el **autopilot** al
    terminar un run, con `outcome` derivado de la traza.
  * `POST /autopilot` y `/autopilot/start`  →  `recall(prompt)` +
    `render_context()`, inyectado como bloque `EXPERIENCIA PASADA RELEVANTE` en
    el system prompt.

## Lo que este docstring mentía hasta la Fase 1
Decía `(c) Nativa — memory graph de Hermes (~/.hermes/memories/)` y citaba
`hooks.on_terminal_event` y `POST /tasks` como ciclo de vida. Los tres eran
de un diseño retirado: el grafo nativo de Hermes nunca lo leyó nadie desde el
bridge, y los otros dos desaparecieron con `relay.py` y `hooks.py`. Un
docstring que describe un flujo que ya no existe es peor que no tenerlo: el que
lo lea creería que el sitio está cuidado.

## Por qué (c) se fue con Hermes
La memoria que queda es **local y escribible sin red**: Chroma embebido y
SQLite. El grafo nativo de Hermes vivía en `~/.hermes/memories/`, fuera del
bridge y fuera de la máquina si Hermes vivía en otro sitio — o sea, que Aegis
dependía de un componente que ya no controla. El invariante del repo es que
Aegis no es punto único de falla; una memoria que solo existe dentro del
segundo motor lo era.
"""

import logging
import os
from typing import Any, Optional

from .episodic import EpisodicMemory
from .sqlite_graph import SQLiteGraph, extract_concepts

log = logging.getLogger("aegis.bridge.memory")

_memory: Optional["ProjectMemory"] = None


class ProjectMemory:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        os.makedirs(settings.memory_dir, exist_ok=True)

        # (a) episódica (degradable: sin chromadb/ollama no persiste, no rompe)
        self.episodic: Optional[EpisodicMemory] = None
        if settings.memory_enabled:
            from ..llm import ollama
            self.episodic = EpisodicMemory(
                persist_dir=os.path.join(settings.memory_dir, "episodes"),
                embedder=ollama,
                embed_model=settings.embed_model)

        # (b) grafo conceptual
        #
        # ## Por qué ya no hay backend `graphiti`
        # Existía `app/memory/graphiti.py` (129 líneas) y se elegía con
        # `MEMORY_GRAPH_BACKEND=graphiti`. Sus requisitos estaban **comentados**
        # en `requirements.txt`, sus propias dependencias no se habían
        # instalado, y el módulo se declaraba a sí mismo "sin verificar, nunca
        # se ha ejecutado en esta máquina". Es decir: un instrumento que no
        # corre, disfrazado de alternativa (A-090). Se borró en la Fase 1 en
        # lugar de dejarlo como opción: una rama que nadie ha ejecutado no es
        # una opción, es una suposición con `import` debajo.
        self.graph: Any = None
        backend = settings.memory_graph_backend
        if backend == "off":
            self.graph = None
        else:
            self.graph = SQLiteGraph(os.path.join(settings.memory_dir, "brain.db"))

        if self.episodic:
            log.info("memoria lista: episódica=%s, grafo=%s (%s)",
                     bool(self.episodic.enabled),
                     type(self.graph).__name__ if self.graph else "off", backend)

    # -- escritura ----------------------------------------------------------
    async def remember(self, episode: dict[str, Any]) -> None:
        run_id = episode.get("run_id", "?")
        try:
            concepts = extract_concepts(" ".join(filter(None, [
                episode.get("prompt"), episode.get("summary"), episode.get("error")])))
            episode["concepts"] = concepts
            if self.graph:
                self.graph.save_episode(episode, concepts)
            if self.episodic and self.episodic.enabled:
                await self.episodic.add_episode(episode)
            log.info("memoria: episodio %s (%s) con %d conceptos",
                     run_id, episode.get("outcome", "?"), len(concepts))
        except Exception as exc:  # noqa: BLE001 — la memoria jamás hunde un run
            log.warning("memoria no pudo guardar episodio %s: %s", run_id, exc)

    # -- lectura ------------------------------------------------------------
    async def recall(self, query: str, k: Optional[int] = None) -> dict[str, Any]:
        k = k or self.settings.memory_recall_k
        episodes: list[dict[str, Any]] = []
        if self.episodic and self.episodic.enabled:
            try:
                episodes = await self.episodic.search(query, k)
            except Exception as exc:  # noqa: BLE001
                log.debug("recall episódico falló (%s) → grafo léxico", exc)
        graph: list[dict[str, Any]] = []
        if self.graph:
            concepts = extract_concepts(query, limit=6)
            graph = self.graph.neighbors(concepts, depth=1, limit=8) \
                if hasattr(self.graph, "neighbors") else []
            if not episodes:
                episodes = self.graph.match_episodes(query, limit=k) \
                    if hasattr(self.graph, "match_episodes") else []
        return {"episodes": episodes, "graph": graph}

    def render_context(self, results: dict[str, Any], max_chars: int = 1800) -> str:
        """Formatea los resultados de `recall` para inyectar en instructions.

        ## El filtro que hace que esto sirva
        `recall` devuelve lo más cercano **sin mirar el `outcome`**, y el filtro
        está aquí, tres líneas más abajo: solo pasan los `success`.

        Un `failed` (o un `sin_evidencia`) presentado bajo «resueltos antes» le
        enseña al modelo un patrón que no funcionó: medido, tres episodios falsos
        bajaban el tool calling de 7/8 a 0/8. Ver A-016. Por eso el filtro es
        explícito y no una propiedad del almacén: si el recall empezara a
        filtrar por su cuenta, este bloque se seguiría creyendo que filtra y
        dejaría de hacerlo sin que nada cambiara de aspecto.
        """
        episodes = [e for e in (results.get("episodes") or [])
                    if (e.get("metadata") or {}).get("outcome") == "success"]
        graph = results.get("graph") or []
        if not episodes and not graph:
            return ""
        lines = ["## Contexto de experiencia previa"]
        if episodes:
            lines.append("### Episodios similares resueltos antes")
            for item in episodes[:3]:
                doc = item.get("document") or ""
                head = " ".join(doc.split())[:280]
                meta = item.get("metadata") or {}
                dist = item.get("distance")
                tag = f" (dist={dist})" if dist is not None else ""
                lines.append(f"- [success] {head}{tag}")
        if graph:
            lines.append("### Conceptos conectados")
            for node in graph[:6]:
                if isinstance(node, dict):
                    lines.append(f"- {node.get('concept')} — en {node.get('total_runs', 1)} episodio(s)")
        out = "\n".join(lines)
        return out[:max_chars]

    def status(self) -> dict[str, Any]:
        return {
            "episodic_enabled": bool(self.episodic and self.episodic.enabled),
            "graph_backend": type(self.graph).__name__ if self.graph else "off",
            "graph_backend_setting": self.settings.memory_graph_backend,
            "memory_dir": self.settings.memory_dir,
            "embed_model": self.settings.embed_model,
            "recall_k": self.settings.memory_recall_k,
        }


def init_memory(settings: Any) -> ProjectMemory:
    global _memory
    _memory = ProjectMemory(settings)
    return _memory


def get_memory() -> Optional[ProjectMemory]:
    return _memory