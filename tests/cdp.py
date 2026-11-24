"""Tiny Chrome DevTools Protocol driver for UI checks (headless Chrome + the `websockets` package)."""
import asyncio
import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websockets


def chrome_path():
    for n in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(n)
        if p:
            return p
    return None


class Page:
    def __init__(self, port=9500, headed=False):
        self.port, self.n, self.proc, self.ws, self.headed = port, 0, None, None, headed

    async def __aenter__(self):
        self.tmp = tempfile.mkdtemp()
        self.proc = subprocess.Popen([chrome_path()] + ([] if self.headed else ["--headless=new", "--disable-gpu"]) + ["--no-sandbox", "--window-size=1300,820",
                                      f"--remote-debugging-port={self.port}", f"--user-data-dir={self.tmp}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                break
            except Exception:
                await asyncio.sleep(0.2)
        tab = [t for t in tabs if t["type"] == "page"][0]
        self.ws = await websockets.connect(tab["webSocketDebuggerUrl"], max_size=2**26)
        await self.cmd("Page.enable")
        await self.cmd("Runtime.enable")
        return self

    async def __aexit__(self, *a):
        await self.ws.close()
        self.proc.kill()

    async def cmd(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})

    async def goto(self, url, w=1280, h=720, init=None):
        await self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        if init:
            await self.cmd("Page.addScriptToEvaluateOnNewDocument", source=init)
        await self.cmd("Page.navigate", url=url)
        await asyncio.sleep(1.5)

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r["result"].get("value")

    async def click(self, selector):
        """Real mouse click at the element centre (not element.click())."""
        pt = await self.js(f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return null;e.scrollIntoView({{block:'center'}});const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}})()")
        if not pt:
            raise AssertionError(f"no element {selector}")
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.cmd("Input.dispatchMouseEvent", type=t, x=pt[0], y=pt[1], button="left", clickCount=1)
        await asyncio.sleep(0.15)

    async def hover(self, x, y):
        await self.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    async def shot(self, path):
        r = await self.cmd("Page.captureScreenshot", format="png")
        open(path, "wb").write(base64.b64decode(r["data"]))

    async def wait_for(self, expr, timeout=15, msg=""):
        end = time.time() + timeout
        while time.time() < end:
            if await self.js(expr):
                return
            await asyncio.sleep(0.25)
        raise AssertionError(msg or f"timeout waiting for {expr}")
