"""Design correction #10: any scaler that learns parameters must fit()
exclusively on TRAIN and only ever transform() VALIDATION/TEST. This wrapper
makes that a runtime error instead of a convention someone can forget."""
from __future__ import annotations

import numpy as np
from sklearn.preprocessing import StandardScaler


class TrainOnlyScaler:
    def __init__(self) -> None:
        self._scaler = StandardScaler()
        self._fitted = False

    def fit(self, X: np.ndarray, split: str) -> "TrainOnlyScaler":
        if split != "TRAIN":
            raise ValueError(f"SCALER_MUST_FIT_ONLY_ON_TRAIN:got_split={split}")
        self._scaler.fit(X)
        self._fitted = True
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise ValueError("SCALER_NOT_FITTED:call fit(X, split='TRAIN') first")
        return self._scaler.transform(X)
