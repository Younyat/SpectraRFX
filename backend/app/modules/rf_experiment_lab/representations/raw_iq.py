from __future__ import annotations

from pathlib import Path

import numpy as np


def load_complex64_iq(path: str | Path, max_samples: int | None = None) -> np.ndarray:
    data = np.fromfile(Path(path), dtype=np.complex64)
    if max_samples is not None:
        data = data[:max_samples]
    return data


def iq_channels(iq: np.ndarray) -> np.ndarray:
    values = np.asarray(iq, dtype=np.complex64)
    return np.stack([values.real, values.imag]).astype(np.float32)
