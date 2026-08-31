from __future__ import annotations

import numpy as np
from scipy import signal


def stft_spectrogram(iq: np.ndarray, sample_rate_hz: float, nperseg: int = 1024, noverlap: int = 512) -> dict[str, np.ndarray]:
    freq, time, zxx = signal.stft(np.asarray(iq), fs=sample_rate_hz, nperseg=nperseg, noverlap=noverlap, return_onesided=False)
    power_db = 20.0 * np.log10(np.maximum(np.abs(zxx), 1e-12))
    return {"frequency_hz": freq.astype(np.float32), "time_s": time.astype(np.float32), "power_db": power_db.astype(np.float32)}
