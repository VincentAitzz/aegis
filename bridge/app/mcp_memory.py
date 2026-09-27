"""Servidor MCP (fase 2) — memoria del proyecto consultable por el agente.

Expone la 'cerebro' de Aegis como tools MCP sobre stdio, para que el propio
agente de Hermes consulte experiencias previas / conceptos conectados dentro de
un run (además de la inyección automática en `POST /tasks`).

Ejecución (requisito: `pip install mcp`):
    cd bridge
    PYTHONPATH=app .venv/bin/python -m app.mcp_memory

Registro en ~/.hermes/config.yaml (mcp.servers.aegis-memory) o vía
`hermes mcp add` — ver docs/runbook.md.
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _bootstrap() -> None:
    from .config import get_settings
    from .memory import init_memory
    init_memory(get_settings())


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # noqa: BLE001
        print(f"mcp no instalado ({exc}); ejecuta: .venv/bin/pip install mcp",
              file=sys.stderr)
        sys.exit(2)

    _bootstrap()
    mcp = FastMCP("aegis-memory")

    @mcp.tool()
    async def memory_search(query: str, k: int = 3) -> str:
        """Busca en la memoria del proyecto (Episodios resueltos + conceptos conectados)."""
        from .memory import get_memory
        mem = get_memory()
        if not mem:
            return "memoria no inicializada"
        results = await mem.recall(query, k)
        return mem.render_context(results, max_chars=4000) or "sin episodios previos relevantes"

    @mcp.tool()
    async def memory_status() -> str:
        """Estado de los almacenes de memoria (episódica, grafo, directorio)."""
        from .memory import get_memory
        mem = get_memory()
        return f"memoria: {mem.status()}" if mem else "memoria desactivada"

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()