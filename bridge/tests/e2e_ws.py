#!/usr/bin/env python3
"""Prueba E2E del bridge: crear tarea por REST y recibir eventos por WS."""
import asyncio
import json
import sys

import httpx
import websockets

BRIDGE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
PROMPT = sys.argv[1] if len(sys.argv) > 1 else "Ejecuta echo hola-aegis con tu terminal y responde en una frase corta."
AGENT = sys.argv[2] if len(sys.argv) > 2 else "worker"


async def main() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(240)) as c:
        r = await c.post(f"{BRIDGE}/tasks", json={"agent": AGENT, "prompt": PROMPT})
        r.raise_for_status()
        task = r.json()
    run_id = task["run_id"]
    print(f"[+] tarea creada run_id={run_id} agent={task['agent']} status={task['status']}")

    events = []
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"type": "subscribe", "run_id": run_id}))
        try:
            async with asyncio.timeout(180):
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=200)
                    ev = json.loads(raw)
                    events.append(ev)
                    print(f"[evt] {ev['type']:<16} agent={ev['agent']:<12} {json.dumps(ev['payload'])[:80]}")
                    if ev["type"] in ("task.done", "task.failed", "task.stopped"):
                        break
        except asyncio.TimeoutError:
            print("(!) timeout aguardando eventos")

    print(f"\n[=] {len(events)} eventos recibidos; tipos: {sorted({e['type'] for e in events})}")


if __name__ == "__main__":
    asyncio.run(main())