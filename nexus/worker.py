"""Worker: connects to the server, computes tasks, sends heartbeats. Reconnects forever.
Run: python -m nexus.worker --url ws://localhost:8000/ws/worker --name w1"""
import argparse
import asyncio
import json
import os
import platform
import random
import time
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


def describe(m: dict) -> tuple[str, dict]:
    """Human label for a task message and its tile info (for the log and the desktop window)."""
    p = m["params"]
    if m["type"] == "mandelbrot":
        n = p.get("n", m["task_id"])
        return f"tile #{n} (Row {p['ty'] + 1}, Col {p['tx'] + 1})", {"n": n, "row": p["ty"] + 1, "col": p["tx"] + 1}
    return f"{m['type']} {p.get('name', m['task_id'])}", {}


async def run_session(url: str, wid: str, name: str, delay: float, log, key: str = "", stats: dict | None = None):
    """One connection. `stats` is a plain dict the desktop window polls (state, done, task, preview, ...)."""
    stats = stats if stats is not None else {}
    headers = {"X-API-Key": key} if key else None
    async with websockets.connect(url, max_size=2**24, ping_interval=None, additional_headers=headers) as ws:
        await ws.send(json.dumps({"t": "hello", "worker_id": wid, "name": name, "cpus": os.cpu_count() or 1}))
        welcome = json.loads(await ws.recv())
        log(f"worker {name} connected to cluster", "ok")
        stats.update(state="online", task=None, wid=wid, since=time.time(), attempt=0)

        async def beat():
            n = 0
            while True:
                stats["metrics"] = sensors()
                await ws.send(json.dumps({"t": "heartbeat", "metrics": stats["metrics"]}))
                n += 1
                if n % 30 == 0:
                    log("heartbeat acknowledged", "hb")
                await asyncio.sleep(1)

        hb = asyncio.create_task(beat())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m["t"] != "task":
                    continue
                label, info = describe(m)
                t0 = time.monotonic()
                stats["task"] = {"id": m["task_id"], "type": m["type"], "label": label, "started": time.time(),
                                 "est_ms": stats.get("avg_ms") or 400, **info}
                log(f"{label} started", "info")
                try:
                    h = HANDLERS[m["type"]]
                    res = await asyncio.to_thread(h.compute, m["params"])      # heartbeats keep flowing
                    if delay:
                        await asyncio.sleep(delay)
                    await ws.send(h.pack(m["task_id"], res))
                    ms = round((time.monotonic() - t0) * 1000)
                    stats["done"] = stats.get("done", 0) + 1
                    stats["total_ms"] = stats.get("total_ms", 0) + ms
                    stats["avg_ms"] = round(stats["total_ms"] / stats["done"])
                    if hasattr(h, "preview"):
                        stats["preview"] = h.preview(res, m["params"])
                    log(f"completed {label} in {ms}ms", "ok")
                except Exception as e:
                    stats["failed"] = stats.get("failed", 0) + 1
                    log(f"{label} failed: {e}", "err")
                    await ws.send(json.dumps({"t": "error", "task_id": m["task_id"], "msg": str(e)}))
                stats["task"] = None
        finally:
            stats["task"] = None
            hb.cancel()


async def main_async(url, name, wid, delay, log=lambda s, k=None: print(s, flush=True), key="", stats=None):
    """Connect and reconnect forever (unless stats['auto_reconnect'] is set to False)."""
    stats = stats if stats is not None else {}
    backoff, attempt = 1.0, 0
    stats.update(state="connecting", attempt=0)
    while True:
        try:
            await run_session(url, wid, name, delay, log, key, stats)
            backoff, attempt = 1.0, 0
            log("connection closed by server", "warn")
        except (OSError, websockets.WebSocketException) as e:
            rejected = isinstance(e, websockets.InvalidStatus) and e.response.status_code in (401, 403)
            attempt += 1
            if rejected:
                log("server rejected the connection: invalid API key", "err")
                stats.update(state="rejected", error="AUTH_401")
                return
            log(f"connection lost ({type(e).__name__}); retry in {backoff:.0f}s", "warn")
        if not stats.get("auto_reconnect", True):
            stats["state"] = "offline"
            return
        stats.update(state="reconnecting", attempt=attempt, retry_in=round(backoff))
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
    log = lambda s, k=None: print(f"[{a.name}] {s}", flush=True)
    try:
        asyncio.run(main_async(to_ws(a.url), a.name, a.id or uuid.uuid4().hex[:8], a.delay, log, a.key))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
