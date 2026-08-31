from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ScientificTraceability:
    def __init__(self, references_path: Path) -> None:
        self.references_path = references_path

    def references(self) -> dict[str, Any]:
        with self.references_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def for_steps(self, steps: list[str]) -> list[dict[str, str]]:
        refs = self.references()
        trace: list[dict[str, str]] = []
        step_to_key = {
            "waterfall_generation": "stft_waterfall",
            "region_detection": "region_detection",
            "object_detection": "object_detection",
            "mlp_spectral_classification": "mlp_spectral_classifier",
            "bispectral_verification": "bispectral_verification",
        }
        for step in steps:
            key = step_to_key.get(step, step)
            for paper in refs.get(key, {}).get("papers", []):
                trace.append(
                    {
                        "module_step": step,
                        "paper_title": str(paper.get("title", "")),
                        "technique": str(paper.get("technique", "")),
                        "used_for": str(paper.get("used_for", "")),
                    }
                )
        return trace
