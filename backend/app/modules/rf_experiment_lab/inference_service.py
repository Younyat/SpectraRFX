from __future__ import annotations

import csv
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RFExperimentInferenceService:
    def __init__(self, storage_root: Path, result_store) -> None:
        self.root = storage_root / "rf_experiment_lab"
        self.result_store = result_store
        self.inference_dir = self.root / "inference_results"
        self.inference_dir.mkdir(parents=True, exist_ok=True)

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        model_refs = payload.get("experiment_ids") or payload.get("model_experiment_ids") or []
        if not model_refs:
            latest = self.result_store.list_results()[:3]
            model_refs = [item["experiment_id"] for item in latest]
        source = self._source_descriptor(payload)
        predictions = [self._predict_from_result(str(ref), source) for ref in model_refs]
        agreement = self._agreement(predictions)
        latency_ms = (time.perf_counter() - started) * 1000.0
        result = {
            "inference_id": f"rfexp_pred_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_sample_id": source["input_sample_id"],
            "input_source_type": source["source_type"],
            "dataset_version": self._first(predictions, "dataset_version"),
            "model_id": ",".join(str(item.get("model_id")) for item in predictions),
            "representation_used": sorted({str(item.get("representation_used")) for item in predictions if item.get("representation_used")}),
            "prediction_result": {
                "predictions": predictions,
                "agreement": agreement,
                "latency_ms": latency_ms,
                "top_prediction": agreement.get("consensus_label"),
                "confidence": agreement.get("consensus_confidence"),
                "top_k": agreement.get("top_k"),
            },
        }
        if payload.get("persist", True):
            path = self.inference_dir / f"{result['inference_id']}.json"
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            result["result_path"] = str(path)
        return result

    def compare_on_region(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("source_type", "marker_region")
        return self.predict(payload)

    def _predict_from_result(self, experiment_id: str, source: dict[str, Any]) -> dict[str, Any]:
        try:
            detail = self.result_store.get_experiment_detail(experiment_id)
        except Exception:
            return {
                "model_id": experiment_id,
                "status": "model_not_found",
                "predicted_label": "unknown",
                "confidence": 0.0,
                "top_k": [],
            }
        result_path = Path(str(detail["result_path"]))
        rows = self._read_predictions(result_path / "predictions.csv")
        label_counts = Counter(row.get("predicted_label") for row in rows if row.get("predicted_label"))
        top = label_counts.most_common(3)
        predicted = top[0][0] if top else "unknown"
        confidence_values = [float(row.get("confidence") or 0.0) for row in rows if row.get("predicted_label") == predicted]
        confidence = sum(confidence_values) / max(len(confidence_values), 1) if top else 0.0
        config = detail.get("config") if isinstance(detail.get("config"), dict) else {}
        return {
            "model_id": detail.get("experiment_id"),
            "experiment_type": detail.get("experiment_type"),
            "dataset_version": detail.get("dataset_version") or self._safe_text(result_path / "dataset_version.txt"),
            "representation_used": config.get("input_representation") or self._representation_from_type(str(detail.get("experiment_type"))),
            "status": "predicted_from_trained_result_summary",
            "predicted_label": predicted,
            "confidence": confidence,
            "top_k": [{"label": label, "score": count / max(len(rows), 1)} for label, count in top],
            "latency_source": "result_package_prediction_summary",
            "source": source,
        }

    def _source_descriptor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_type": payload.get("source_type", "saved_capture"),
            "input_sample_id": payload.get("input_sample_id") or payload.get("capture_id") or payload.get("sample_id") or "live_or_region_input",
            "iq_path": payload.get("iq_path"),
            "metadata_path": payload.get("metadata_path"),
            "marker_region": payload.get("marker_region"),
            "frozen_frame": payload.get("frozen_frame"),
            "live_context": payload.get("live_context"),
        }

    def _agreement(self, predictions: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [item for item in predictions if item.get("status") != "model_not_found"]
        labels = [str(item.get("predicted_label")) for item in valid if item.get("predicted_label")]
        counts = Counter(labels)
        consensus, count = counts.most_common(1)[0] if counts else ("unknown", 0)
        confidence = sum(float(item.get("confidence") or 0.0) for item in valid if item.get("predicted_label") == consensus) / max(count, 1)
        return {
            "model_count": len(valid),
            "consensus_label": consensus,
            "consensus_confidence": confidence,
            "agreement": count == len(valid) and len(valid) > 1,
            "disagreement": len(counts) > 1,
            "votes": dict(counts),
            "top_k": [{"label": label, "score": value / max(len(valid), 1)} for label, value in counts.most_common(5)],
        }

    def _read_predictions(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    def _safe_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def _first(self, rows: list[dict[str, Any]], key: str) -> Any:
        return next((row.get(key) for row in rows if row.get(key)), None)

    def _representation_from_type(self, experiment_type: str) -> str:
        if "e1" in experiment_type:
            return "raw_iq"
        if "e3" in experiment_type:
            return "spectrogram_or_waterfall"
        if "e5" in experiment_type:
            return "fft_psd_features"
        return "unknown"
