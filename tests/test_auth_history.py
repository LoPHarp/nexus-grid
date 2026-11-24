"""API key enforcement and metrics history against a real server process."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def req(port, path, method="GET", body=None, key=None):
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=h,
                               data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, None


def wait_for(cond, timeout, msg):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise AssertionError(msg)


@pytest.fixture
def secured(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "NEXUS_DB": str(tmp_path / "a.db"), "NEXUS_API_KEY": "s3cret"}
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "nexus.server:app", "--port", str(port),
                               "--log-level", "warning"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL)]
    wait_for(lambda: req(port, "/api/health")[0] == 200, 20, "server did not start")
    yield port, procs, env
    for p in procs:
        p.kill()


JOB = {"type": "mandelbrot", "params": {"width": 80, "height": 40, "tile": 20, "max_iter": 30}}


def test_write_endpoints_need_key_reads_do_not(secured):
    port, _, _ = secured
    assert req(port, "/api/jobs", "POST", JOB)[0] == 401
    assert req(port, "/api/jobs", "POST", JOB, key="wrong")[0] == 401
    code, job = req(port, "/api/jobs", "POST", JOB, key="s3cret")
    assert code == 201 and job["total"] == 8
    assert req(port, "/api/jobs")[0] == 200 and req(port, "/api/workers")[0] == 200
    assert req(port, f"/api/jobs/{job['id']}", "DELETE")[0] == 401
    assert req(port, f"/api/jobs/{job['id']}", "DELETE", key="s3cret")[0] == 200
    assert req(port, "/api/jobs", "POST", {"type": "nope"}, key="s3cret")[0] == 422


def test_worker_needs_key_and_history_is_recorded(secured):
    port, procs, env = secured
    url = f"ws://127.0.0.1:{port}/ws/worker"
    bad = subprocess.Popen([sys.executable, "-m", "nexus.worker", "--url", url, "--name", "bad", "--key", "x"],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    time.sleep(2)
    assert req(port, "/api/workers")[1] == []                        # rejected, never registered
    bad.kill()
    good = subprocess.Popen([sys.executable, "-m", "nexus.worker", "--url", url, "--name", "good",
                             "--id", "good", "--key", "s3cret"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    procs.append(good)
    wait_for(lambda: len(req(port, "/api/workers")[1]) == 1, 15, "keyed worker did not connect")
    wait_for(lambda: any("good" in p["workers"] for p in req(port, "/api/metrics/history?seconds=30")[1]),
             10, "no history for worker")
    p = req(port, "/api/metrics/history?seconds=30")[1][-1]
    assert {"t", "queue", "tasks_per_s", "workers_alive", "workers"} <= set(p)
