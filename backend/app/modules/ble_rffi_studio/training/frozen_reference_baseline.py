"""RQ2's 4th model branch (2026-08-08): a simple, frozen morphological/coarse
time-frequency reference baseline -- the branch the audit found genuinely
missing alongside the three already-implemented ones (engineered features +
classical ML, CNN1D on raw I/Q, CNN2D on spectrograms). "Frozen" means no
iterative optimization at all: fit() computes one per-class centroid (the
mean of morphological_coarse_tf_representation vectors) and nothing else --
no gradient descent, no hyperparameter search. Classification is nearest
centroid by Euclidean distance, converted to a probability distribution via
a softmax over negative distances (the standard nearest-centroid-to-
probability conversion, not a fitted model).

Same build/fit/predict_proba/classes interface as BaselineModelTrainer,
deliberately, so TrainingService's orchestration around it (metrics,
predictions, latency measurement) reads the same way a reader already
familiar with run_baseline expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SUPPORTED_MODEL_TYPES = ("frozen_morphological_baseline",)


@dataclass
class _FrozenCentroidModel:
    class_order: list[str]
    centroids: np.ndarray  # [n_classes, n_features]


class FrozenReferenceBaselineTrainer:
    def build(self, model_type: str, random_seed: int, hyperparameters: dict[str, Any] | None = None) -> _FrozenCentroidModel:
        if model_type not in SUPPORTED_MODEL_TYPES:
            raise ValueError(f"UNSUPPORTED_FROZEN_REFERENCE_MODEL_TYPE:{model_type}")
        # random_seed/hyperparameters accepted for interface parity with
        # BaselineModelTrainer/CnnTrainer -- genuinely unused: a frozen
        # nearest-centroid template has nothing stochastic or tunable to seed.
        return _FrozenCentroidModel(class_order=[], centroids=np.zeros((0, 0)))

    def fit(self, model: _FrozenCentroidModel, X_train: np.ndarray, y_train: list[str]) -> _FrozenCentroidModel:
        class_order = sorted(set(y_train))
        y_arr = np.asarray(y_train)
        centroids = np.stack([X_train[y_arr == label].mean(axis=0) for label in class_order])
        model.class_order = class_order
        model.centroids = centroids
        return model

    def predict_proba(self, model: _FrozenCentroidModel, X: np.ndarray) -> np.ndarray:
        if len(X) == 0:
            return np.zeros((0, len(model.class_order)))
        # [n_samples, n_classes] Euclidean distance to each frozen centroid.
        distances = np.linalg.norm(X[:, np.newaxis, :] - model.centroids[np.newaxis, :, :], axis=2)
        # Softmax over negative distances: the closest centroid gets the
        # highest probability, strictly decreasing with distance -- a
        # standard, deterministic distance-to-probability conversion, not a
        # second fitted model.
        neg_distances = -distances
        shifted = neg_distances - neg_distances.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        return exp / exp.sum(axis=1, keepdims=True)

    def classes(self, model: _FrozenCentroidModel) -> list[str]:
        return list(model.class_order)
