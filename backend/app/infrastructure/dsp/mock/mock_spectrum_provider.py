from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from app.application.interfaces.spectrum_provider import SpectrumProvider
from app.domain.entities.analyzer_settings import AnalyzerSettings
from app.domain.entities.spectrum_frame import (
    SpectrumFrame,
    SpectrumStatistics,
    TraceMetadata,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockSpectrumProvider(SpectrumProvider):
    def __init__(self) -> None:
        self._last_frame: SpectrumFrame | None = None
        self._rng = np.random.default_rng()

    def get_live_spectrum(self, settings: AnalyzerSettings) -> SpectrumFrame:
        points = settings.resolution.fft_size
        start_hz = settings.frequency.start_frequency_hz
        stop_hz = settings.frequency.stop_frequency_hz

        freqs = np.linspace(start_hz, stop_hz, points, dtype=np.float64)

        base_noise = self._rng.normal(loc=-105.0, scale=2.5, size=points).astype(np.float32)

        signal_1_center = settings.frequency.center_frequency_hz
        signal_2_center = settings.frequency.center_frequency_hz + settings.frequency.span_hz * 0.22
        signal_3_center = settings.frequency.center_frequency_hz - settings.frequency.span_hz * 0.18

        levels = (
            base_noise
            + self._gaussian_peak(freqs, signal_1_center, 25_000.0, 42.0)
            + self._gaussian_peak(freqs, signal_2_center, 50_000.0, 25.0)
            + self._gaussian_peak(freqs, signal_3_center, 12_000.0, 18.0)
        )

        peak_index = int(np.argmax(levels))
        peak_frequency_hz = float(freqs[peak_index])
        peak_level_db = float(levels[peak_index])
        noise_floor_db = float(np.percentile(levels, 20))
        mean_level_db = float(np.mean(levels))
        snr_db = float(peak_level_db - noise_floor_db)

        statistics = SpectrumStatistics(
            peak_frequency_hz=peak_frequency_hz,
            peak_level_db=peak_level_db,
            noise_floor_db=noise_floor_db,
            mean_level_db=mean_level_db,
            occupied_bandwidth_hz=55_000.0,
            channel_power_db=peak_level_db - 3.0,
            snr_db=snr_db,
        )

        metadata = TraceMetadata(
            detector_mode=settings.trace.detector_mode,
            trace_mode=settings.trace.trace_mode,
            fft_size=settings.resolution.fft_size,
            rbw_hz=settings.resolution.rbw_hz,
            vbw_hz=settings.resolution.vbw_hz,
            reference_level_db=settings.display.reference_level_db,
            min_level_db=settings.display.min_level_db,
            max_level_db=settings.display.max_level_db,
            averaging_enabled=settings.trace.averaging_enabled,
            smoothing_enabled=settings.trace.smoothing_enabled,
        )

        frame = SpectrumFrame(
            timestamp_utc=_utc_now_iso(),
            center_frequency_hz=settings.frequency.center_frequency_hz,
            span_hz=settings.frequency.span_hz,
            start_frequency_hz=start_hz,
            stop_frequency_hz=stop_hz,
            sample_rate_hz=settings.frequency.sample_rate_hz,
            frequencies_hz=freqs.tolist(),
            levels_db=levels.astype(np.float64).tolist(),
            statistics=statistics,
            metadata=metadata,
        )

        self._last_frame = frame
        return frame

    def get_last_spectrum(self) -> SpectrumFrame | None:
        return self._last_frame

    def clear_trace_state(self) -> None:
        self._last_frame = None

    def reset_peak_tracking(self) -> None:
        return None

    @staticmethod
    def _gaussian_peak(
        freqs_hz: np.ndarray,
        center_hz: float,
        sigma_hz: float,
        amplitude_db: float,
    ) -> np.ndarray:
        return amplitude_db * np.exp(-0.5 * ((freqs_hz - center_hz) / sigma_hz) ** 2)