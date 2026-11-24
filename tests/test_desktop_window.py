"""Drives the real native window (pywebview + Qt) with tests/ui/desktop_check.js. Skipped without a display or pywebview."""
import json
import os
import subprocess
import sys

import pytest

from test_ui_headless import ROOT, server  # noqa: F401  (fixture)

try:
    import webview  # noqa: F401
    HAVE = True
except Exception:
    HAVE = False
pytestmark = pytest.mark.skipif(not (HAVE and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))), reason="needs pywebview and a display")


def test_desktop_window_sequence_kill_and_native_downloads(server, tmp_path):
    port = server()
    out = subprocess.run([sys.executable, "-m", "nexus.desktop", "--url", f"http://127.0.0.1:{port}", "--name", "Atlas-01",
                          "--script", os.path.join(ROOT, "tests", "ui", "desktop_check.js"), "--save-dir", str(tmp_path)],
                         cwd=ROOT, capture_output=True, text=True, timeout=240)
    line = [l for l in out.stdout.splitlines() if l.startswith("SCRIPT ")]
    assert line, out.stdout[-500:] + out.stderr[-500:]
    res = json.loads(line[0][7:])
    assert "error" not in res, res
    assert res["desktopApi"] and res["graphWidthAfterReturn"] > 0
    assert res["tilesAdvanced"] and res["chartsChanged"] and res["killed"] and res["demoNodes"] >= 3
    assert res["imageJobStatus"] == 201 and res["banner"] is None
    assert res["toastPng"].startswith("Saved") and res["toastZip"].startswith("Saved"), res
    files = sorted(os.listdir(tmp_path))
    assert any(f.endswith(".png") for f in files) and any(f.endswith(".zip") for f in files), files
    assert open(tmp_path / [f for f in files if f.endswith(".png")][0], "rb").read(8) == b"\x89PNG\r\n\x1a\n"
    assert open(tmp_path / [f for f in files if f.endswith(".zip")][0], "rb").read(2) == b"PK"
