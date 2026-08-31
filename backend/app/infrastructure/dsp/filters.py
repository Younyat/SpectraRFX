from __future__ import annotations

import numpy as np

from app.domain.value_objects.filter_config import FilterDesignConfig


class SpectrumFilters:
    def apply(self, samples: np.ndarray, config: FilterDesignConfig) -> np.ndarray:
        if samples.ndim != 1:
            raise ValueError("samples must be a 1D array")

        if not config.enabled:
            return samples.astype(np.complex64, copy=True)

        normalized = config.filter_type

        if normalized == "low_pass":
            return self._low_pass(samples, config.cutoff_hz, config.sample_rate_hz)

        if normalized == "high_pass":
            return self._high_pass(samples, config.cutoff_hz, config.sample_rate_hz)

        if normalized == "band_pass":
            return self._band_pass(samples, config.low_cut_hz, config.high_cut_hz, config.sample_rate_hz)

        if normalized in {"band_stop", "notch"}:
            return self._band_stop(samples, config.low_cut_hz, config.high_cut_hz, config.sample_rate_hz)

        raise ValueError(f"Unsupported filter type: {normalized}")

    def _fft_mask(
        self,
        sample_count: int,
        sample_rate_hz: float,
        predicate,
    ) -> np.ndarray:
        freqs = np.fft.fftfreq(sample_count, d=1.0 / sample_rate_hz)
        mask = predicate(freqs)
        return mask.astype(np.float32)

    def _low_pass(self, samples: np.ndarray, cutoff_hz: float | None, sample_rate_hz: float) -> np.ndarray:
        if cutoff_hz is None:
            raise ValueError("cutoff_hz is required for low-pass")
        X = np.fft.fft(samples)
        mask = self._fft_mask(len(samples), sample_rate_hz, lambda f: np.abs(f) <= cutoff_hz)
        y = np.fft.ifft(X * mask)
        return y.astype(np.complex64)

    def _high_pass(self, samples: np.ndarray, cutoff_hz: float | None, sample_rate_hz: float) -> np.ndarray:
        if cutoff_hz is None:
            raise ValueError("cutoff_hz is required for high-pass")
        X = np.fft.fft(samples)
        mask = self._fft_mask(len(samples), sample_rate_hz, lambda f: np.abs(f) >= cutoff_hz)
        y = np.fft.ifft(X * mask)
        return y.astype(np.complex64)

    def _band_pass(
        self,
        samples: np.ndarray,
        low_cut_hz: float | None,
        high_cut_hz: float | None,
        sample_rate_hz: float,
    ) -> np.ndarray:
        if low_cut_hz is None or high_cut_hz is None:
            raise ValueError("low_cut_hz and high_cut_hz are required for band-pass")
        X = np.fft.fft(samples)
        mask = self._fft_mask(
            len(samples),
            sample_rate_hz,
            lambda f: (np.abs(f) >= low_cut_hz) & (np.abs(f) <= high_cut_hz),
        )
        y = np.fft.ifft(X * mask)
        return y.astype(np.complex64)

    def _band_stop(
        self,
        samples: np.ndarray,
        low_cut_hz: float | None,
        high_cut_hz: float | None,
        sample_rate_hz: float,
    ) -> np.ndarray:
        if low_cut_hz is None or high_cut_hz is None:
            raise ValueError("low_cut_hz and high_cut_hz are required for band-stop")
        X = np.fft.fft(samples)
        mask = self._fft_mask(
            len(samples),
            sample_rate_hz,
            lambda f: ~((np.abs(f) >= low_cut_hz) & (np.abs(f) <= high_cut_hz)),
        )
        y = np.fft.ifft(X * mask)
        return y.astype(np.complex64)