"""Worker: connects to the server, computes tasks, sends heartbeats. Reconnects forever.
Run: python -m nexus.worker --url ws://localhost:8000/ws/worker --name w1"""
import argparse
import asyncio
import json
import os
import platform
import random
import uuid

import psutil
import websockets

from .tasks import HANDLERS


def to_ws(url: str) -> str:
    url = url.strip().rstrip("/")
    for a, b in (("https://", "wss://"), ("http://", "ws://")):
        if url.startswith(a):
            url = b + url[len(a):]
    if not url.startswith(("ws://", "wss://")):
        url = "wss://" + url
    return url if url.endswith("/ws/worker") else url + "/ws/worker"


def sensors() -> dict:
    m = {"cpu": psutil.cpu_percent(None), "mem": psutil.virtual_memory().percent}
    try:
        temps = [t.current for lst in psutil.sensors_temperatures().values() for t in lst]
        if temps:
            m["temp"] = round(max(temps), 1)
    except (AttributeError, OSError):
        pass
    return m


async def run_session(url: str, wid: str, name: str, delay: float, log, key: str = "", stats: dict | None = None):
    stats = stats if stats is not None else {}
    headers = {"X-API-Key": key} if key else None
    async with websockets.connect(url, max_size=2**24, ping_interval=None, additional_headers=headers) as ws:
        await ws.send(json.dumps({"t": "hello", "worker_id": wid, "name": name, "cpus": os.cpu_count() or 1}))
        welcome = json.loads(await ws.recv())
        log(f"connected, server heartbeat timeout {welcome.get('heartbeat_timeout')}s")
        stats.update(state="connected", task="")

        async def beat():
            while True:
                stats["metrics"] = sensors()
                await ws.send(json.dumps({"t": "heartbeat", "metrics": stats["metrics"]}))
                await asyncio.sleep(1)

        hb = asyncio.create_task(beat())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m["t"] != "task":
                    continue
                try:
                    stats["task"] = f"{m['type']} #{m['task_id']}"
                    h = HANDLERS[m["type"]]
                    arr = await asyncio.to_thread(h.compute, m["params"])   # heartbeats keep flowing
                    if delay:
                        await asyncio.sleep(delay)
                    await ws.send(h.pack(m["task_id"], arr))
                    stats["done"] = stats.get("done", 0) + 1
                except Exception as e:
                    stats["failed"] = stats.get("failed", 0) + 1
                    await ws.send(json.dumps({"t": "error", "task_id": m["task_id"], "msg": str(e)}))
        finally:
            stats["task"] = ""
            hb.cancel()


async def main_async(url, name, wid, delay, log=print, key="", stats=None):
    stats = stats if stats is not None else {}
    backoff = 1.0
    while True:
        try:
            await run_session(url, wid, name, delay, log, key, stats)
            backoff = 1.0
        except (OSError, websockets.WebSocketException) as e:
            rejected = isinstance(e, websockets.InvalidStatus) and e.response.status_code in (401, 403)
            log("server rejected the connection: check the access key" if rejected
                else f"connection lost ({type(e).__name__}); retry in {backoff:.0f}s")
            stats.update(state="rejected (bad key?)" if rejected else f"reconnecting in {backoff:.0f}s")
        await asyncio.sleep(backoff + random.random())
        backoff = min(backoff * 2, 30)    # a sleeping Render instance needs up to ~1 minute to wake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("NEXUS_URL", "ws://localhost:8000"),
                    help="server address, http(s):// or ws(s)://; /ws/worker is added if missing")
    ap.add_argument("--name", default=platform.node())
    ap.add_argument("--key", default=os.environ.get("NEXUS_API_KEY", ""), help="server access key (X-API-Key)")
    ap.add_argument("--id", default=None, help="stable worker id (default: random per start)")
    ap.add_argument("--delay", type=float, default=float(os.environ.get("WORKER_DELAY", "0")),
                    help="artificial extra seconds per task (demo/tests)")
    a = ap.parse_args()
    psutil.cpu_percent(None)
    log = lambda s: print(f"[{a.name}] {s}", flush=True)
    try:
        asyncio.run(main_async(to_ws(a.url), a.name, a.id or uuid.uuid4().hex[:8], a.delay, log, a.key))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
