from __future__ import annotations

import numpy as np


def alpha_profile_proxy(iq: np.ndarray, lags: int = 64) -> np.ndarray:
    values = np.asarray(iq, dtype=np.complex64)
    if values.size < 2:
        return np.zeros((lags,), dtype=np.float32)
    profile = [abs(np.mean(values[lag:] * np.conj(values[:-lag]))) if lag > 0 and lag < values.size else 0.0 for lag in range(lags)]
    return np.asarray(profile, dtype=np.float32)
