"""IQ file reading utilities supporting cf32, cf16_le, cf32_le, and complex64."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np


def complex_sample_nbytes(dtype_name: str) -> int:
    d = dtype_name.lower()
    if d in {"cf32", "cf32_le", "complex64"}:
        return 8
    if d in {"cf16_le", "float16"}:
        return 4
    return 8


def read_iq_window(path: Path, dtype_name: str, start_sample: int, n_samples: int) -> np.ndarray:
    """Read n_samples complex samples starting at start_sample from an IQ binary file."""
    d = dtype_name.lower()
    if d in {"cf32", "cf32_le", "complex64"}:
        scalar = np.dtype("<f4")
    elif d in {"cf16_le", "float16"}:
        scalar = np.dtype("<f2")
    else:
        raise ValueError(f"Unsupported IQ dtype: {dtype_name}")

    byte_offset = start_sample * 2 * scalar.itemsize
    raw = np.fromfile(str(path), dtype=scalar, count=n_samples * 2, offset=byte_offset)
    if raw.size < 4:
        raise ValueError(f"Too few IQ samples in {path}")
    raw = raw[: raw.size - (raw.size % 2)]
    return (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)).astype(np.complex64)


def read_full_iq(path: Path, dtype_name: str) -> np.ndarray:
    return read_iq_window(path, dtype_name, 0, _file_sample_count(path, dtype_name))


def _file_sample_count(path: Path, dtype_name: str) -> int:
    nbytes = complex_sample_nbytes(dtype_name)
    return int(path.stat().st_size // nbytes)


def windows_linspace(sample_count: Optional[int], window_size: int, n_windows: int) -> List[int]:
    if not sample_count or sample_count <= window_size:
        return [0]
    max_start = sample_count - window_size
    if n_windows <= 1:
        return [max_start // 2]
    return [int(x) for x in np.linspace(0, max_start, n_windows)]


def windows_energy_ranked(
    path: Path,
    dtype_name: str,
    sample_count: Optional[int],
    window_size: int,
    n_windows: int,
    candidates: int = 48,
) -> List[int]:
    if not sample_count or sample_count <= window_size:
        return [0]
    max_start = sample_count - window_size
    starts = [int(x) for x in np.linspace(0, max_start, max(candidates, n_windows))]
    scored = []
    for start in starts:
        try:
            iq = read_iq_window(path, dtype_name, start, window_size)
            pwr = float(np.mean(np.abs(iq.astype(np.complex128, copy=False)) ** 2))
            if np.isfinite(pwr):
                scored.append((pwr, start))
        except Exception:
            continue
    if not scored:
        return windows_linspace(sample_count, window_size, n_windows)
    scored.sort(reverse=True)
    return sorted({s for _, s in scored[:n_windows]}) or windows_linspace(sample_count, window_size, n_windows)


def select_windows(
    path: Path,
    dtype_name: str,
    sample_count: Optional[int],
    window_size: int,
    n_windows: int,
    strategy: str = "linspace",
) -> List[int]:
    if strategy == "energy":
        return windows_energy_ranked(path, dtype_name, sample_count, window_size, n_windows)
    return windows_linspace(sample_count, window_size, n_windows)
