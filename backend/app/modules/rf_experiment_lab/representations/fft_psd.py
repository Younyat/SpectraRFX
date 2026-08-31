from __future__ import annotations

import numpy as np
from scipy import signal


def welch_psd(iq: np.ndarray, sample_rate_hz: float, nperseg: int = 4096) -> dict[str, np.ndarray]:
    freq, psd = signal.welch(np.asarray(iq), fs=sample_rate_hz, nperseg=min(nperseg, len(iq)), return_onesided=False)
    order = np.argsort(freq)
    return {"frequency_hz": freq[order].astype(np.float32), "psd": psd[order].astype(np.float32)}
