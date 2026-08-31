from __future__ import annotations

import numpy as np


def estimate_basic_impairments(iq: np.ndarray, sample_rate_hz: float) -> dict[str, float]:
    values = np.asarray(iq, dtype=np.complex64)
    if values.size == 0:
        return {"dc_offset_level": 0.0, "iq_imbalance_estimate": 0.0, "cfo_proxy_hz": 0.0}
    dc = complex(np.mean(values))
    real_power = float(np.mean(np.square(values.real)))
    imag_power = float(np.mean(np.square(values.imag)))
    phase_step = np.angle(values[1:] * np.conj(values[:-1])) if values.size > 1 else np.asarray([0.0])
    return {
        "dc_offset_level": float(abs(dc)),
        "iq_imbalance_estimate": float(abs(real_power - imag_power) / max(real_power + imag_power, 1e-12)),
        "cfo_proxy_hz": float(np.mean(phase_step) * sample_rate_hz / (2.0 * np.pi)),
    }
