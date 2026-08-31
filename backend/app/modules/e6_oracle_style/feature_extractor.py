"""
E6 feature extraction — 37 tabular features from a complex IQ window.

Identical feature set to the reference Oracle-style pipeline so that
models trained here are compatible with live inference from any source
that produces the same 37-element vector in the same order.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np

FEATURE_EXTRACTOR_VERSION = "e6_features_v1"
_N_FFT_BINS = 12


def feature_names(n_fft_bins: int = _N_FFT_BINS) -> List[str]:
    base = [
        "amp_mean", "amp_std", "amp_min", "amp_max",
        "amp_p10", "amp_p50", "amp_p90",
        "power_mean", "power_std",
        "real_mean", "real_std",
        "imag_mean", "imag_std",
        "phase_diff_mean", "phase_diff_std",
        "phase_diff_p10", "phase_diff_p90",
        "iq_corr", "papr",
        "zero_cross_real", "zero_cross_imag",
        "spectral_centroid", "spectral_spread", "spectral_flatness",
    ]
    return base + [f"fft_band_{i:02d}" for i in range(n_fft_bins)]


def extract_features(iq: np.ndarray, n_fft_bins: int = _N_FFT_BINS) -> np.ndarray:
    """Extract 36 + n_fft_bins scalar features from a complex IQ window.

    The input is de-meaned and RMS-normalised before feature computation so
    that the vector is power-invariant and centre-frequency invariant.
    """
    iq = iq[np.isfinite(iq.real) & np.isfinite(iq.imag)]
    if iq.size < 16:
        raise ValueError("IQ window too short for feature extraction (need ≥ 16 samples)")
    iq = iq.astype(np.complex128, copy=False)
    iq = iq - np.mean(iq)
    rms = float(np.sqrt(np.mean(np.abs(iq) ** 2)))
    if not np.isfinite(rms) or rms <= 0:
        raise ValueError("IQ window has zero or invalid RMS power")
    iq = iq / rms

    amp = np.abs(iq).astype(np.float64)
    power = amp * amp
    real = iq.real
    imag = iq.imag
    phase = np.unwrap(np.angle(iq))
    phase_diff = np.diff(phase)

    real_std = float(np.std(real)) or 1e-12
    imag_std = float(np.std(imag)) or 1e-12
    iq_corr = float(np.mean((real - np.mean(real)) * (imag - np.mean(imag))) / (real_std * imag_std))
    papr = float(np.max(power) / (np.mean(power) + 1e-12))
    zcr_r = float(np.mean(np.diff(np.signbit(real)) != 0))
    zcr_i = float(np.mean(np.diff(np.signbit(imag)) != 0))

    spectrum = np.abs(np.fft.fftshift(np.fft.fft(iq * np.hanning(iq.size)))) ** 2 + 1e-12
    freqs = np.linspace(-0.5, 0.5, spectrum.size, endpoint=False)
    total = float(np.sum(spectrum))
    centroid = float(np.sum(freqs * spectrum) / total)
    spread = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spectrum) / total))
    flatness = float(math.exp(float(np.mean(np.log(spectrum)))) / float(np.mean(spectrum)))
    band_energy = np.array(
        [np.sum(b) / total for b in np.array_split(spectrum, n_fft_bins)],
        dtype=np.float32,
    )

    values = [
        float(np.mean(amp)), float(np.std(amp)), float(np.min(amp)), float(np.max(amp)),
        float(np.percentile(amp, 10)), float(np.percentile(amp, 50)), float(np.percentile(amp, 90)),
        float(np.mean(power)), float(np.std(power)),
        float(np.mean(real)), real_std,
        float(np.mean(imag)), imag_std,
        float(np.mean(phase_diff)), float(np.std(phase_diff)),
        float(np.percentile(phase_diff, 10)), float(np.percentile(phase_diff, 90)),
        iq_corr, papr, zcr_r, zcr_i,
        centroid, spread, flatness,
    ]
    return np.concatenate([np.asarray(values, dtype=np.float32), band_energy])
