"""FastAPI app: REST API, worker WebSocket, event WebSocket. Run: uvicorn nexus.server:app"""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import subprocess
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .db import DB
from .scheduler import Scheduler

START = time.time()


def create_app(db_path: str | None = None, heartbeat_timeout: float | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("NEXUS_DB", "nexus.db")
    timeout = heartbeat_timeout or float(os.environ.get("HEARTBEAT_TIMEOUT", "5"))
    subscribers: set[asyncio.Queue] = set()

    def emit(event: dict):
        for q in list(subscribers):
            if q.qsize() > 1000:               # slow consumer: drop it rather than grow memory
                subscribers.discard(q)
            else:
                q.put_nowait(event)

    sched = Scheduler(DB(db_path), timeout, emit)

    async def reaper():
        while True:
            await asyncio.sleep(0.5)
            sched.reap()

    demo_procs: dict[str, subprocess.Popen] = {}     # workers spawned by Demo Mode, by worker id

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(reaper())
        yield
        task.cancel()
        for p in demo_procs.values():
            p.kill()

    app = FastAPI(title="Nexus Grid", version="0.1.0", lifespan=lifespan)
    app.state.sched = sched

    # ---- REST ----
    @app.get("/api/health")
    async def health():
        alive = sum(1 for w in sched.workers.values() if w.alive)
        return {"status": "ok", "uptime_s": round(time.time() - START, 1), "workers_alive": alive}

    @app.post("/api/jobs", status_code=201)
    async def create_job(body: dict = Body(..., examples=[{"type": "mandelbrot", "params": {"width": 800, "height": 600}}])):
        try:
            return sched.submit(body.get("type", "mandelbrot"), body.get("params", {}), int(body.get("priority", 0)))
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e))

    @app.get("/api/jobs")
    async def list_jobs(limit: int = 100):
        return [sched.job_public(sched.jobs[j["id"]]) if j["id"] in sched.jobs else j
                for j in sched.db.list_jobs(limit)]

    @app.get("/api/jobs/{jid}")
    async def get_job(jid: int):
        j = sched.jobs.get(jid)
        j = sched.job_public(j) if j else sched.db.get_job(jid)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.delete("/api/jobs/{jid}")
    async def delete_job(jid: int):
        if not sched.cancel(jid):
            raise HTTPException(404, "job not found")
        return {"deleted": jid}

    @app.get("/api/jobs/{jid}/tiles")
    async def job_tiles(jid: int):
        """Finished tiles of a job: task id, tile coordinates, worker."""
        j = sched.jobs.get(jid)
        if not j:
            raise HTTPException(404, "job not found (results are kept in memory only)")
        return [{"task_id": t, "tx": sched.tasks[t].params["tx"], "ty": sched.tasks[t].params["ty"],
                 "px": sched.tasks[t].params["px"], "py": sched.tasks[t].params["py"],
                 "worker_id": sched.tasks[t].worker_id}
                for t in j["task_ids"] if sched.tasks[t].state == "done"]

    @app.get("/api/tiles/{task_id}", response_class=Response)
    async def tile(task_id: int):
        """One tile as the binary result frame (format in docs/ARCHITECTURE.md)."""
        t = sched.tasks.get(task_id)
        if not t or t.result is None:
            raise HTTPException(404, "tile not available")
        return Response(t.result, media_type="application/octet-stream")

    @app.get("/api/workers")
    async def workers():
        return [w.public() for w in sched.workers.values()]

    @app.get("/api/metrics")
    async def metrics():
        ws = list(sched.workers.values())
        return {"workers_alive": sum(w.alive for w in ws), "workers_total": len(ws),
                "queue_depth": sched.queue_depth(), "tasks_per_s": round(sched.throughput(), 2),
                "jobs_running": sum(1 for j in sched.jobs.values() if j["state"] == "running")}

    # ---- Demo Mode (local workers started by the server, for a one-click demonstration) ----
    @app.post("/api/demo")
    async def demo(request: Request, workers: int = 4):
        """Start up to `workers` local demo workers (max 8) and submit a Mandelbrot job."""
        port = os.environ.get("PORT") or request.url.port or 8000
        for wid, p in list(demo_procs.items()):
            if p.poll() is not None:
                del demo_procs[wid]
        for i in range(1, min(max(workers, 1), 8) + 1):
            wid = f"demo{i}"
            if wid not in demo_procs:
                demo_procs[wid] = subprocess.Popen(
                    [sys.executable, "-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker",
                     "--name", wid, "--id", wid, "--delay", "0.3"], stdout=subprocess.DEVNULL)
        job = sched.submit("mandelbrot", {"width": 640, "height": 480, "tile": 40, "max_iter": 200,
                                          "cx": -0.7436, "cy": 0.1318, "view_w": 0.02})
        return {"workers": sorted(demo_procs), "job": job}

    @app.post("/api/workers/{wid}/kill")
    async def kill_worker(wid: str):
        """Kill a Demo Mode worker process (to show failover). Only workers started by /api/demo."""
        p = demo_procs.get(wid)
        if not p or p.poll() is not None:
            raise HTTPException(404, "not a running demo worker")
        p.kill()
        return {"killed": wid}

    # ---- WebSockets ----
    @app.websocket("/ws/worker")
    async def ws_worker(ws: WebSocket):
        await ws.accept()
        w = None
        try:
            hello = json.loads(await ws.receive_text())
            if hello.get("t") != "hello":
                await ws.close(1002)
                return
            w = sched.worker_hello(str(hello["worker_id"]), str(hello.get("name", "worker")),
                                   int(hello.get("cpus", 1)), lambda m: ws.send_text(json.dumps(m)))
            await ws.send_text(json.dumps({"t": "welcome", "heartbeat_timeout": timeout}))
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    from .protocol import unpack_result
                    task_id, _ = unpack_result(msg["bytes"])
                    sched.task_done(w, task_id, msg["bytes"])
                else:
                    m = json.loads(msg["text"])
                    if m["t"] == "heartbeat":
                        sched.heartbeat(w, m.get("metrics", {}))
                    elif m["t"] == "error":
                        sched.task_error(w, int(m["task_id"]), str(m.get("msg", "")))
        except (WebSocketDisconnect, RuntimeError, ValueError, KeyError):
            pass
        finally:
            if w and sched.workers.get(w.id) is w:
                sched.worker_lost(w.id, "disconnected")

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        subscribers.add(q)
        try:
            await ws.send_text(json.dumps({"e": "snapshot", "workers": [w.public() for w in sched.workers.values()],
                                           "jobs": [sched.job_public(j) for j in sched.jobs.values()]}))
            while True:
                await ws.send_text(json.dumps(await q.get()))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            subscribers.discard(q)

    web = Path(__file__).resolve().parent.parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")   # must stay last
    return app


app = create_app()
