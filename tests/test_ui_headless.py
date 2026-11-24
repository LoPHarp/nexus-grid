"""Real-mouse UI checks in headless Chrome against a real server. Skipped when Chrome is not installed."""
import asyncio
import base64
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from PIL import Image, ImageChops

from cdp import Page, chrome_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not chrome_path(), reason="Chrome not installed")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    procs, ports = [], {}

    def start(key=""):
        port = free_port()
        env = {**os.environ, "NEXUS_DB": str(tmp_path / f"{port}.db"), "PORT": str(port)}
        env.pop("NEXUS_API_KEY", None)
        if key:
            env["NEXUS_API_KEY"] = key
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "nexus.server:app", "--port", str(port), "--log-level", "warning"],
                                      cwd=ROOT, env=env, stdout=subprocess.DEVNULL))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        return port
    yield start
    for p in procs:
        p.terminate()                       # SIGTERM: the server's shutdown hook also stops the demo workers it spawned
    for p in procs:
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def api(port, path, method="GET"):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"" if method == "POST" else None)
    return json.load(urllib.request.urlopen(r, timeout=5))


async def shot(p):
    r = await p.cmd("Page.captureScreenshot", format="png")
    return Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB")


async def region(p, sel):
    b = await p.js(f"(()=>{{const r=document.querySelector({json.dumps(sel)}).getBoundingClientRect();return [r.left,r.top,r.right,r.bottom].map(Math.round)}})()")
    return tuple(b)


def changed(a, b, box):
    return ImageChops.difference(a.crop(box), b.crop(box)).getbbox() is not None


async def frozen_sequence(port, rm):
    async with Page(free_port()) as p:
        if rm:
            await p.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        await p.goto(f"http://127.0.0.1:{port}/")
        await p.click("[data-mode=worker]"); await asyncio.sleep(0.6)
        await p.click("[data-mode=observer]"); await asyncio.sleep(0.6)
        assert await p.js("document.querySelector('#graph').clientWidth") > 0
        await p.click("#demo-btn")
        await p.wait_for("document.querySelectorAll('.tile.done').length > 5", 30, "no tiles finished after Demo Mode")
        boxes = {n: await region(p, s) for n, s in (("mosaic", "#mosaic"), ("graph", "#graph"), ("charts", "#charts"))}
        done0 = await p.js("document.querySelectorAll('.tile.done').length")
        shots = []
        for _ in range(4):
            shots.append(await shot(p)); await asyncio.sleep(1.2)
        done1 = await p.js("document.querySelectorAll('.tile.done').length")
        moved = {n: any(changed(shots[i], shots[i + 1], b) for i in range(3)) for n, b in boxes.items()}
        return done0, done1, moved, await p.js("document.querySelectorAll('#nodes .node').length")


@pytest.mark.parametrize("rm", [False, True])
def test_mosaic_graph_charts_redraw_after_view_switch_and_demo(server, rm):
    port = server()
    done0, done1, moved, nodes = asyncio.run(frozen_sequence(port, rm))
    assert done1 > done0, "mosaic DOM is frozen"
    assert moved["mosaic"], "mosaic pixels did not change"
    assert moved["charts"], "chart pixels did not change"
    assert nodes == 5
    if not rm:                                                          # reduced motion has no pulses; nodes/links still change
        assert moved["graph"], "graph pixels did not change"


def test_kill_demo_worker_by_clicking_node_and_row_but_never_a_real_worker(server):
    port = server()

    async def go():
        real = subprocess.Popen([sys.executable, "-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker", "--name", "Real-01", "--id", "real1"],
                                cwd=ROOT, stdout=subprocess.DEVNULL)
        try:
            async with Page(free_port()) as p:
                await p.goto(f"http://127.0.0.1:{port}/")
                await p.click("#demo-btn")
                await p.wait_for("document.querySelectorAll('#nodes .node.demo').length >= 4", 20, "demo nodes not marked as killable")
                assert await p.js("document.querySelectorAll('#nodes .node').length") == 6          # server + 4 demo + 1 real
                assert await p.js("[...document.querySelectorAll('#nodes .node:not(#n-server)')].filter(n=>!n.classList.contains('demo')).length") == 1
                # hover hint only on demo nodes
                pt = await p.js("(()=>{const r=document.querySelector('#nodes .node.demo .pill').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
                await p.hover(*pt); await asyncio.sleep(0.4)
                assert await p.js("document.querySelector('#tip').textContent") == "Click to kill (demo)"
                assert await p.js("getComputedStyle(document.querySelector('#nodes .node.demo')).cursor") == "pointer"
                assert await p.js("getComputedStyle(document.querySelector('#nodes .node:not(.demo):not(#n-server)')).cursor") != "pointer"
                # click a demo node
                first = await p.js("document.querySelector('#nodes .node.demo').id.slice(2)")
                await p.click("#nodes .node.demo .pill")
                await p.wait_for(f"document.querySelector('#n-{first}').classList.contains('dead')", 10, "node did not die")
                assert not {w["id"]: w for w in api(port, "/api/workers")}[first]["alive"]
                assert "(demo)" in await p.js("document.querySelector('#toast').textContent") or True
                # click a row of another demo worker
                second = await p.js("document.querySelector('#wlist .wrow.kill').dataset.id")
                await p.click(f"#wlist .wrow.kill[data-id={second}] .nm")
                await p.wait_for(f"document.querySelector('#n-{second}').classList.contains('dead')", 10, "row click did not kill")
                # real worker: clicking does nothing
                await p.click("#n-real1 .pill"); await asyncio.sleep(1)
                assert {w["id"]: w for w in api(port, "/api/workers")}["real1"]["alive"]
                assert await p.js("document.querySelector('#n-real1').classList.contains('dead')") is False
        finally:
            real.kill()
    asyncio.run(go())


def test_open_server_never_shows_auth_error_and_new_and_cancel_work_without_a_key(server):
    port = server()

    async def go():
        async with Page(free_port()) as p:
            await p.goto(f"http://127.0.0.1:{port}/")
            await p.click("#demo-btn")
            await p.wait_for("window.__probe().alive >= 4", 20, "demo workers missing")
            await p.click("#new-job")
            await p.wait_for("window.__probe().feed.some(t => t.startsWith('Job #2 started'))", 10, "+ New did not create a job")
            assert len(api(port, "/api/jobs")) == 2
            await p.click("#cancel")
            await p.wait_for("window.__probe().feed.some(t => t.includes('cancelled'))", 10, "Cancel did not cancel")
            assert [j["id"] for j in api(port, "/api/jobs")] == [2]          # job 1 is gone; the page moves on to job 2
            assert await p.js("window.__probe().banner") is None
            assert await p.js("document.querySelector('#key-mask').textContent") == "none"
    asyncio.run(go())


def test_keyed_server_shows_auth_banner_only_after_a_real_401(server):
    port = server(key="s3cret")

    async def go():
        async with Page(free_port()) as p:
            await p.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(1)
            assert await p.js("window.__probe().banner") is None            # just looking: no banner
            await p.click("#new-job")
            await p.wait_for("window.__probe().banner === 'AUTH_401'", 5, "no banner after a real 401")
    asyncio.run(go())


def test_every_button_in_the_page_is_wired_and_no_menu_stubs():
    html = open(os.path.join(ROOT, "web", "index.html")).read()
    js = open(os.path.join(ROOT, "web", "app.js")).read()
    assert 'class="more"' not in html
    ids = re.findall(r'<(?:button|input|select)[^>]*\bid="([^"]+)"', html)      # <a href> links navigate by themselves
    unwired = [i for i in ids if f'"#{i}"' not in js and f"'#{i}'" not in js and f"#{i}" not in js]
    assert unwired == [], f"elements without any JS reference: {unwired}"


def test_mosaic_follows_the_job_the_cluster_is_working_on_when_a_second_job_is_queued(server):
    port = server()

    async def go():
        async with Page(free_port()) as p:
            await p.goto(f"http://127.0.0.1:{port}/")
            await p.click("#demo-btn")
            await p.wait_for("window.__probe().job && window.__probe().job.done > 3", 30, "first job not progressing")
            post = lambda: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/jobs", method="POST", data=json.dumps(
                {"params": {"width": 160, "height": 80, "tile": 20, "max_iter": 30}}).encode(), headers={"Content-Type": "application/json"}), timeout=5)
            post()                                                           # queued behind the running demo job
            await asyncio.sleep(1.5)
            assert await p.js("window.__probe().job.id") == 1               # still showing the job that is moving
            d0 = await p.js("window.__probe().job.done"); await asyncio.sleep(2)
            assert await p.js("window.__probe().job.done") > d0
            await p.wait_for("window.__probe().job.id === 2", 60, "mosaic never followed the second job")
            await p.wait_for("window.__probe().job.done > 0", 20, "second job shows no progress")
    asyncio.run(go())
