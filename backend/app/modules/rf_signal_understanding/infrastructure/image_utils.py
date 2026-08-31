from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def normalize_to_uint8(matrix: np.ndarray, vmin: float | None = None, vmax: float | None = None) -> np.ndarray:
    data = np.asarray(matrix, dtype=np.float32)
    if data.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    low = float(np.nanmin(data) if vmin is None else vmin)
    high = float(np.nanmax(data) if vmax is None else vmax)
    if not np.isfinite(low):
        low = 0.0
    if not np.isfinite(high) or high <= low:
        high = low + 1.0
    scaled = (np.clip(data, low, high) - low) / (high - low)
    return np.asarray(np.round(scaled * 255.0), dtype=np.uint8)


def write_grayscale_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.asarray(image, dtype=np.uint8)
    if pixels.ndim != 2:
        raise ValueError("write_grayscale_png expects a 2-D uint8 image")
    height, width = pixels.shape

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        payload = chunk_type + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    raw_rows = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw_rows, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
