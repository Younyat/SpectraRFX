from __future__ import annotations

import numpy as np


def spectral_log_features(psd: np.ndarray, bins: int = 40) -> np.ndarray:
    values = np.log10(np.maximum(np.asarray(psd, dtype=np.float32), 1e-12))
    if values.size == 0:
        return np.zeros((bins,), dtype=np.float32)
    edges = np.linspace(0, values.size, bins + 1, dtype=int)
    return np.asarray([float(np.mean(values[edges[i] : max(edges[i + 1], edges[i] + 1)])) for i in range(bins)], dtype=np.float32)
