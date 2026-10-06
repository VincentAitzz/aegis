"""El health check de la gateway de Hermes. Nada más.

## Por qué este módulo es una sonda y no un cliente
Hasta el 2026-10-04 fue un cliente completo: `create_run`, `run_status`,
`approve`, `steer`, `stop` y el consumidor SSE. Eso era el segundo motor de
tools, y `docs/motores.md` §6 lo prohíbe explícitamente: **dos motores con
tools son dos sitios donde puede vivir un guardarraíl**. Cuando el autopilot
pasó a ser el único que ejecuta tools (`2f1fccb`), nadie initió ya un run de
Hermes: `data/logs/runs/` tiene 84 ficheros `run_*.jsonl` que paran el 3-oct y
133 `autopilot-*.jsonl` que siguen. Las seis métodos se quedaron sin un solo
llamador y `docs/architecture.md` las seguía documentando como API viva.

Lo que **sí** queda vivo es una cosa: `GET /health` pregunta a la gateway si
está en pie (`main.py`), y el watchdog de `infra/stack.sh` espera esa misma
respuesta con 90 s de margen. Eso no es un motor, es un semáforo, y por eso se
queda.

## Por qué el cliente se puede reabrir
`hermes` es un **singleton a nivel de módulo**, así que un `aclose()` lo dejaba
muerto para el resto del proceso. En producción parece que no importa —uvicorn
apaga y el proceso se va— pero el apagado también ocurre en los tests, y ahí la
consecuencia era esta: al no poder usar `with TestClient(app)` (el `with`
dispara el lifespan, que cerraba el cliente), **el lifespan no llegaba a
ejecutarse**, así que `init_memory`, `init_autonia` e `init_agenda` no corrían en
ningún test HTTP. La propiedad que se quiere: **cerrar no es irreversible**.

## Por qué el `read` del timeout es 5 s y no `None`
Era `read=None`, o sea "esperar lo que haga falta". En `/health` eso se traducía
en que la respuesta tardaba lo que tardase la gateway —y como el LED de la app lo
consulta cada 1,2 s, una gateway colgada convertía eso en una avalancha de
conexiones abiertas contra un servicio que no iba a responder nunca. Un health
check que no puede fallar rápido no es un health check.

Cuando este módulo se redujo (Fase 1) quedaban dos `read=None` mas en el
repo, y los dos eran riesgo de disponibilidad real, no comodidad:

- `llm.embed_texts`, que se awaita al **empezar y al terminar cada run**. Con
  `read=None`, un `/api/embed` que acepta la conexión y no contestaba colgaba el
  run sin límite y sin motivo que lo explicara. Arreglado en `llm.py` con un tope
  explícito.
- `llm.ensure_model`, que además era código muerto: su único llamador era
  `_submit_task`, que se fue con el motor de Hermes. Se borró en vez de arreglarse.
"""
import logging
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("aegis.bridge.hermes")

#: Un health check que tarda más que esto no está vivo, está colgado.
HEALTH_TIMEOUT_S = 5.0


class HermesClient:
    """Sonda de vida de la gateway. No crea runs, no los gobierna."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._cerrado = False
        self._http = self._nuevo()

    def _nuevo(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=HEALTH_TIMEOUT_S,
                                  write=2.0, pool=2.0))

    @property
    def _client(self) -> httpx.AsyncClient:
        """El cliente de HTTP, o uno nuevo si estaba cerrado. Ver el docstring."""
        if self._cerrado:
            self._cerrado = False
            self._http = self._nuevo()
        return self._http

    @property
    def cerrado(self) -> bool:
        return self._cerrado

    async def aclose(self) -> None:
        if self._cerrado:
            return
        await self._http.aclose()
        self._cerrado = True

    async def health(self) -> dict[str, Any]:
        """¿Está la gateway en pie? Nunca lanza: un semáforo roto no apaga el panel."""
        try:
            r = await self._client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}


hermes = HermesClient(get_settings().hermes_base_url, get_settings().hermes_api_key)