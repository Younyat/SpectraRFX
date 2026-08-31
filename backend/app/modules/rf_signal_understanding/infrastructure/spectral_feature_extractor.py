from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal, stats


class SpectralFeatureExtractor:
    def extract(
        self,
        iq_segment: np.ndarray,
        sample_rate_hz: float,
        region_waterfall_matrix: np.ndarray,
        region: dict[str, Any],
    ) -> dict[str, float]:
        samples = np.asarray(iq_segment, dtype=np.complex64)
        if samples.size < 8:
            return self._empty(region)
        nperseg = min(1024, max(64, int(samples.size // 2)))
        freqs, psd = signal.welch(samples, fs=float(sample_rate_hz), nperseg=nperseg, return_onesided=False)
        order = np.argsort(freqs)
        freqs = freqs[order]
        power = np.asarray(np.abs(psd[order]), dtype=np.float64) + 1e-18
        probs = power / np.sum(power)
        centroid = float(np.sum(freqs * probs))
        spread = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * probs)))
        entropy = float(-np.sum(probs * np.log2(probs + 1e-18)) / max(np.log2(probs.size), 1.0))
        kurtosis = float(stats.kurtosis(power, fisher=False, bias=False)) if power.size > 3 else 0.0
        peak_threshold = np.percentile(power, 90)
        peak_count = int(np.sum((power[1:-1] > power[:-2]) & (power[1:-1] > power[2:]) & (power[1:-1] >= peak_threshold)))
        occupied_bandwidth = float(region.get("occupied_bandwidth_hz", 0.0))
        duration = float(region.get("time_end_s", 0.0)) - float(region.get("time_start_s", 0.0))
        region_matrix = np.asarray(region_waterfall_matrix, dtype=np.float32)
        time_occupancy_ratio = 0.0
        snr_db = 0.0
        if region_matrix.size:
            threshold = np.percentile(region_matrix, 75)
            time_occupancy_ratio = float(np.mean(np.max(region_matrix, axis=1) >= threshold))
            snr_db = float(np.percentile(region_matrix, 95) - np.percentile(region_matrix, 20))
        return {
            "occupied_bandwidth_hz": occupied_bandwidth,
            "spectral_centroid_hz": centroid,
            "spectral_spread_hz": spread,
            "spectral_entropy": entropy,
            "spectral_kurtosis": kurtosis,
            "peak_count": float(peak_count),
            "burst_duration_s": max(duration, 0.0),
            "duty_cycle": time_occupancy_ratio,
            "frequency_drift_hz": self._estimate_drift(region_matrix, occupied_bandwidth),
            "time_occupancy_ratio": time_occupancy_ratio,
            "snr_db": snr_db,
        }

    def _empty(self, region: dict[str, Any]) -> dict[str, float]:
        return {
            "occupied_bandwidth_hz": float(region.get("occupied_bandwidth_hz", 0.0)),
            "spectral_centroid_hz": 0.0,
            "spectral_spread_hz": 0.0,
            "spectral_entropy": 0.0,
            "spectral_kurtosis": 0.0,
            "peak_count": 0.0,
            "burst_duration_s": 0.0,
            "duty_cycle": 0.0,
            "frequency_drift_hz": 0.0,
            "time_occupancy_ratio": 0.0,
            "snr_db": 0.0,
        }

    def _estimate_drift(self, region_matrix: np.ndarray, occupied_bandwidth_hz: float) -> float:
        if region_matrix.ndim != 2 or min(region_matrix.shape) < 2:
            return 0.0
        peaks = np.argmax(region_matrix, axis=1)
        drift_bins = float(np.max(peaks) - np.min(peaks))
        return drift_bins / max(region_matrix.shape[1] - 1, 1) * float(occupied_bandwidth_hz)
