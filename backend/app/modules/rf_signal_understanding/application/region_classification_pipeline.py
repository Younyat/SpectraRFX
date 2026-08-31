from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.rf_signal_understanding.infrastructure.mlp_spectral_classifier import MLPSpectralClassifier
from app.modules.rf_signal_understanding.infrastructure.waterfall_region_classifier import WaterfallRegionClassifier


class RegionClassificationPipeline:
    def __init__(self) -> None:
        self.visual = WaterfallRegionClassifier()
        self.mlp = MLPSpectralClassifier()

    def classify(self, region_waterfall_matrix: np.ndarray, region: dict[str, Any]) -> dict[str, Any]:
        return {
            "visual": self.visual.classify(region_waterfall_matrix, region),
            "mlp": self.mlp.classify(region_waterfall_matrix),
        }
