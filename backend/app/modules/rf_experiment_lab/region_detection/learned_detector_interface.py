from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class LearnedWaterfallDetector(Protocol):
    detector_id: str

    def detect(
        self,
        waterfall_matrix: np.ndarray,
        time_axis_s: list[float],
        freq_axis_hz: list[float],
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...


class OptionalLearnedDetectorStub:
    def __init__(self, detector_id: str) -> None:
        self.detector_id = detector_id

    def detect(
        self,
        waterfall_matrix: np.ndarray,
        time_axis_s: list[float],
        freq_axis_hz: list[float],
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.detector_id} is not implemented or no trained detector is installed")

    def status(self) -> dict[str, Any]:
        return {
            "id": self.detector_id,
            "available": False,
            "trainable": True,
            "implementation_status": "not_implemented",
            "message": "Optional learned detector interface is registered; no trained detector is installed.",
        }
