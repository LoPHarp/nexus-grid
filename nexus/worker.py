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

from .protocol import pack_result
from .tasks import HANDLERS


def sensors() -> dict:
    m = {"cpu": psutil.cpu_percent(None), "mem": psutil.virtual_memory().percent}
    try:
        temps = [t.current for lst in psutil.sensors_temperatures().values() for t in lst]
        if temps:
            m["temp"] = round(max(temps), 1)
    except (AttributeError, OSError):
        pass
    return m


async def run_session(url: str, wid: str, name: str, delay: float, log):
    async with websockets.connect(url, max_size=2**24, ping_interval=None) as ws:
        await ws.send(json.dumps({"t": "hello", "worker_id": wid, "name": name, "cpus": os.cpu_count() or 1}))
        welcome = json.loads(await ws.recv())
        log(f"connected, server heartbeat timeout {welcome.get('heartbeat_timeout')}s")

        async def beat():
            while True:
                await ws.send(json.dumps({"t": "heartbeat", "metrics": sensors()}))
                await asyncio.sleep(1)

        hb = asyncio.create_task(beat())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m["t"] != "task":
                    continue
                try:
                    h = HANDLERS[m["type"]]
                    arr = await asyncio.to_thread(h.compute, m["params"])   # heartbeats keep flowing
                    if delay:
                        await asyncio.sleep(delay)
                    await ws.send(pack_result(m["task_id"], arr))
                except Exception as e:
                    await ws.send(json.dumps({"t": "error", "task_id": m["task_id"], "msg": str(e)}))
        finally:
            hb.cancel()


async def main_async(url, name, wid, delay, log=print):
    backoff = 1.0
    while True:
        try:
            await run_session(url, wid, name, delay, log)
            backoff = 1.0
        except (OSError, websockets.WebSocketException) as e:
            log(f"connection lost ({type(e).__name__}); retry in {backoff:.0f}s")
        await asyncio.sleep(backoff + random.random())
        backoff = min(backoff * 2, 30)    # a sleeping Render instance needs up to ~1 minute to wake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("NEXUS_URL", "ws://localhost:8000/ws/worker"))
    ap.add_argument("--name", default=platform.node())
    ap.add_argument("--id", default=None, help="stable worker id (default: random per start)")
    ap.add_argument("--delay", type=float, default=float(os.environ.get("WORKER_DELAY", "0")),
                    help="artificial extra seconds per task (demo/tests)")
    a = ap.parse_args()
    psutil.cpu_percent(None)
    log = lambda s: print(f"[{a.name}] {s}", flush=True)
    try:
        asyncio.run(main_async(a.url, a.name, a.id or uuid.uuid4().hex[:8], a.delay, log))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
