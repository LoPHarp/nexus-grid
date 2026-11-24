import numpy as np

DEFAULTS = {"width": 800, "height": 600, "tile": 100, "max_iter": 200,
            "cx": -0.5, "cy": 0.0, "view_w": 3.0}


def normalize(params: dict) -> dict:
    """Fill defaults so the stored job (and the dashboard) sees the real geometry."""
    return {**DEFAULTS, **params}


def split(params: dict) -> list[dict]:
    """Server side: job params -> one params dict per tile (= per task)."""
    p = normalize(params)
    for k in ("width", "height", "tile", "max_iter"):
        p[k] = int(p[k])
    if not (1 <= p["width"] <= 4096 and 1 <= p["height"] <= 4096 and 8 <= p["tile"] <= 512
            and 1 <= p["max_iter"] <= 5000):
        raise ValueError("width/height 1..4096, tile 8..512, max_iter 1..5000")
    step = p["view_w"] / p["width"]
    x_left = p["cx"] - p["view_w"] / 2
    y_top = p["cy"] + step * p["height"] / 2
    tiles = []
    for ty, py in enumerate(range(0, p["height"], p["tile"])):
        for tx, px in enumerate(range(0, p["width"], p["tile"])):
            tiles.append({"tx": tx, "ty": ty, "px": px, "py": py,
                          "w": min(p["tile"], p["width"] - px), "h": min(p["tile"], p["height"] - py),
                          "x0": x_left + px * step, "y0": y_top - py * step, "step": step,
                          "max_iter": p["max_iter"]})
    return tiles


def compute(t: dict) -> np.ndarray:
    """Worker side: escape-time iteration counts for one tile (uint16, shape h x w)."""
    xs = t["x0"] + np.arange(t["w"]) * t["step"]
    ys = t["y0"] - np.arange(t["h"]) * t["step"]
    c = xs[None, :] + 1j * ys[:, None]
    z = np.zeros_like(c)
    out = np.zeros(c.shape, dtype=np.uint16)
    alive = np.ones(c.shape, dtype=bool)
    for i in range(t["max_iter"]):
        z[alive] = z[alive] ** 2 + c[alive]
        esc = alive & (z.real ** 2 + z.imag ** 2 > 4.0)
        out[esc] = i
        alive &= ~esc
        if not alive.any():
            break
    out[alive] = t["max_iter"]
    return out
