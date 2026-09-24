"""Cliente HTTP hacia el API server de Hermes (REST) y consumidor SSE."""

import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx

from .config import get_settings

log = logging.getLogger("aegis.bridge.hermes")


class HermesClient:
    """Envoltorio fino del API server de Hermes."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=None))

    # -- control ------------------------------------------------------------
    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        try:
            r = await self._client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

    async def create_run(self, model: str, prompt: str,
                         instructions: Optional[str] = None,
                         session_id: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {"input": prompt, "model": model}
        if instructions:
            body["instructions"] = instructions
        if session_id:
            body["session_id"] = session_id
        r = await self._client.post(f"{self.base_url}/v1/runs",
                                    headers=self.headers, json=body)
        r.raise_for_status()
        return r.json()

    async def run_status(self, run_id: str) -> dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/v1/runs/{run_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    async def approve(self, run_id: str, decision: str, comment: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"decision": decision}
        if comment:
            payload["comment"] = comment
        r = await self._client.post(f"{self.base_url}/v1/runs/{run_id}/approval",
                                    headers=self.headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def steer(self, run_id: str, text: str) -> dict[str, Any]:
        r = await self._client.post(f"{self.base_url}/v1/runs/{run_id}/steer",
                                    headers=self.headers, json={"text": text})
        r.raise_for_status()
        return r.json()

    async def stop(self, run_id: str) -> dict[str, Any]:
        r = await self._client.post(f"{self.base_url}/v1/runs/{run_id}/stop",
                                    headers=self.headers)
        r.raise_for_status()
        return r.json()

    # -- streaming SSE --------------------------------------------------------
    async def run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Itera sobre los eventos SSE de un run (tool.started/completed, run.* etc.).

        Cada ítem: {"event": <name>, "data": <parsed-json>}. El [DONE] cierra el stream.
        """
        url = f"{self.base_url}/v1/runs/{run_id}/events"
        async with self._client.stream("GET", url, headers=self.headers) as resp:
            resp.raise_for_status()
            event = "message"
            data_buf: list[str] = []
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith(":"):  # keepalive SSE
                    continue
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[len("data:"):].strip())
                    # 'data: [DONE]' cierra el stream
                    if data_buf and data_buf[0] == "[DONE]":
                        break
                # bloques terminados por línea en blanco: el parser es tolerante
                if data_buf and (not line.startswith(("event:", "data:")) or line.endswith("}")):
                    payload = "".join(data_buf)
                    data_buf = []
                    try:
                        yield {"event": event, "data": json.loads(payload)}
                    except json.JSONDecodeError:
                        yield {"event": event, "data": {"raw": payload}}


hermes = HermesClient(get_settings().hermes_base_url, get_settings().hermes_api_key)