from __future__ import annotations

import numpy as np


class BispectralFeatureExtractor:
    def extract(self, iq_segment: np.ndarray, max_bins: int = 64) -> dict[str, object]:
        samples = np.asarray(iq_segment, dtype=np.complex64)
        if samples.size < 32:
            return {
                "bispectrum_matrix": [],
                "bispectral_peak_energy": 0.0,
                "bispectral_peak_location": [0.0, 0.0],
                "bispectral_entropy": 0.0,
                "phase_coupling_score": 0.0,
                "nonlinear_energy_ratio": 0.0,
            }
        windowed = samples[: min(samples.size, max_bins * 8)]
        spectrum = np.fft.fft(windowed, n=max_bins)
        bispectrum = np.zeros((max_bins, max_bins), dtype=np.complex64)
        for f1 in range(max_bins):
            for f2 in range(max_bins):
                bispectrum[f1, f2] = spectrum[f1] * spectrum[f2] * np.conj(spectrum[(f1 + f2) % max_bins])
        magnitude = np.abs(bispectrum).astype(np.float64)
        total = float(np.sum(magnitude) + 1e-18)
        normalized = magnitude / total
        peak_index = np.unravel_index(int(np.argmax(magnitude)), magnitude.shape)
        peak_energy = float(magnitude[peak_index] / (np.max(magnitude) + 1e-18))
        entropy = float(-np.sum(normalized * np.log2(normalized + 1e-18)) / max(np.log2(normalized.size), 1.0))
        phase = np.angle(bispectrum)
        phase_coupling = float(np.abs(np.mean(np.exp(1j * phase))))
        linear_energy = float(np.sum(np.abs(spectrum) ** 2) + 1e-18)
        nonlinear_ratio = float(total / (total + linear_energy))
        preview = magnitude[:16, :16]
        preview = preview / (float(np.max(preview)) + 1e-18)
        return {
            "bispectrum_matrix": preview.round(6).tolist(),
            "bispectral_peak_energy": peak_energy,
            "bispectral_peak_location": [float(peak_index[0] / max_bins), float(peak_index[1] / max_bins)],
            "bispectral_entropy": entropy,
            "phase_coupling_score": phase_coupling,
            "nonlinear_energy_ratio": nonlinear_ratio,
        }
