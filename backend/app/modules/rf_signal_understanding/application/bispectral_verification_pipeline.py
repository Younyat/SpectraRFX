from __future__ import annotations

import numpy as np

from app.modules.rf_signal_understanding.infrastructure.bispectral_feature_extractor import BispectralFeatureExtractor


class BispectralVerificationPipeline:
    def __init__(self) -> None:
        self.extractor = BispectralFeatureExtractor()

    def verify(self, iq_segment: np.ndarray) -> dict[str, object]:
        return self.extractor.extract(iq_segment)
