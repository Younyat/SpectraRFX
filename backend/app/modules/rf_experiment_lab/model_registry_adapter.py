from __future__ import annotations

from typing import Any


class ModelRegistryAdapter:
    def __init__(self, mlops_service: Any | None = None) -> None:
        self.mlops_service = mlops_service

    def list_current_models(self) -> list[dict[str, Any]]:
        if self.mlops_service is None or not hasattr(self.mlops_service, "list_models"):
            return []
        try:
            models = self.mlops_service.list_models()
        except Exception:
            return []
        return models if isinstance(models, list) else []

    def describe_integration_policy(self) -> dict[str, Any]:
        return {
            "policy": "Experimental models are candidates only until strict validation passes.",
            "current_baseline_preserved": True,
            "primary_fingerprinting_warning": "The current NumPy/softmax baseline is not presented as physical deep-learning RFF.",
        }
