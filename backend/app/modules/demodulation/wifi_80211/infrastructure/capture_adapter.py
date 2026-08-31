from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

import numpy as np

BYTES_PER_COMPLEX = {"cf32_le": 8, "ci16_le": 4, "cu8": 2}


def sha256_file(path: Path, chunk_bytes: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_bytes), b""):
            digest.update(block)
    return digest.hexdigest()


def sample_count(path: Path, datatype: str) -> int:
    width = BYTES_PER_COMPLEX.get(datatype)
    return path.stat().st_size // width if width else 0


def file_layout(path: Path, datatype: str) -> dict[str, int]:
    width = BYTES_PER_COMPLEX.get(datatype)
    size = path.stat().st_size
    return {
        "file_size_bytes": size,
        "samples_total_in_file": size // width if width else 0,
        "trailing_incomplete_bytes": size % width if width else size,
    }


def iter_iq_chunks(path: Path, datatype: str, chunk_samples: int = 1_000_000) -> Iterator[tuple[int, np.ndarray]]:
    """Yield bounded complex64 chunks and their absolute first sample index."""
    raw_dtype = {"cf32_le": "<f4", "ci16_le": "<i2", "cu8": np.uint8}.get(datatype)
    if raw_dtype is None:
        raise ValueError(f"Unsupported IQ datatype: {datatype}")
    offset = 0
    with path.open("rb") as stream:
        while True:
            raw = np.fromfile(stream, dtype=raw_dtype, count=max(1, chunk_samples) * 2)
            raw = raw[: raw.size - raw.size % 2]
            if not raw.size:
                break
            if datatype == "cf32_le":
                scaled = raw.astype(np.float32, copy=False)
            elif datatype == "ci16_le":
                scaled = raw.astype(np.float32) / 32768.0
            else:
                scaled = (raw.astype(np.float32) - 127.5) / 127.5
            iq = (scaled[0::2] + 1j * scaled[1::2]).astype(np.complex64, copy=False)
            yield offset, iq
            offset += iq.size
