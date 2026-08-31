from __future__ import annotations

import numpy as np

from app.modules.rf_experiment_lab.representations.spectrogram import stft_spectrogram


def waterfall_matrix(iq: np.ndarray, sample_rate_hz: float) -> dict[str, np.ndarray]:
    spec = stft_spectrogram(iq, sample_rate_hz)
    return {"time_axis_s": spec["time_s"], "freq_axis_hz": spec["frequency_hz"], "waterfall": spec["power_db"].T}
