from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import numpy as np

from app.application.interfaces.waterfall_provider import WaterfallProvider
from app.domain.entities.analyzer_settings import AnalyzerSettings
from app.domain.entities.waterfall_frame import WaterfallFrame, WaterfallMetadata


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockWaterfallProvider(WaterfallProvider):
    def __init__(self) -> None:
        self._history: deque[WaterfallFrame] = deque()
        self._row_index = 0
        self._rng = np.random.default_rng()

    def get_live_waterfall_frame(self, settings: AnalyzerSettings) -> WaterfallFrame:
        points = settings.resolution.fft_size
        start_hz = settings.frequency.start_frequency_hz
        stop_hz = settings.frequency.stop_frequency_hz
        freqs = np.linspace(start_hz, stop_hz, points, dtype=np.float64)

        noise = self._rng.normal(loc=-110.0, scale=3.0, size=points).astype(np.float32)

        moving_center = settings.frequency.center_frequency_hz + np.sin(self._row_index / 10.0) * 40_000.0

        levels = (
            noise
            + self._gaussian_peak(freqs, moving_center, 30_000.0, 35.0)
            + self._gaussian_peak(freqs, settings.frequency.center_frequency_hz - 150_000.0, 18_000.0, 15.0)
        )

        normalized = self._normalize(
            levels,
            settings.display.min_level_db,
            settings.display.max_level_db,
        )

        frame = WaterfallFrame(
            timestamp_utc=_utc_now_iso(),
            center_frequency_hz=settings.frequency.center_frequency_hz,
            span_hz=settings.frequency.span_hz,
            start_frequency_hz=start_hz,
            stop_frequency_hz=stop_hz,
            sample_rate_hz=settings.frequency.sample_rate_hz,
            row_index=self._row_index,
            frequencies_hz=freqs.tolist(),
            levels_db=levels.astype(np.float64).tolist(),
            normalized_levels=normalized.astype(np.float64).tolist(),
            metadata=WaterfallMetadata(
                color_map=settings.display.color_map,
                min_level_db=settings.display.min_level_db,
                max_level_db=settings.display.max_level_db,
                history_size=settings.display.waterfall_history_size,
                averaging_enabled=settings.trace.averaging_enabled,
                smoothing_enabled=settings.trace.smoothing_enabled,
            ),
        )

        self._history.append(frame)
        self._row_index += 1

        while len(self._history) > settings.display.waterfall_history_size:
            self._history.popleft()

        return frame

    def get_last_waterfall_frame(self) -> WaterfallFrame | None:
        if not self._history:
            return None
        return self._history[-1]

    def clear_history(self) -> None:
        self._history.clear()
        self._row_index = 0

    def get_history_size(self) -> int:
        return len(self._history)

    @staticmethod
    def _gaussian_peak(
        freqs_hz: np.ndarray,
        center_hz: float,
        sigma_hz: float,
        amplitude_db: float,
    ) -> np.ndarray:
        return amplitude_db * np.exp(-0.5 * ((freqs_hz - center_hz) / sigma_hz) ** 2)

    @staticmethod
    def _normalize(levels_db: np.ndarray, min_db: float, max_db: float) -> np.ndarray:
        clipped = np.clip(levels_db, min_db, max_db)
        return ((clipped - min_db) / (max_db - min_db)).astype(np.float32)