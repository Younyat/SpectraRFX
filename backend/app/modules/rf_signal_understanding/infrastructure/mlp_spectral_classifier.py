from __future__ import annotations

from typing import Any

import numpy as np


class MLPSpectralClassifier:
    model_id = "mlp_spectral_heuristic_v1"

    def classify(self, region_waterfall_matrix: np.ndarray, fixed_width: int = 128) -> dict[str, Any]:
        matrix = np.asarray(region_waterfall_matrix, dtype=np.float32)
        if matrix.size == 0:
            membership = {"unknown": 1.0}
        else:
            votes: dict[str, int] = {}
            for row in matrix:
                resized = np.interp(np.linspace(0, row.size - 1, fixed_width), np.arange(row.size), row)
                label = self._classify_row(resized)
                votes[label] = votes.get(label, 0) + 1
            total = max(sum(votes.values()), 1)
            membership = {label: count / total for label, count in votes.items()}
            membership.setdefault("unknown", 0.0)
        label, confidence = max(membership.items(), key=lambda item: item[1])
        return {
            "classifier": "mlp_spectral_classifier",
            "model_id": self.model_id,
            "temporal_membership": membership,
            "label": label,
            "confidence": float(confidence),
        }

    def _classify_row(self, row: np.ndarray) -> str:
        centered = row - np.mean(row)
        active = centered > max(np.std(centered), 1e-6)
        occupancy = float(np.mean(active))
        transitions = int(np.sum(active[1:] != active[:-1]))
        if occupancy > 0.45:
            return "wideband_noise_like"
        if transitions >= 4:
            return "fsk_like"
        if 0.02 <= occupancy <= 0.25:
            return "ook_like"
        return "unknown"
