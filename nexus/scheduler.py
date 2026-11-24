"""Job queue, worker registry, heartbeat and reassignment. Runs on one asyncio loop (no locks)."""
import asyncio
import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .db import DB, now
from .tasks import HANDLERS

MAX_ATTEMPTS = 5


@dataclass
class Task:
    id: int
    job_id: int
    type: str
    params: dict
    priority: int
    state: str = "queued"          # queued | running | done | failed
    worker_id: str | None = None
    attempts: int = 0
    assigned_at: float = 0.0
    result: bytes | None = None    # the binary result frame as received


@dataclass
class Worker:
    id: str
    name: str
    send: Callable[[dict], Awaitable[None]]
    cpus: int = 1
    last_seen: float = field(default_factory=time.monotonic)
    alive: bool = True
    task_id: int | None = None
    done: int = 0
    metrics: dict = field(default_factory=dict)
    done_times: list = field(default_factory=list)
    last_latency_ms: int = 0

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "alive": self.alive, "busy": self.task_id is not None,
                "task_id": self.task_id, "done": self.done, "cpus": self.cpus, "metrics": self.metrics}


class Scheduler:
    def __init__(self, db: DB, heartbeat_timeout: float = 5.0,
                 emit: Callable[[dict], None] = lambda e: None):
        self.db, self.timeout, self.emit = db, heartbeat_timeout, emit
        self.jobs: dict[int, dict] = {}
        self.tasks: dict[int, Task] = {}
        self.workers: dict[str, Worker] = {}
        self._heap: list = []
        self._seq = itertools.count()
        self._task_ids = itertools.count(1)
        self._job_id = db.next_job_id()
        self.completed_times: list[float] = []

    # ---- jobs ----
    def submit(self, type_: str, params: dict, priority: int = 0) -> dict:
        if type_ not in HANDLERS:
            raise ValueError(f"unknown task type {type_!r}; known: {sorted(HANDLERS)}")
        h = HANDLERS[type_]
        params = h.normalize(params) if hasattr(h, "normalize") else params
        parts = h.split(params)
        params = h.summary(params) if hasattr(h, "summary") else params
        job = {"id": self._job_id, "type": type_, "params": params, "priority": priority,
               "state": "running", "total": len(parts), "done": 0, "created": now(), "task_ids": []}
        self._job_id += 1
        for p in parts:
            t = Task(next(self._task_ids), job["id"], type_, p, priority)
            self.tasks[t.id] = t
            job["task_ids"].append(t.id)
            self._push(t)
        self.jobs[job["id"]] = job
        self.db.save_job(job)
        self.emit({"e": "job_created", "job": self.job_public(job)})
        self.dispatch()
        return self.job_public(job)

    def cancel(self, jid: int) -> bool:
        job = self.jobs.get(jid)
        if not job:
            found = self.db.get_job(jid) is not None
            self.db.delete_job(jid)
            return found
        for tid in job["task_ids"]:
            t = self.tasks.pop(tid, None)
            if t and t.worker_id in self.workers and self.workers[t.worker_id].task_id == tid:
                self.workers[t.worker_id].task_id = None
            if t:
                t.state = "failed"        # lazily dropped from the heap
        del self.jobs[jid]
        self.db.delete_job(jid)
        self.emit({"e": "job_deleted", "job_id": jid})
        self.dispatch()
        return True

    @staticmethod
    def _tile(t: Task) -> list:
        return [t.params.get("tx", t.params.get("index", 0)), t.params.get("ty", 0)]

    @staticmethod
    def job_public(j: dict) -> dict:
        return {k: v for k, v in j.items() if k != "task_ids"}

    # ---- queue ----
    def _push(self, t: Task, front: bool = False):
        order = -next(self._seq) if front else next(self._seq)
        heapq.heappush(self._heap, (-t.priority, order, t.id))

    def queue_depth(self) -> int:
        return sum(1 for _, _, tid in self._heap if tid in self.tasks and self.tasks[tid].state == "queued")

    def dispatch(self):
        for w in self.workers.values():
            if not (w.alive and w.task_id is None):
                continue
            t = self._pop()
            if t is None:
                return
            t.state, t.worker_id, t.attempts, w.task_id = "running", w.id, t.attempts + 1, t.id
            t.assigned_at = time.monotonic()
            asyncio.get_running_loop().create_task(self._send_task(w, t))
            self.emit({"e": "task_assigned", "task_id": t.id, "job_id": t.job_id,
                       "worker_id": w.id, "tile": self._tile(t), "attempt": t.attempts})

    def _pop(self) -> Task | None:
        while self._heap:
            _, _, tid = heapq.heappop(self._heap)
            t = self.tasks.get(tid)
            if t and t.state == "queued":
                return t
        return None

    async def _send_task(self, w: Worker, t: Task):
        try:
            await w.send({"t": "task", "task_id": t.id, "type": t.type, "params": t.params})
        except Exception:
            self.worker_lost(w.id, "send failed")

    # ---- workers ----
    def worker_hello(self, wid: str, name: str, cpus: int, send) -> Worker:
        old = self.workers.get(wid)
        if old:                                   # same worker reconnecting: drop the stale session
            self.worker_lost(wid, "replaced by new connection")
        w = Worker(wid, name, send, cpus)
        self.workers[wid] = w
        self.emit({"e": "worker_joined", "worker": w.public()})
        self.dispatch()
        return w

    def heartbeat(self, w: Worker, metrics: dict):
        w.last_seen = time.monotonic()
        w.metrics = metrics
        self.emit({"e": "metrics", "worker_id": w.id, "metrics": metrics, "queue": self.queue_depth()})

    def worker_lost(self, wid: str, reason: str):
        w = self.workers.get(wid)
        if not w or not w.alive:
            return
        w.alive = False
        requeued = []
        if w.task_id is not None:
            t = self.tasks.get(w.task_id)
            w.task_id = None
            if t and t.state == "running":
                if t.attempts >= MAX_ATTEMPTS:
                    t.state = "failed"
                    self._fail_job(t.job_id)
                else:
                    t.state, t.worker_id = "queued", None
                    self._push(t, front=True)
                    requeued.append(t.id)
        self.emit({"e": "worker_lost", "worker_id": wid, "reason": reason, "requeued": requeued})
        self.dispatch()

    def reap(self):
        """Called periodically: workers silent for longer than the timeout are declared dead."""
        t = time.monotonic()
        for w in list(self.workers.values()):
            if w.alive and t - w.last_seen > self.timeout:
                self.worker_lost(w.id, "heartbeat timeout")
            elif not w.alive and t - w.last_seen > 60:
                del self.workers[w.id]
                self.emit({"e": "worker_removed", "worker_id": w.id})

    def task_done(self, w: Worker, task_id: int, frame: bytes):
        t = self.tasks.get(task_id)
        w.last_seen = time.monotonic()
        if not t or t.state != "running" or t.worker_id != w.id:
            return                                 # stale result from a reassigned/cancelled task
        t.state, t.result = "done", frame
        t.params.pop("data", None)                 # input file no longer needed, free the memory
        w.task_id, w.done = None, w.done + 1
        w.done_times.append(time.monotonic())
        w.last_latency_ms = round((time.monotonic() - t.assigned_at) * 1000)
        self.completed_times.append(time.monotonic())
        job = self.jobs[t.job_id]
        job["done"] += 1
        if job["done"] == job["total"]:
            job["state"], job["finished"] = "done", now()
        self.db.save_job(job)
        self.emit({"e": "task_done", "task_id": task_id, "job_id": job["id"], "worker_id": w.id,
                   "latency_ms": round((time.monotonic() - t.assigned_at) * 1000),
                   "tile": self._tile(t), "done": job["done"], "total": job["total"]})
        if job["state"] == "done":
            self.emit({"e": "job_done", "job": self.job_public(job)})
        self.dispatch()

    def task_error(self, w: Worker, task_id: int, msg: str):
        t = self.tasks.get(task_id)
        if not t or t.worker_id != w.id:
            return
        w.task_id = None
        t.state, t.worker_id = "failed", None
        self._fail_job(t.job_id, msg)
        self.dispatch()

    def _fail_job(self, jid: int, msg: str = "task failed too many times"):
        job = self.jobs.get(jid)
        if job and job["state"] != "failed":
            job["state"], job["finished"], job["error"] = "failed", now(), msg
            self.db.save_job(job)
            self.emit({"e": "job_failed", "job": self.job_public(job)})

    # ---- stats ----
    def sample(self) -> dict:
        """One point of metrics history (taken once per second by the server)."""
        mono = time.monotonic()
        ws = {}
        for w in self.workers.values():
            if not w.alive:
                continue
            w.done_times = [x for x in w.done_times if mono - x < 5]
            ws[w.id] = {"cpu": w.metrics.get("cpu", 0), "temp": w.metrics.get("temp", w.metrics.get("mem", 0)),
                        "tp": len(w.done_times) / 5, "lat": w.last_latency_ms}
        return {"t": round(time.time(), 1), "queue": self.queue_depth(), "tasks_per_s": round(self.throughput(), 2),
                "workers_alive": len(ws), "workers": ws}

    def throughput(self, window: float = 10.0) -> float:
        cut = time.monotonic() - window
        self.completed_times = [x for x in self.completed_times if x > cut]
        return len(self.completed_times) / window
