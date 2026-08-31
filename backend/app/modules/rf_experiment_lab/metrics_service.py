from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np


class MetricsService:
    def classification_metrics(self, y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
        labels = sorted(set(y_true) | set(y_pred))
        if not labels:
            return self.empty_classification_metrics()
        index = {label: idx for idx, label in enumerate(labels)}
        matrix = np.zeros((len(labels), len(labels)), dtype=int)
        for truth, pred in zip(y_true, y_pred):
            matrix[index[truth], index[pred]] += 1
        accuracy = float(np.trace(matrix) / max(np.sum(matrix), 1))
        per_class = {}
        f1_values = []
        recalls = []
        precisions = []
        for label in labels:
            i = index[label]
            tp = float(matrix[i, i])
            fp = float(np.sum(matrix[:, i]) - tp)
            fn = float(np.sum(matrix[i, :]) - tp)
            precision = tp / max(tp + fp, 1.0)
            recall = tp / max(tp + fn, 1.0)
            f1 = 2 * precision * recall / max(precision + recall, 1e-12)
            per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": int(np.sum(matrix[i, :]))}
            precisions.append(precision)
            recalls.append(recall)
            f1_values.append(f1)
        return {
            "accuracy": accuracy,
            "balanced_accuracy": float(np.mean(recalls)),
            "macro_f1": float(np.mean(f1_values)),
            "precision_macro": float(np.mean(precisions)),
            "recall_macro": float(np.mean(recalls)),
            "confusion_matrix": {"labels": labels, "matrix": matrix.tolist()},
            "classification_report": per_class,
        }

    def empty_classification_metrics(self) -> dict[str, Any]:
        return {
            "accuracy": None,
            "balanced_accuracy": None,
            "macro_f1": None,
            "precision_macro": None,
            "recall_macro": None,
            "confusion_matrix": {"labels": [], "matrix": []},
            "classification_report": {},
        }

    def region_detection_metrics(self, regions: list[dict[str, Any]], latency_ms: float | None = None) -> dict[str, Any]:
        areas = []
        freq_spans = []
        time_spans = []
        for region in regions:
            bounds = region.get("pixel_bounds", {}) if isinstance(region.get("pixel_bounds"), dict) else {}
            if bounds:
                areas.append(
                    max(int(bounds.get("time_end", 0)) - int(bounds.get("time_start", 0)) + 1, 0)
                    * max(int(bounds.get("freq_end", 0)) - int(bounds.get("freq_start", 0)) + 1, 0)
                )
            freq_spans.append(float(region.get("occupied_bandwidth_hz") or 0.0))
            time_spans.append(max(float(region.get("time_end_s") or 0.0) - float(region.get("time_start_s") or 0.0), 0.0))
        return {
            "latency_ms": latency_ms,
            "detected_regions": len(regions),
            "region_area_statistics": self._summary(areas),
            "region_frequency_span": self._summary(freq_spans),
            "region_time_span": self._summary(time_spans),
            "detector_counts": dict(Counter(str(region.get("detector", "unknown")) for region in regions)),
        }

    def _summary(self, values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {"count": 0, "min": None, "max": None, "mean": None}
        arr = np.asarray(values, dtype=np.float64)
        return {"count": int(arr.size), "min": float(np.min(arr)), "max": float(np.max(arr)), "mean": float(np.mean(arr))}
