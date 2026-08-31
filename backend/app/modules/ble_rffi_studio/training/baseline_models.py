"""Reference/baseline models (Fase 3): Logistic Regression, SVM (RBF), Random
Forest, all operating on the feature_vector representation profile. These
exist to give every later model (CNN1D/CNN2D) a comparable, simple baseline
-- not to be the final answer.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC

SUPPORTED_MODEL_TYPES = ("logistic_regression", "svm_rbf", "random_forest")


class BaselineModelTrainer:
    def build(self, model_type: str, random_seed: int, hyperparameters: dict[str, Any] | None = None) -> Any:
        hyperparameters = hyperparameters or {}
        if model_type == "logistic_regression":
            return LogisticRegression(random_state=random_seed, max_iter=hyperparameters.get("max_iter", 1000), C=hyperparameters.get("C", 1.0))
        if model_type == "svm_rbf":
            return SVC(kernel="rbf", probability=True, random_state=random_seed, C=hyperparameters.get("C", 1.0), gamma=hyperparameters.get("gamma", "scale"))
        if model_type == "random_forest":
            return RandomForestClassifier(random_state=random_seed, n_estimators=hyperparameters.get("n_estimators", 100), max_depth=hyperparameters.get("max_depth"))
        raise ValueError(f"UNSUPPORTED_BASELINE_MODEL_TYPE:{model_type}")

    def fit(self, model: Any, X_train: np.ndarray, y_train: np.ndarray) -> Any:
        model.fit(X_train, y_train)
        return model

    def predict_proba(self, model: Any, X: np.ndarray) -> np.ndarray:
        return model.predict_proba(X)

    def classes(self, model: Any) -> list[str]:
        return list(model.classes_)
