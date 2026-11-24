"""Wire protocol shared by server and worker.

Control messages are JSON text frames: {"t": <type>, ...}.
Worker -> server: hello, heartbeat, error.   Server -> worker: welcome, task.
Tile results travel as one binary frame:
    offset 0  u8   frame type (1 = result)
    offset 1  u32  task id            (big endian)
    offset 5  u16  width in pixels
    offset 7  u16  height in pixels
    offset 9  ...  zlib(uint16 little-endian iteration counts, row-major)
"""
import struct
import zlib

import numpy as np

FRAME_RESULT = 1
_HDR = struct.Struct(">BIHH")


def pack_result(task_id: int, arr: np.ndarray) -> bytes:
    h, w = arr.shape
    return _HDR.pack(FRAME_RESULT, task_id, w, h) + zlib.compress(arr.astype("<u2").tobytes(), 1)


def unpack_result(frame: bytes) -> tuple[int, np.ndarray]:
    kind, task_id, w, h = _HDR.unpack_from(frame)
    if kind != FRAME_RESULT:
        raise ValueError(f"unknown frame type {kind}")
    data = zlib.decompress(frame[_HDR.size:])
    if len(data) != w * h * 2:
        raise ValueError("result size mismatch")
    return task_id, np.frombuffer(data, dtype="<u2").reshape(h, w)
