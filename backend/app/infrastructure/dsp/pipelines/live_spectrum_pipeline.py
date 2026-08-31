from __future__ import annotations
import numpy as np
from app.infrastructure.dsp.fft_engine import FFTEngine

class LiveSpectrumPipeline:
    def __init__(self, sample_rate: float = 2_000_000.0, fft_size: int = 4096):
        self.sample_rate = sample_rate
        self.fft_engine = FFTEngine(fft_size)
    
    def process(self, iq_samples: np.ndarray, center_freq: float) -> dict:
        power_db = self.fft_engine.compute_power_db(iq_samples)
        freqs = np.fft.fftfreq(self.fft_engine.fft_size, 1/self.sample_rate)[:len(power_db)]
        freqs = freqs + center_freq
        return {"frequencies": freqs, "power_db": power_db}
            noise_floor_db=noise_floor_db,
        )

        occupied = self._detectors.occupied_bandwidth(
            frequencies_hz=abs_freqs_hz,
            levels_db=processed_db,
            threshold_db=noise_floor_db + 6.0,
        )

        statistics = SpectrumStatistics(
            peak_frequency_hz=peak.peak_frequency_hz,
            peak_level_db=peak.peak_level_db,
            noise_floor_db=noise_floor_db,
            mean_level_db=mean_level_db,
            occupied_bandwidth_hz=None if occupied is None else occupied.bandwidth_hz,
            channel_power_db=None,
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

        return SpectrumFrame(
            timestamp_utc=_utc_now_iso(),
            center_frequency_hz=settings.frequency.center_frequency_hz,
            span_hz=settings.frequency.span_hz,
            start_frequency_hz=settings.frequency.start_frequency_hz,
            stop_frequency_hz=settings.frequency.stop_frequency_hz,
            sample_rate_hz=settings.frequency.sample_rate_hz,
            frequencies_hz=abs_freqs_hz.astype(np.float64).tolist(),
            levels_db=processed_db.astype(np.float64).tolist(),
            statistics=statistics,
            metadata=metadata,
        )