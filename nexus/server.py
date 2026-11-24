"""FastAPI app: REST API, worker WebSocket, event WebSocket. Run: uvicorn nexus.server:app"""
import asyncio
import collections
import io
import json
import os
import secrets
import time
import zipfile
from contextlib import asynccontextmanager

import subprocess
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .db import DB
from . import ai
from .protocol import frame_payload, frame_task_id
from .scheduler import Scheduler
from .tasks import image

START = time.time()
STARS = ["Atlas", "Nova", "Orion", "Vega", "Lyra", "Draco", "Cygnus", "Pyxis"]
DESCRIPTION = """Distributed computing server: jobs are split into tasks, handed to connected workers, results are collected.

**Access key.** If the server runs with `NEXUS_API_KEY`, endpoints that change state (`POST/DELETE /api/jobs`)
and the worker WebSocket require the header `X-API-Key`. Read-only endpoints, `/ws/events` and Demo Mode stay open.
Click *Authorize* to try protected calls here. WebSocket protocols are described in `docs/API.md`."""
key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Required when the server sets NEXUS_API_KEY")


class JobCreate(BaseModel):
    type: str = Field("mandelbrot", description="Task type: `mandelbrot`")
    params: dict = Field(default_factory=dict, description="Type-specific parameters (see docs/API.md)")
    priority: int = Field(0, description="Higher runs first")
    model_config = {"json_schema_extra": {"examples": [
        {"type": "mandelbrot", "params": {"width": 800, "height": 600, "tile": 100, "max_iter": 200}, "priority": 0}]}}


class Job(BaseModel):
    id: int
    type: str
    params: dict
    priority: int
    state: str = Field(description="running | done | failed | aborted")
    total: int = Field(description="number of tasks (tiles)")
    done: int
    created: float
    finished: float | None = None
    error: str | None = None


def create_app(db_path: str | None = None, heartbeat_timeout: float | None = None,
               api_key: str | None = None) -> FastAPI:
    api_key = os.environ.get("NEXUS_API_KEY", "") if api_key is None else api_key
    history: collections.deque = collections.deque(maxlen=3600)    # one point per second, last hour
    last_demo = [0.0]

    def require_key(k: str | None = Depends(key_header)):
        if api_key and not secrets.compare_digest((k or "").encode(), api_key.encode()):
            raise HTTPException(401, "missing or invalid X-API-Key")
    db_path = db_path or os.environ.get("NEXUS_DB", "nexus.db")
    timeout = heartbeat_timeout or float(os.environ.get("HEARTBEAT_TIMEOUT", "5"))
    subscribers: set[asyncio.Queue] = set()

    recent: collections.deque = collections.deque(maxlen=30)       # short event summaries for Ask the cluster

    def emit(event: dict):
        e = event.get("e")
        if e in ("worker_joined", "worker_lost", "job_created", "job_done", "job_failed", "worker_removed"):
            who = (event.get("worker") or {}).get("name") or event.get("worker_id") or (event.get("job") or {}).get("id", "")
            recent.append(f"{time.strftime('%H:%M:%S')} {e} {who}" + (f" ({event.get('reason')})" if event.get("reason") else ""))
        for q in list(subscribers):
            if q.qsize() > 1000:               # slow consumer: drop it rather than grow memory
                subscribers.discard(q)
            else:
                q.put_nowait(event)

    sched = Scheduler(DB(db_path), timeout, emit)
    advisor = ai.from_env(lambda: ai.snapshot(sched, recent))
    last_ask: collections.deque = collections.deque(maxlen=30)

    async def reaper():
        n = 0
        while True:
            await asyncio.sleep(0.5)
            sched.reap()
            n += 1
            if n % 2 == 0:
                history.append(sched.sample())

    demo_procs: dict[str, subprocess.Popen] = {}     # workers spawned by Demo Mode, by worker id

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(reaper())
        yield
        task.cancel()
        for p in demo_procs.values():
            p.kill()

    app = FastAPI(title="Nexus Grid API", version="0.3.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.sched = sched
    # the desktop client loads the page from local files and calls this API cross-origin; auth is a header, not a cookie
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Disposition"])

    # ---- REST ----
    @app.get("/api/health", tags=["system"], summary="Liveness check")
    async def health():
        alive = sum(1 for w in sched.workers.values() if w.alive)
        return {"status": "ok", "uptime_s": round(time.time() - START, 1), "workers_alive": alive}

    @app.post("/api/jobs", status_code=201, response_model=Job, tags=["jobs"], summary="Submit a job",
              dependencies=[Depends(require_key)])
    async def create_job(body: JobCreate):
        try:
            return sched.submit(body.type, body.params, body.priority)
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e))

    @app.get("/api/jobs", response_model=list[Job], tags=["jobs"], summary="List jobs, newest first")
    async def list_jobs(limit: int = 100):
        return [sched.job_public(sched.jobs[j["id"]]) if j["id"] in sched.jobs else j
                for j in sched.db.list_jobs(limit)]

    @app.get("/api/jobs/{jid}", response_model=Job, tags=["jobs"], summary="Get one job")
    async def get_job(jid: int):
        j = sched.jobs.get(jid)
        j = sched.job_public(j) if j else sched.db.get_job(jid)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.delete("/api/jobs/{jid}", tags=["jobs"], summary="Cancel and delete a job", dependencies=[Depends(require_key)])
    async def delete_job(jid: int):
        if not sched.cancel(jid):
            raise HTTPException(404, "job not found")
        return {"deleted": jid}

    @app.get("/api/jobs/{jid}/tiles", tags=["jobs"])
    async def job_tiles(jid: int):
        """Finished tiles of a job: task id, tile coordinates, worker."""
        j = sched.jobs.get(jid)
        if not j:
            raise HTTPException(404, "job not found (results are kept in memory only)")
        return [{"task_id": t, "tx": sched.tasks[t].params.get("tx", sched.tasks[t].params.get("index", 0)),
                 "ty": sched.tasks[t].params.get("ty", 0), "worker_id": sched.tasks[t].worker_id}
                for t in j["task_ids"] if sched.tasks[t].state == "done"]

    @app.get("/api/tiles/{task_id}", response_class=Response, tags=["jobs"])
    async def tile(task_id: int):
        """One tile as the binary result frame (format in docs/ARCHITECTURE.md)."""
        t = sched.tasks.get(task_id)
        if not t or t.result is None:
            raise HTTPException(404, "tile not available")
        return Response(t.result, media_type="application/octet-stream")

    @app.get("/api/tasks/{task_id}/result", response_class=Response, tags=["jobs"],
             summary="Processed file of an image task")
    async def task_result(task_id: int):
        t = sched.tasks.get(task_id)
        if not t or t.result is None or t.type != "image":
            raise HTTPException(404, "no file result for this task")
        return Response(frame_payload(t.result), media_type=image.media_type(t.params),
                        headers={"Content-Disposition": f'attachment; filename="{image.output_name(t.params)}"'})

    @app.get("/api/jobs/{jid}/download", response_class=Response, tags=["jobs"],
             summary="Zip of all finished files of an image job")
    async def job_download(jid: int):
        j = sched.jobs.get(jid)
        if not j or j["type"] != "image":
            raise HTTPException(404, "image job not found (results are kept in memory only)")
        done = [sched.tasks[t] for t in j["task_ids"] if sched.tasks[t].state == "done"]
        if not done:
            raise HTTPException(409, "no finished files yet")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:      # images are already compressed
            for t in done:
                z.writestr(image.output_name(t.params), frame_payload(t.result))
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="job{jid}.zip"'})

    @app.get("/api/workers", tags=["workers"], summary="Connected and recently lost workers")
    async def workers():
        return [w.public() for w in sched.workers.values()]

    @app.get("/api/metrics", tags=["metrics"], summary="Current cluster metrics")
    async def metrics():
        ws = list(sched.workers.values())
        return {"workers_alive": sum(w.alive for w in ws), "workers_total": len(ws),
                "queue_depth": sched.queue_depth(), "tasks_per_s": round(sched.throughput(), 2),
                "jobs_running": sum(1 for j in sched.jobs.values() if j["state"] == "running"),
                "jobs_done": sched.db.count_done()}

    @app.get("/api/metrics/history", tags=["metrics"], summary="Per-second metrics history")
    async def metrics_history(seconds: int = 300):
        """Points from the last `seconds` (max 3600): queue depth, tasks/s and per-worker cpu, temp (or memory %), throughput, latency."""
        cut = time.time() - min(max(seconds, 1), 3600)
        return [p for p in history if p["t"] >= cut]

    class Ask(BaseModel):
        question: str = Field(..., max_length=ai.MAX_Q, examples=ai.SUGGESTIONS[:1])

    @app.post("/api/ask", tags=["ai"], summary="Ask a question about the cluster")
    async def ask(body: Ask):
        """Answer from cache, a free model (if configured), recorded answers, or rules; `source` says which.
        Limited to 30 questions per minute."""
        now = time.monotonic()
        while last_ask and now - last_ask[0] > 60:
            last_ask.popleft()
        if len(last_ask) >= 30:
            raise HTTPException(429, "too many questions, try again in a minute")
        last_ask.append(now)
        if not body.question.strip():
            raise HTTPException(422, "empty question")
        return await asyncio.to_thread(advisor.ask, body.question)

    @app.get("/api/ask/suggestions", tags=["ai"], summary="Example questions")
    async def ask_suggestions():
        return ai.SUGGESTIONS

    # ---- Demo Mode (local workers started by the server, for a one-click demonstration) ----
    @app.post("/api/demo", tags=["demo"])
    async def demo(request: Request, workers: int = 4):
        """Start up to `workers` local demo workers (max 8) and submit a Mandelbrot job."""
        if time.monotonic() - last_demo[0] < 3:
            raise HTTPException(429, "demo was started a moment ago")
        last_demo[0] = time.monotonic()
        port = os.environ.get("PORT") or request.url.port or 8000
        for wid, p in list(demo_procs.items()):
            if p.poll() is not None:
                del demo_procs[wid]
        for i in range(1, min(max(workers, 1), 8) + 1):
            wid = f"demo{i}"
            label = f"{STARS[(i - 1) % len(STARS)]}-{i:02d}"
            sched.demo_ids.add(wid)
            if wid not in demo_procs:
                demo_procs[wid] = subprocess.Popen(
                    [sys.executable, "-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker",
                     "--name", label, "--id", wid, "--delay", "0.3"], stdout=subprocess.DEVNULL)
        job = sched.submit("mandelbrot", {"width": 640, "height": 480, "tile": 40, "max_iter": 200,
                                          "cx": -0.7436, "cy": 0.1318, "view_w": 0.02})
        return {"workers": sorted(demo_procs), "job": job}

    @app.post("/api/workers/{wid}/kill", tags=["demo"])
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
        if api_key and not secrets.compare_digest(ws.headers.get("x-api-key", "").encode(), api_key.encode()):
            await ws.close(1008)                      # rejected during the handshake (HTTP 403)
            return
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
                    task_id = frame_task_id(msg["bytes"])
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

    @app.middleware("http")
    async def revalidate_static(request: Request, call_next):
        r = await call_next(request)
        if not request.url.path.startswith("/api"):
            r.headers["Cache-Control"] = "no-cache"          # always revalidate: HTML, CSS and JS must come from the same deploy
        return r

    web = Path(__file__).resolve().parent.parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")   # must stay last
    return app


app = create_app()
