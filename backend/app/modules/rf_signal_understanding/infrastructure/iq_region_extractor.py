from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal


class IQRegionExtractor:
    def extract(
        self,
        iq_samples: np.ndarray,
        sample_rate_hz: float,
        center_frequency_hz: float,
        region: dict[str, Any],
        output_dir: Path,
    ) -> dict[str, Any]:
        sample_start = max(0, int(float(region["time_start_s"]) * sample_rate_hz))
        sample_end = min(iq_samples.size, max(sample_start + 1, int(float(region["time_end_s"]) * sample_rate_hz)))
        segment = np.asarray(iq_samples[sample_start:sample_end], dtype=np.complex64)
        low_hz = float(region["freq_start_hz"]) - float(center_frequency_hz)
        high_hz = float(region["freq_end_hz"]) - float(center_frequency_hz)
        if high_hz < low_hz:
            low_hz, high_hz = high_hz, low_hz
        nyquist = float(sample_rate_hz) / 2.0
        clipped_low = max(low_hz, -nyquist * 0.98)
        clipped_high = min(high_hz, nyquist * 0.98)

        filtered = segment
        if segment.size > 16 and clipped_high > clipped_low:
            bandwidth = clipped_high - clipped_low
            shift_hz = (clipped_low + clipped_high) / 2.0
            n = np.arange(segment.size, dtype=np.float64)
            shifted = segment * np.exp(-2j * np.pi * shift_hz * n / float(sample_rate_hz))
            cutoff = min(max((bandwidth / 2.0) / nyquist, 0.005), 0.95)
            taps = signal.firwin(numtaps=min(129, max(17, (segment.size // 8) | 1)), cutoff=cutoff)
            filtered = signal.lfilter(taps, [1.0], shifted).astype(np.complex64)

        region_dir = output_dir / "regions"
        region_dir.mkdir(parents=True, exist_ok=True)
        segment_path = region_dir / f"{region['bbox_id']}.iq"
        filtered.astype(np.complex64).tofile(segment_path)
        return {
            "iq_segment_path": str(segment_path),
            "sample_start": int(sample_start),
            "sample_end": int(sample_end),
            "bandpass_low_hz": float(clipped_low),
            "bandpass_high_hz": float(clipped_high),
        }
