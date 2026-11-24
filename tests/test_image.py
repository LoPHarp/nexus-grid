import base64
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest
from PIL import Image

from nexus.protocol import frame_payload, frame_task_id
from nexus.tasks import image
from test_failover import call, procs, wait_for, ROOT   # noqa: F401  (fixture reuse)


def png(w, h, mode="RGB"):
    b = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def test_compute_resizes_and_converts():
    t = image.split(image.normalize({"images": [{"name": "a.png", "data": png(400, 200, "RGBA")}],
                                     "max_side": 100, "format": "jpeg", "quality": 70}))[0]
    data, w, h = image.compute(t)
    im = Image.open(io.BytesIO(data))
    assert im.format == "JPEG" and (w, h) == (100, 50) == im.size    # RGBA handled, aspect ratio kept
    assert image.output_name(t) == "000_a.jpg"
    frame = image.pack(7, (data, w, h))
    assert frame_task_id(frame) == 7 and frame_payload(frame) == data


def test_small_images_are_not_upscaled():
    t = image.split(image.normalize({"images": [{"name": "s.png", "data": png(50, 40)}], "format": "PNG"}))[0]
    assert image.compute(t)[1:] == (50, 40)


@pytest.mark.parametrize("bad", [
    {"images": []}, {"images": [{"name": "x"}]}, {"images": [{"name": "x", "data": "AA"}], "format": "GIF"},
    {"images": [{"name": "x", "data": "AA"}], "max_side": 5},
    {"images": [{"name": "x", "data": "A" * 7_000_000}]}])
def test_rejects_bad_params(bad):
    with pytest.raises(ValueError):
        image.normalize(bad)


def test_image_job_end_to_end_with_zip(procs):
    port, spawn = procs
    spawn("-m", "nexus.worker", "--url", f"ws://127.0.0.1:{port}/ws/worker", "--name", "i", "--id", "i")
    wait_for(lambda: len(call(port, "/api/workers")) == 1, 15, "worker did not connect")
    imgs = [{"name": f"p{i}.png", "data": png(300 + i, 200)} for i in range(4)]
    job = call(port, "/api/jobs", "POST", {"type": "image", "params": {
        "images": imgs, "max_side": 64, "format": "WEBP", "quality": 60}})
    assert job["params"]["count"] == 4 and "data" not in json.dumps(job["params"])   # bytes not stored in the record
    wait_for(lambda: call(port, f"/api/jobs/{job['id']}")["state"] == "done", 30, "image job did not finish")
    import urllib.request
    raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs/{job['id']}/download", timeout=5).read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    assert sorted(z.namelist()) == [f"00{i}_p{i}.webp" for i in range(4)]
    assert all(Image.open(io.BytesIO(z.read(n))).size[0] == 64 for n in z.namelist())
