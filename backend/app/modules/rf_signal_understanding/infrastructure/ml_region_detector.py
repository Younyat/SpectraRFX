from __future__ import annotations

from typing import Any


class MLRegionDetector:
    supported_detectors = ("ssd", "faster_rcnn")

    def detect(self, *args: Any, detector: str = "ssd", **kwargs: Any) -> list[dict[str, Any]]:
        if detector not in self.supported_detectors:
            raise ValueError(f"Unsupported detector: {detector}")
        return []

    def status(self) -> dict[str, Any]:
        return {
            "supported": list(self.supported_detectors),
            "trained_models_available": False,
            "note": "ML detector hooks are present; train-region-detector must provide a model before inference.",
        }
