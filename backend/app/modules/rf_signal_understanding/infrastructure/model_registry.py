from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class ModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir

    def list_models(self) -> list[dict[str, Any]]:
        model_types = ["region_detector", "waterfall_classifier", "mlp_spectral_classifier", "bispectral_fusion"]
        summaries: list[dict[str, Any]] = []
        for model_type in model_types:
            model_dir = self.models_dir / model_type
            model_dir.mkdir(parents=True, exist_ok=True)
            files = [path for path in model_dir.iterdir() if path.is_file()]
            metadata_path = model_dir / "metadata.json"
            metadata: dict[str, Any] = {"files": [path.name for path in files]}
            if metadata_path.exists():
                try:
                    with metadata_path.open("r", encoding="utf-8") as file:
                        metadata.update(json.load(file))
                except json.JSONDecodeError:
                    metadata["metadata_error"] = "metadata.json could not be decoded"
            summaries.append(
                {
                    "model_id": f"{model_type}_v1",
                    "model_type": model_type,
                    "status": "trained" if (model_dir / "model.npz").exists() or files else "not_trained",
                    "path": str(model_dir),
                    "trained": (model_dir / "model.npz").exists() or bool(files),
                    "metadata": metadata,
                }
            )
        return summaries
