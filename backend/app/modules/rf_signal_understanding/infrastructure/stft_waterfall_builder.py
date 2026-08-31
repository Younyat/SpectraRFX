from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

from app.modules.rf_signal_understanding.infrastructure.image_utils import normalize_to_uint8, write_grayscale_png


class STFTWaterfallBuilder:
    def build(
        self,
        iq_samples: np.ndarray,
        sample_rate_hz: float,
        center_frequency_hz: float,
        n_fft: int,
        hop_length: int,
        window: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        if iq_samples.size == 0:
            raise ValueError("I/Q input is empty")
        noverlap = max(0, int(n_fft) - int(hop_length))
        freqs, times, stft = signal.stft(
            iq_samples,
            fs=float(sample_rate_hz),
            window=window,
            nperseg=int(n_fft),
            noverlap=noverlap,
            nfft=int(n_fft),
            boundary=None,
            padded=False,
            return_onesided=False,
        )
        order = np.argsort(freqs)
        freqs = freqs[order] + float(center_frequency_hz)
        power_db = 20.0 * np.log10(np.abs(stft[order, :]).T + 1e-12)
        power_db = np.asarray(power_db, dtype=np.float32)
        power_min = float(np.percentile(power_db, 2))
        power_max = float(np.percentile(power_db, 99))

        waterfall_path = output_dir / "waterfall.npy"
        image_path = output_dir / "waterfall.png"
        np.save(waterfall_path, power_db)
        write_grayscale_png(image_path, normalize_to_uint8(power_db, power_min, power_max))

        return {
            "waterfall_matrix": power_db,
            "waterfall_matrix_path": str(waterfall_path),
            "waterfall_image_path": str(image_path),
            "time_axis_s": [float(value) for value in times],
            "freq_axis_hz": [float(value) for value in freqs],
            "power_db_min": power_min,
            "power_db_max": power_max,
        }
