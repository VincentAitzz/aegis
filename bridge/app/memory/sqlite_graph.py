"""Grafo conceptual persistente del proyecto (backend por defecto, stdlib SQLite).

Es la capa 'cerebro' ligera y determinista:

  * nodos = conceptos (tokens frecuentes de cada episodio)
  * aristas = relación `related_to` entre conceptos que aparecieron juntos en un
    mismo episodio (el `run_id` que los descubrió queda registrado en la arista)
  * episodios = metadato completo del run (prompt, resumen, código, error)

No requiere ChromaDB ni red: funciona con el venv del bridge tal cual. Es el
backend que se usa por defecto; el avanzado con extracción LLM es Graphiti
(ver `graphiti.py`), activable con `MEMORY_GRAPH_BACKEND=graphiti`.
"""

import json
import logging
import os
import re
import sqlite3
from typing import Any, Iterable, Optional

log = logging.getLogger("aegis.bridge.memory.graph")

_STOPWORDS = frozenset("""
el la los las un una unos unas del al y o e u a en con para por que como mas no si
es son fue eran lo le se su sus este esta estos estas ese esa eso cuando donde
quien quiero luego despues entre desde hasta sobre contra segun tras cada muy sin
pues bien the and for with from this that these those are was were will have has
had not but its it is of to on at be by an or you as do does did just all any can
could would should which what when where how then than there here like us them
""".split())

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,24}")


def extract_concepts(text: str, limit: int = 8) -> list[str]:
    """Conceptos simples: tokens alfanuméricos frecuentes, sin stopwords."""
    if not text:
        return []
    freq: dict[str, int] = {}
    for w in _TOKEN.findall(text.lower()):
        if w in _STOPWORDS or len(w) < 3:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=lambda w: (-freq[w], w))
    return ranked[:limit]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    concept TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY,
    src INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    dst INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    rel TEXT NOT NULL DEFAULT 'related_to',
    episode_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE TABLE IF NOT EXISTS episodes (
    run_id TEXT PRIMARY KEY,
    agent TEXT,
    outcome TEXT,
    prompt TEXT,
    summary TEXT,
    text TEXT,
    code TEXT,
    error TEXT,
    concepts TEXT,
    created_at TEXT
);
"""


class SQLiteGraph:
    """Grafo conceptual + almacén de episodios persistente en SQLite."""

    def __init__(self, dsn: str, rel: str = "related_to") -> None:
        self._dsn = dsn
        self._rel = rel
        parent = os.path.dirname(dsn)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(dsn)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- escritura ----------------------------------------------------------
    def save_episode(self, episode: dict[str, Any], concepts: list[str]) -> None:
        run_id = episode.get("run_id") or ""
        if not run_id:
            return
        self._conn.execute(
            "INSERT INTO episodes(run_id, agent, outcome, prompt, summary, text, code, error, concepts, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET agent=excluded.agent, outcome=excluded.outcome,"
            " prompt=excluded.prompt, summary=excluded.summary, text=excluded.text, code=excluded.code,"
            " error=excluded.error, concepts=excluded.concepts",
            # `outcome` se corta a 16: es un identificador, y uno que se
            # trunca en silencio se convierte en otro valor sin que nadie lo note
            # (`solo_conversacion` -> `solo_conversacio`). Los nombres de aquí
            # tienen que caber; si no caben, se acortan, no se agranda el corte.
            (run_id, (episode.get("agent") or "")[:64], (episode.get("outcome") or "")[:16],
             (episode.get("prompt") or ""), (episode.get("summary") or ""),
             (episode.get("text") or ""),
             json.dumps(episode.get("code") or [], ensure_ascii=False),
             (episode.get("error") or ""),
             json.dumps(concepts, ensure_ascii=False),
             (episode.get("at") or "")))
        self._link_concepts(run_id, concepts)
        self._conn.commit()

    def _link_concepts(self, run_id: str, concepts: list[str]) -> None:
        concepts = [c for c in dict.fromkeys(concepts) if c]
        if len(concepts) < 2:
            return
        ids: list[int] = []
        for c in concepts:
            self._conn.execute("INSERT OR IGNORE INTO nodes(concept) VALUES(?)", (c,))
            row = self._conn.execute("SELECT id FROM nodes WHERE concept=?", (c,)).fetchone()
            ids.append(row[0])
        seen: set[tuple[int, int]] = set()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = (min(ids[i], ids[j]), max(ids[i], ids[j]))
                if pair in seen:
                    continue
                seen.add(pair)
                self._conn.execute(
                    "INSERT OR IGNORE INTO edges(src, dst, rel, episode_id, created_at)"
                    " VALUES(?,?,?,?,?)",
                    (pair[0], pair[1], self._rel, run_id, run_id))

    # -- lectura ------------------------------------------------------------
    def neighbors(self, concepts: list[str], depth: int = 1, limit: int = 12) -> list[dict[str, Any]]:
        """Conceptos alcanzables desde los dados, agregados por concepto."""
        concepts = [c for c in concepts if c]
        if not concepts:
            return []
        marks = ",".join("?" * len(concepts))
        node_ids = [r[0] for r in self._conn.execute(
            f"SELECT id FROM nodes WHERE concept IN ({marks})", concepts)]
        if not node_ids:
            return []
        visited: set[int] = set(node_ids)
        agg: dict[str, dict[str, Any]] = {}

        def register(dst: int, rel: str, episode_id: str) -> None:
            row = self._conn.execute("SELECT concept FROM nodes WHERE id=?", (dst,)).fetchone()
            if not row:
                return
            node = agg.setdefault(row[0], {"concept": row[0], "runs": set(), "relations": set()})
            if episode_id:
                node["runs"].add(episode_id)
            node["relations"].add(rel)

        frontier = node_ids
        for _ in range(depth):
            nxt: set[int] = set()
            for nid in frontier:
                for dst, rel, ep in self._conn.execute(
                        "SELECT e.dst, e.rel, e.episode_id FROM edges e WHERE e.src=? "
                        "UNION SELECT e.src, e.rel, e.episode_id FROM edges e WHERE e.dst=?",
                        (nid, nid)):
                    register(dst, rel, ep)
                    if dst not in visited:
                        visited.add(dst)
                        nxt.add(dst)
            frontier = list(nxt)
            if not frontier:
                break
        result = [{"concept": v["concept"],
                   "runs": sorted(v["runs"])[:6],
                   "total_runs": len(v["runs"]),
                   "relations": sorted(v["relations"])}
                  for v in agg.values()]
        result.sort(key=lambda n: -n["total_runs"])
        return result[:limit]

    def match_episodes(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Recuperación léxica offline: episodios cuyos conceptos/prompt solapan con la consulta."""
        concepts = extract_concepts(query, limit=6)
        if not concepts:
            return []
        rows = self._conn.execute(
            "SELECT run_id, agent, outcome, prompt, summary, error FROM episodes").fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for run_id, agent, outcome, prompt, summary, error in rows:
            hay = f"{prompt} {summary} {error}".lower()
            score = sum(1 for c in concepts if c in hay)
            if score:
                doc = f"{summary} {error}".strip() or f"run {run_id} ({outcome})"
                scored.append((score, {
                    "run_id": run_id,
                    "agent": agent or "",
                    "outcome": outcome or "",
                    "prompt": (prompt or "")[:200],
                    "document": doc[:600],
                }))
        scored.sort(key=lambda t: -t[0])
        return [{"document": d["document"], "metadata": d, "distance": None}
                for _, d in scored[:limit]]