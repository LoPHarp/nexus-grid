"""Desktop worker: a small status window around nexus.worker (tkinter, standard library).
Run: python -m nexus.gui   (or the packaged executable)."""
import argparse
import asyncio
import os
import platform
import threading
import time
import tkinter as tk
import uuid
from tkinter import ttk

from .worker import main_async, to_ws

DEFAULT_URL = "https://nexus-grid-2ivy.onrender.com"


class App:
    def __init__(self, root, url, key, name):
        self.root, self.stats, self.loop, self.task = root, {}, None, None
        root.title("Nexus Grid worker")
        root.geometry("460x420")
        f = ttk.Frame(root, padding=10)
        f.pack(fill="both", expand=True)
        self.url, self.key, self.name = tk.StringVar(value=url), tk.StringVar(value=key), tk.StringVar(value=name)
        for i, (label, var, show) in enumerate((("Server", self.url, ""), ("Access key", self.key, "*"),
                                                ("Worker name", self.name, ""))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, show=show, width=44).grid(row=i, column=1, sticky="ew", pady=2)
        f.columnconfigure(1, weight=1)
        self.btn = ttk.Button(f, text="Connect", command=self.toggle)
        self.btn.grid(row=3, column=0, columnspan=2, pady=8, sticky="ew")
        self.status = tk.StringVar(value="stopped")
        self.info = tk.StringVar()
        ttk.Label(f, textvariable=self.status, font=("TkDefaultFont", 12, "bold")).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(f, textvariable=self.info).grid(row=5, column=0, columnspan=2, sticky="w")
        self.logbox = tk.Text(f, height=12, state="disabled", wrap="word")
        self.logbox.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        f.rowconfigure(6, weight=1)
        self.tick()

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}\n"
        self.root.after(0, self._append, line)

    def _append(self, line):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def toggle(self):
        if self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)
            return
        self.stats.clear()
        self.stats["state"] = "connecting"
        self.btn.configure(text="Disconnect")
        url, key, name = to_ws(self.url.get()), self.key.get().strip(), self.name.get().strip() or "worker"
        threading.Thread(target=self.run, args=(url, key, name), daemon=True).start()

    def run(self, url, key, name):
        self.loop = asyncio.new_event_loop()
        self.task = self.loop.create_task(main_async(url, name, uuid.uuid4().hex[:8], 0, self.log, key, self.stats))
        try:
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        finally:
            self.loop.close()
            self.task = None
            self.stats["state"] = "stopped"
            self.log("stopped")
            self.root.after(0, lambda: self.btn.configure(text="Connect"))

    def tick(self):
        s = self.stats
        self.status.set(s.get("state", "stopped"))
        m = s.get("metrics", {})
        self.info.set(f"tasks done: {s.get('done', 0)}   failed: {s.get('failed', 0)}   "
                      f"current: {s.get('task') or '-'}   CPU {m.get('cpu', 0):.0f}%  mem {m.get('mem', 0):.0f}%")
        self.root.after(500, self.tick)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("NEXUS_URL", DEFAULT_URL))
    ap.add_argument("--key", default=os.environ.get("NEXUS_API_KEY", ""))
    ap.add_argument("--name", default=platform.node() or "worker")
    ap.add_argument("--autoconnect", action="store_true")
    ap.add_argument("--selftest", type=float, default=0, help="close the window after N seconds (CI check)")
    a = ap.parse_args()
    root = tk.Tk()
    app = App(root, a.url, a.key, a.name)
    if a.autoconnect:
        root.after(200, app.toggle)
    if a.selftest:
        root.after(int(a.selftest * 1000), root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
