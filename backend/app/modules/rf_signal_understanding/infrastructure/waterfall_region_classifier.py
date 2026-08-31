from __future__ import annotations

from typing import Any

import numpy as np


class WaterfallRegionClassifier:
    model_id = "waterfall_classifier_heuristic_v1"

    def classify(self, region_waterfall_matrix: np.ndarray, bbox: dict[str, Any]) -> dict[str, Any]:
        matrix = np.asarray(region_waterfall_matrix, dtype=np.float32)
        bandwidth = float(bbox.get("occupied_bandwidth_hz", 0.0))
        duration = float(bbox.get("time_end_s", 0.0)) - float(bbox.get("time_start_s", 0.0))
        if matrix.size == 0:
            label, confidence = "unknown", 0.2
        else:
            temporal_variance = float(np.var(np.mean(matrix, axis=1))) if matrix.shape[0] > 1 else 0.0
            freq_variance = float(np.var(np.mean(matrix, axis=0))) if matrix.shape[1] > 1 else 0.0
            center_hz = float(bbox.get("center_frequency_hz", 0.0))
            fm_band = 87_500_000 <= center_hz <= 108_000_000
            if fm_band and 80_000 <= bandwidth <= 350_000:
                label, confidence = "fm_broadcast_like", 0.72
            elif fm_band:
                label, confidence = "fm_broadcast_like", 0.54
            elif bandwidth > 5_000_000:
                label, confidence = "ofdm_like", 0.62
            elif bandwidth > 1_000_000:
                label, confidence = "spread_spectrum_like", 0.58
            elif duration < 0.75 and temporal_variance > freq_variance * 0.25:
                label, confidence = "ook_like", 0.66
            elif freq_variance > temporal_variance:
                label, confidence = "fsk_like", 0.58
            else:
                label, confidence = "unknown", 0.35
        top_k = self._top_k(label, confidence)
        return {
            "classifier": "cnn_waterfall_classifier",
            "model_id": self.model_id,
            "label": label,
            "confidence": confidence,
            "top_k": top_k,
        }

    def _top_k(self, label: str, confidence: float) -> list[dict[str, float | str]]:
        alternatives = ["fm_broadcast_like", "ook_like", "fsk_like", "psk_like", "ofdm_like", "unknown"]
        scores = {name: 0.02 for name in alternatives}
        scores[label] = confidence
        remaining = max(0.0, 1.0 - confidence)
        for name in alternatives:
            if name != label:
                scores[name] += remaining / max(len(alternatives) - 1, 1)
        return [{"label": name, "score": float(score)} for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]]
