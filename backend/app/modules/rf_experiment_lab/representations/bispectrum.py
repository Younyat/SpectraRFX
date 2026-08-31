from __future__ import annotations

import numpy as np


def bispectrum_proxy(iq: np.ndarray, fft_size: int = 256) -> np.ndarray:
    values = np.asarray(iq, dtype=np.complex64)[:fft_size]
    if values.size < fft_size:
        values = np.pad(values, (0, fft_size - values.size))
    spectrum = np.fft.fft(values)
    outer = spectrum[:, None] * spectrum[None, :] * np.conj(np.roll(spectrum, 1)[:, None])
    return np.abs(outer).astype(np.float32)
