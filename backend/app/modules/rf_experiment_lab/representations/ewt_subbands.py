from __future__ import annotations

import numpy as np


def simple_fft_subbands(iq: np.ndarray, bands: int = 8) -> np.ndarray:
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(np.asarray(iq, dtype=np.complex64))))
    if spectrum.size == 0:
        return np.zeros((bands,), dtype=np.float32)
    splits = np.array_split(spectrum, bands)
    return np.asarray([float(np.mean(part)) for part in splits], dtype=np.float32)
