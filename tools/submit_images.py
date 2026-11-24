#!/usr/bin/env python3
"""Send a folder of images to a Nexus Grid server as an image-batch job and download the results.
Usage: NEXUS_URL=https://host NEXUS_API_KEY=... python tools/submit_images.py ./photos --max-side 800 --format WEBP
Standard library only."""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def call(base, path, key, body=None, method=None, raw=False):
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    req = urllib.request.Request(base + path, headers=h, method=method or ("POST" if body else "GET"),
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} for {path}: {e.read().decode()[:300]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--max-side", type=int, default=1024)
    ap.add_argument("--format", default="JPEG", choices=["JPEG", "PNG", "WEBP"])
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--out", default="out")
    ap.add_argument("--url", default=os.environ.get("NEXUS_URL", "http://localhost:8000"))
    a = ap.parse_args()
    key, base = os.environ.get("NEXUS_API_KEY", ""), a.url.rstrip("/")
    files = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in EXT)
    if not files:
        sys.exit("no images found")
    images = [{"name": p.name, "data": base64.b64encode(p.read_bytes()).decode()} for p in files]
    job = call(base, "/api/jobs", key, {"type": "image", "params": {
        "images": images, "max_side": a.max_side, "format": a.format, "quality": a.quality}})
    print(f"job {job['id']}: {job['total']} images")
    while job["state"] == "running":
        time.sleep(1)
        job = call(base, f"/api/jobs/{job['id']}", key)
        print(f"  {job['done']}/{job['total']} {job['state']}")
    if job["state"] != "done":
        sys.exit(f"job ended as {job['state']}: {job.get('error')}")
    z = zipfile.ZipFile(io.BytesIO(call(base, f"/api/jobs/{job['id']}/download", key, raw=True)))
    z.extractall(a.out)
    before = sum(p.stat().st_size for p in files)
    after = sum(i.file_size for i in z.infolist())
    print(f"saved {len(z.namelist())} files to {a.out}/: {before:,} -> {after:,} bytes")


if __name__ == "__main__":
    main()
