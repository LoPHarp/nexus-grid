"""Desktop client: the dashboard page in a native window (pywebview) plus the Python worker beside it.
The page talks to the local worker through window.pywebview.api (class LocalWorker below).
Run: python -m nexus.desktop   (or the packaged executable)."""
import argparse
import asyncio
import json
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path

from .worker import main_async, to_ws

DEFAULT_URL = "https://nexus-grid-2ivy.onrender.com"
CONFIG = Path.home() / ".nexus-grid.json"        # server URL, worker name, auto-reconnect; never the key


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "web"


class LocalWorker:
    """Exposed to JavaScript. Attributes start with '_' so pywebview does not introspect them."""

    def __init__(self, url, key, name):
        saved = {}
        try:
            saved = json.loads(CONFIG.read_text())
        except (OSError, ValueError):
            pass
        self._cfg = {"url": url or saved.get("url") or DEFAULT_URL, "name": name or saved.get("name") or platform.node() or "worker",
                     "auto_reconnect": saved.get("auto_reconnect", True)}
        self._key = key
        self._stats, self._log, self._thread, self._loop, self._task = {"state": "stopped"}, [], None, None, None
        self._window = None
        self._maximized = False

    # ---- worker control ----
    def get_config(self):
        return {"desktop": True, **self._cfg, "key": self._key, "platform": sys.platform}

    def connect(self, url, key, name):
        if self._thread and self._thread.is_alive():
            return
        self._cfg.update(url=url.strip(), name=(name or "").strip() or self._cfg["name"])
        self._key = key.strip()
        self._save()
        self._stats = {"state": "connecting", "auto_reconnect": self._cfg["auto_reconnect"], "done": 0, "failed": 0}
        self._thread = threading.Thread(target=self._run, args=(to_ws(self._cfg["url"]), self._key, self._cfg["name"]), daemon=True)
        self._thread.start()

    def disconnect(self):
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def set_auto_reconnect(self, on):
        self._cfg["auto_reconnect"] = bool(on)
        self._stats["auto_reconnect"] = bool(on)
        self._save()

    def state(self, since=0):
        s = dict(self._stats)
        s["log"], s["log_len"] = self._log[since:], len(self._log)
        s["uptime_s"] = round(time.time() - s["since"]) if s.get("since") and s.get("state") == "online" else 0
        return s

    # ---- window controls (frameless window) ----
    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        (self._window.restore if self._maximized else self._window.maximize)()
        self._maximized = not self._maximized

    def close(self):
        self._window.destroy()

    # ---- internals ----
    def _save(self):
        try:
            CONFIG.write_text(json.dumps(self._cfg))
        except OSError:
            pass

    def _add_log(self, msg, kind="info"):
        self._log.append({"t": time.strftime("%I:%M:%S %p"), "msg": msg, "kind": kind or "info"})
        del self._log[:-300]

    def _run(self, url, key, name):
        self._loop = asyncio.new_event_loop()
        self._task = self._loop.create_task(main_async(url, name, uuid.uuid4().hex[:8], 0, self._add_log, key, self._stats))
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            self._stats["state"] = "offline"
            self._add_log("disconnected", "warn")
        finally:
            self._loop.close()
            self._task = None


def main():
    import webview
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("NEXUS_URL", ""))
    ap.add_argument("--key", default=os.environ.get("NEXUS_API_KEY", ""))
    ap.add_argument("--name", default="")
    ap.add_argument("--autoconnect", action="store_true")
    ap.add_argument("--selftest", type=float, default=0, help="print a DOM probe after N seconds and exit (CI)")
    a = ap.parse_args()
    api = LocalWorker(a.url, a.key, a.name)
    page = str(web_dir() / "index.html")
    win = webview.create_window("Nexus Grid", page, js_api=api, width=1360, height=820, min_size=(380, 640),
                                frameless=True, easy_drag=False, background_color="#050811")
    api._window = win

    def after_start():
        if a.autoconnect:
            time.sleep(1.5)
            api.connect(api._cfg["url"], api._key, api._cfg["name"])
        if a.selftest:
            time.sleep(a.selftest)
            print("PROBE", win.evaluate_js("JSON.stringify(window.__probe ? window.__probe() : null)"), flush=True)
            win.destroy()

    webview.start(after_start, private_mode=False, storage_path=str(Path.home() / ".nexus-grid-webview"))


if __name__ == "__main__":
    main()
