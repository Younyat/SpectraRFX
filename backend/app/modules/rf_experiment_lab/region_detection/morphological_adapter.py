from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.rf_signal_understanding.infrastructure.morphological_region_detector import MorphologicalRegionDetector


class MorphologicalHeuristicAdapter:
    detector_id = "morphological_heuristic"
    aliases = {"morphological", "baseline_visual_region_detector", "morphological_heuristic"}

    def __init__(self) -> None:
        self._detector = MorphologicalRegionDetector()

    def detect(
        self,
        waterfall_matrix: np.ndarray,
        time_axis_s: list[float],
        freq_axis_hz: list[float],
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        parameters = parameters or {}
        regions = self._detector.detect(
            waterfall_matrix,
            time_axis_s,
            freq_axis_hz,
            threshold_percentile=float(parameters.get("threshold_percentile", 88.0)),
            min_pixels=int(parameters.get("min_region_area", parameters.get("min_pixels", 16))),
            max_regions=int(parameters.get("max_regions", 32)),
        )
        for region in regions:
            region["detector"] = self.detector_id
            region["baseline_visual_region_detector"] = True
        return regions

    def status(self) -> dict[str, Any]:
        return {
            "id": self.detector_id,
            "available": True,
            "trainable": False,
            "fallback": True,
            "note": "Uses the existing RF Signal Understanding morphological detector without replacing it.",
        }
