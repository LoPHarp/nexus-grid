import asyncio
import time

import numpy as np
import pytest

from nexus.db import DB
from nexus.protocol import pack_result, unpack_result
from nexus.scheduler import Scheduler
from nexus.tasks import mandelbrot

SMALL = {"width": 40, "height": 20, "tile": 10, "max_iter": 30}      # 8 tiles


def test_protocol_roundtrip():
    a = (np.arange(12, dtype=np.uint16) * 7).reshape(3, 4)
    tid, b = unpack_result(pack_result(42, a))
    assert tid == 42 and (a == b).all()


def test_mandelbrot_tile_values():
    tiles = mandelbrot.split({**SMALL, "cx": 0.0, "cy": 0.0, "view_w": 0.02})
    arr = mandelbrot.compute(tiles[0])
    assert arr.shape == (10, 10) and (arr == 30).all()               # origin neighbourhood never escapes
    far = mandelbrot.compute({"x0": 5.0, "y0": 5.0, "step": 0.1, "w": 4, "h": 4, "max_iter": 30})
    assert (far == 0).all()                                          # escapes immediately


def test_split_rejects_bad_params():
    with pytest.raises(ValueError):
        mandelbrot.split({"width": 100000})


class Fake:
    """Stands in for a worker connection: records what the server sent."""
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(m)


def make(timeout=0.2):
    return Scheduler(DB(":memory:"), heartbeat_timeout=timeout)


def frame(task_id):
    return pack_result(task_id, np.zeros((10, 10), dtype=np.uint16))


def run(coro):
    return asyncio.run(coro)


def test_priority_order_and_one_task_per_worker():
    async def go():
        s = make()
        low = s.submit("mandelbrot", SMALL, priority=0)
        high = s.submit("mandelbrot", SMALL, priority=5)
        f = Fake()
        w = s.worker_hello("a", "a", 1, f.send)
        await asyncio.sleep(0)
        assert len(f.sent) == 1                                      # capacity is one task
        assert s.tasks[f.sent[0]["task_id"]].job_id == high["id"]
        assert low["id"] != high["id"]
    run(go())


def test_job_completes():
    async def go():
        s = make()
        job = s.submit("mandelbrot", SMALL)
        f = Fake()
        w = s.worker_hello("a", "a", 1, f.send)
        for _ in range(job["total"]):
            await asyncio.sleep(0)
            s.task_done(w, f.sent[-1]["task_id"], frame(f.sent[-1]["task_id"]))
        assert s.jobs[job["id"]]["state"] == "done" and s.jobs[job["id"]]["done"] == 8
        assert s.db.get_job(job["id"])["state"] == "done"
    run(go())


def test_heartbeat_timeout_reassigns_task():
    async def go():
        s = make(timeout=0.2)
        s.submit("mandelbrot", SMALL)
        f1, f2 = Fake(), Fake()
        w1 = s.worker_hello("a", "a", 1, f1.send)
        await asyncio.sleep(0)
        lost_task = f1.sent[0]["task_id"]
        w2 = s.worker_hello("b", "b", 1, f2.send)
        await asyncio.sleep(0.3)
        s.heartbeat(w2, {})                                          # b stays alive, a is silent
        s.reap()
        assert not w1.alive and w2.alive
        await asyncio.sleep(0)
        s.task_done(w2, f2.sent[0]["task_id"], frame(f2.sent[0]["task_id"]))   # b frees up
        await asyncio.sleep(0)
        got = [m["task_id"] for m in f2.sent]
        assert lost_task in got                                      # the dead worker's task went to b
        assert s.tasks[lost_task].attempts == 2
    run(go())


def test_disconnect_requeues_at_front_and_stale_result_ignored():
    async def go():
        s = make()
        s.submit("mandelbrot", SMALL)
        f1, f2 = Fake(), Fake()
        w1 = s.worker_hello("a", "a", 1, f1.send)
        await asyncio.sleep(0)
        tid = f1.sent[0]["task_id"]
        s.worker_lost("a", "disconnected")
        w2 = s.worker_hello("b", "b", 1, f2.send)
        await asyncio.sleep(0)
        assert f2.sent[0]["task_id"] == tid                          # retried first
        s.task_done(w1, tid, frame(tid))                             # late result from dead worker
        assert s.tasks[tid].state == "running"
        s.task_done(w2, tid, frame(tid))
        assert s.tasks[tid].state == "done"
    run(go())


def test_task_fails_after_max_attempts():
    async def go():
        s = make()
        job = s.submit("mandelbrot", SMALL)
        for i in range(5):
            f = Fake()
            s.worker_hello(f"w{i}", "w", 1, f.send)
            await asyncio.sleep(0)
            s.worker_lost(f"w{i}", "x")
        assert s.jobs[job["id"]]["state"] == "failed"
    run(go())


def test_cancel_job():
    async def go():
        s = make()
        job = s.submit("mandelbrot", SMALL)
        assert s.cancel(job["id"]) and not s.cancel(job["id"])
        assert s.queue_depth() == 0
    run(go())


def test_dead_worker_is_removed_after_a_minute_and_event_emitted():
    async def go():
        events = []
        s = Scheduler(DB(":memory:"), heartbeat_timeout=0.2, emit=events.append)
        w = s.worker_hello("a", "a", 1, Fake().send)
        s.worker_lost("a", "x")
        w.last_seen -= 61
        s.reap()
        assert "a" not in s.workers and {"e": "worker_removed", "worker_id": "a"} in events
    run(go())
