"""End to end: real server process + real worker processes; one worker is killed mid-job."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def call(port, path, method="GET", body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=5))


def wait_for(cond, timeout, msg):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.2)
    raise AssertionError(msg)


@pytest.fixture
def procs(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "NEXUS_DB": str(tmp_path / "t.db"), "HEARTBEAT_TIMEOUT": "2"}
    started = []

    def spawn(*args):  # noqa
        p = subprocess.Popen([PY, *args], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started.append(p)
        return p

    server = spawn("-m", "uvicorn", "nexus.server:app", "--port", str(port), "--log-level", "warning")
    wait_for(lambda: _up(port), 20, "server did not start")
    spawn.server = server
    yield port, spawn
    for p in started:
        p.kill()


def _up(port):
    try:
        return call(port, "/api/health")["status"] == "ok"
    except OSError:
        return False


def test_killed_worker_tasks_are_reassigned(procs):
    port, spawn = procs
    url = f"ws://127.0.0.1:{port}/ws/worker"
    workers = [spawn("-m", "nexus.worker", "--url", url, "--name", f"w{i}", "--id", f"w{i}", "--delay", "0.3")
               for i in range(3)]
    wait_for(lambda: len(call(port, "/api/workers")) == 3, 15, "workers did not connect")
    job = call(port, "/api/jobs", "POST", {"type": "mandelbrot",
               "params": {"width": 160, "height": 80, "tile": 20, "max_iter": 50}})   # 32 tiles
    wait_for(lambda: call(port, f"/api/jobs/{job['id']}")["done"] >= 4, 20, "no progress")
    workers[0].kill()                                                # crash one worker mid-job
    wait_for(lambda: call(port, f"/api/jobs/{job['id']}")["state"] == "done", 60, "job did not finish")
    final = call(port, f"/api/jobs/{job['id']}")
    assert final["done"] == final["total"] == 32
    ws = {w["id"]: w for w in call(port, "/api/workers")}
    assert not ws["w0"]["alive"] and ws["w1"]["alive"]


def test_worker_reconnects_after_server_restart(procs, tmp_path):
    port, spawn = procs
    spawn("-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker", "--name", "r", "--id", "r")
    wait_for(lambda: len(call(port, "/api/workers")) == 1, 15, "worker did not connect")
    # simulate the free host going to sleep: stop the server, start a fresh one on the same port
    first = spawn.server
    first.kill()
    first.wait()
    spawn("-m", "uvicorn", "nexus.server:app", "--port", str(port), "--log-level", "warning")
    wait_for(lambda: _up(port), 20, "server did not restart")
    wait_for(lambda: [w["alive"] for w in call(port, "/api/workers")] == [True], 20, "worker did not reconnect")


def test_dashboard_and_demo_endpoint(procs):
    port, spawn = procs
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
    assert "<title>Nexus Grid</title>" in html and "app.js" in html
    # demo workers are real processes started by the server; a killed one is reported dead
    res = call(port, "/api/demo?workers=2", "POST")
    assert res["workers"] == ["demo1", "demo2"] and res["job"]["total"] == 192
    wait_for(lambda: len(call(port, "/api/workers")) == 2, 15, "demo workers did not connect")
    wait_for(lambda: call(port, f"/api/jobs/{res['job']['id']}")["done"] > 0, 20, "no tiles done")
    assert call(port, "/api/workers/demo1/kill", "POST") == {"killed": "demo1"}
    wait_for(lambda: not {w["id"]: w for w in call(port, "/api/workers")}["demo1"]["alive"], 10, "kill not noticed")
    tile = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tiles/1", timeout=5).read()
    assert tile[0] == 1 and len(tile) > 9                            # binary result frame


def test_ask_endpoint_without_model_uses_recorded_or_rules(procs):
    port, spawn = procs
    import urllib.request
    def ask(q):
        r = urllib.request.Request(f"http://127.0.0.1:{port}/api/ask", method="POST", data=json.dumps({"question": q}).encode(),
                                   headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(r, timeout=5))
    a = ask("Is the cluster healthy?")
    assert a["source"] in ("rules", "recorded") and a["answer"]               # no workers: rules say so
    assert "No workers" in a["answer"]
    assert call(port, "/api/ask/suggestions")[0] == "Is the cluster healthy?"


def test_only_demo_workers_are_killable_and_flagged(procs):
    port, spawn = procs
    spawn("-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker", "--name", "Real-01", "--id", "real1")
    call(port, "/api/demo?workers=2", "POST")
    wait_for(lambda: len(call(port, "/api/workers")) == 3, 20, "workers did not connect")
    flags = {w["id"]: w["demo"] for w in call(port, "/api/workers")}
    assert flags == {"real1": False, "demo1": True, "demo2": True}
    with pytest.raises(urllib.error.HTTPError) as e:
        call(port, "/api/workers/real1/kill", "POST")
    assert e.value.code == 404                                        # real workers cannot be killed through the API
    assert {w["id"]: w for w in call(port, "/api/workers")}["real1"]["alive"]
    assert call(port, "/api/workers/demo1/kill", "POST") == {"killed": "demo1"}
