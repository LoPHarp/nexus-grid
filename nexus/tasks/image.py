"""Image batch: resize (fit into max_side), re-compress and convert files. One image = one task."""
import base64
import io
import os

from PIL import Image

from ..protocol import pack_file

FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
MAX_IMAGES, MAX_ONE, MAX_TOTAL = 50, 5_000_000, 25_000_000      # bytes after base64 decoding


def normalize(params: dict) -> dict:
    imgs = params.get("images")
    if not isinstance(imgs, list) or not 1 <= len(imgs) <= MAX_IMAGES:
        raise ValueError(f"images: a list of 1..{MAX_IMAGES} items {{name, data(base64)}}")
    total = 0
    for i in imgs:
        if not isinstance(i, dict) or not isinstance(i.get("name"), str) or not isinstance(i.get("data"), str):
            raise ValueError("each image needs string fields name and data (base64)")
        size = len(i["data"]) * 3 // 4
        if size > MAX_ONE:
            raise ValueError(f"{i['name']}: larger than {MAX_ONE // 10**6} MB")
        total += size
    if total > MAX_TOTAL:
        raise ValueError(f"batch larger than {MAX_TOTAL // 10**6} MB")
    op = {"max_side": int(params.get("max_side", 1024)), "format": str(params.get("format", "JPEG")).upper(),
          "quality": int(params.get("quality", 80))}
    if op["format"] not in FORMATS or not 16 <= op["max_side"] <= 8192 or not 1 <= op["quality"] <= 100:
        raise ValueError("format JPEG|PNG|WEBP, max_side 16..8192, quality 1..100")
    return {"images": imgs, **op}


def summary(params: dict) -> dict:
    """Job record without the image bytes (they stay in task memory only)."""
    return {"count": len(params["images"]), "names": [i["name"] for i in params["images"]],
            "max_side": params["max_side"], "format": params["format"], "quality": params["quality"]}


def split(params: dict) -> list[dict]:
    return [{"index": n, "name": i["name"], "data": i["data"], "max_side": params["max_side"],
             "format": params["format"], "quality": params["quality"]} for n, i in enumerate(params["images"])]


def compute(t: dict) -> tuple[bytes, int, int]:
    im = Image.open(io.BytesIO(base64.b64decode(t["data"])))
    im.load()
    im.thumbnail((t["max_side"], t["max_side"]))            # keeps aspect ratio, never upscales
    if t["format"] == "JPEG" and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    out = io.BytesIO()
    kw = {"quality": t["quality"]} if t["format"] in ("JPEG", "WEBP") else {"optimize": True}
    im.save(out, t["format"], **kw)
    return out.getvalue(), im.width, im.height


def pack(task_id: int, result) -> bytes:
    data, w, h = result
    return pack_file(task_id, data, w, h)


def output_name(t: dict) -> str:
    stem = os.path.splitext(os.path.basename(t["name"]))[0] or "image"
    return f"{t['index']:03d}_{stem}.{FORMATS[t['format']][0]}"


def media_type(t: dict) -> str:
    return FORMATS[t["format"]][1]
