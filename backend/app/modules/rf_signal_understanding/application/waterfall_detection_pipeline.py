from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.rf_signal_understanding.infrastructure.ml_region_detector import MLRegionDetector
from app.modules.rf_signal_understanding.infrastructure.morphological_region_detector import MorphologicalRegionDetector


class WaterfallDetectionPipeline:
    def __init__(self) -> None:
        self.morphological = MorphologicalRegionDetector()
        self.ml = MLRegionDetector()

    def detect(self, waterfall_matrix: np.ndarray, time_axis_s: list[float], freq_axis_hz: list[float]) -> list[dict[str, Any]]:
        regions = self.morphological.detect(waterfall_matrix, time_axis_s, freq_axis_hz)
        regions.extend(self.ml.detect(waterfall_matrix, time_axis_s, freq_axis_hz))
        return regions
