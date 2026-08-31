from __future__ import annotations

import numpy as np


class StreamingIqMetrics:
    def __init__(self) -> None:
        self.samples = 0; self.sum_power = 0.0; self.peak = 0.0; self.clipped = 0; self.near_zero = 0; self.sum_iq = 0j

    def update(self, iq: np.ndarray) -> None:
        magnitude = np.abs(iq)
        self.samples += int(iq.size)
        self.sum_power += float(np.sum(magnitude * magnitude, dtype=np.float64))
        self.peak = max(self.peak, float(np.max(magnitude)) if iq.size else 0.0)
        self.clipped += int(np.count_nonzero(magnitude > 0.98))
        self.near_zero += int(np.count_nonzero(magnitude < 1e-6))
        self.sum_iq += complex(np.sum(iq, dtype=np.complex128))

    def result(self, sample_rate_hz: float) -> dict:
        count = max(self.samples, 1); rms = (self.sum_power / count) ** 0.5; dc = abs(self.sum_iq / count)
        return {"unique_samples_observed": self.samples, "duration_processed_seconds": self.samples / max(sample_rate_hz, 1.0), "peak_magnitude": self.peak, "rms_magnitude": rms, "clipping_ratio": self.clipped / count, "near_zero_ratio": self.near_zero / count, "dc_component_magnitude": dc, "possible_dc_or_lo_component": bool(dc > max(rms * 0.1, 1e-6)), "noise_floor_offset_applied": False}
