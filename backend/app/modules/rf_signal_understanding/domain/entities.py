from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TimeFrequencyRegion:
    bbox_id: str
    time_start_s: float
    time_end_s: float
    freq_start_hz: float
    freq_end_hz: float
    center_frequency_hz: float
    occupied_bandwidth_hz: float
    detector: str
    confidence: float
    pixel_bounds: dict[str, int] = field(default_factory=dict)
    model_id: str | None = None

    def to_result(self) -> dict[str, Any]:
        result = {
            "bbox_id": self.bbox_id,
            "time_start_s": self.time_start_s,
            "time_end_s": self.time_end_s,
            "freq_start_hz": self.freq_start_hz,
            "freq_end_hz": self.freq_end_hz,
            "center_frequency_hz": self.center_frequency_hz,
            "occupied_bandwidth_hz": self.occupied_bandwidth_hz,
            "detector": self.detector,
            "confidence": self.confidence,
            "pixel_bounds": self.pixel_bounds,
        }
        if self.model_id:
            result["model_id"] = self.model_id
        return result
