from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.modules.rf_experiment_lab.experiment_config_schema import ExperimentConfig


class ExperimentResultStore:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "rf_experiment_lab"
        self.config_dir = self.root / "configs"
        self.results_dir = self.root / "results"
        self.reports_dir = self.root / "reports"
        for path in (self.config_dir, self.results_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_config(self, config: ExperimentConfig) -> dict[str, Any]:
        target = self.config_dir / f"{config.experiment_id}.json"
        target.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
        return {"experiment_id": config.experiment_id, "path": str(target)}

    def load_config(self, experiment_id: str) -> ExperimentConfig:
        path = self.config_dir / f"{experiment_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Experiment config not found: {experiment_id}")
        return ExperimentConfig.model_validate_json(path.read_text(encoding="utf-8"))

    def list_configs(self) -> list[dict[str, Any]]:
        configs = []
        for path in sorted(self.config_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            configs.append(
                {
                    "experiment_id": data.get("experiment_id", path.stem),
                    "stage": data.get("stage"),
                    "task": data.get("task"),
                    "technology": data.get("technology"),
                    "paper_reference": data.get("paper_reference"),
                    "path": str(path),
                }
            )
        return configs

    def create_result_folder(self, config: ExperimentConfig) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.results_dir / config.experiment_id / timestamp
        path.mkdir(parents=True, exist_ok=False)
        return path

    def write_experiment_artifacts(
        self,
        result_dir: Path,
        config: ExperimentConfig,
        metrics: dict[str, Any],
        split_definition: dict[str, Any] | None = None,
        detections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        (result_dir / "config.yaml").write_text(self._to_simple_yaml(config.model_dump()), encoding="utf-8")
        (result_dir / "paper_reference.txt").write_text(config.paper_reference + "\n", encoding="utf-8")
        (result_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (result_dir / "dataset_version.txt").write_text(config.dataset_version + "\n", encoding="utf-8")
        (result_dir / "model_summary.txt").write_text(self._model_summary(config), encoding="utf-8")
        (result_dir / "thresholds.json").write_text(json.dumps(config.parameters, indent=2), encoding="utf-8")
        if split_definition is not None:
            (result_dir / "split_definition.json").write_text(json.dumps(split_definition, indent=2), encoding="utf-8")
        if detections is not None:
            (result_dir / "detections.json").write_text(json.dumps(detections, indent=2), encoding="utf-8")
            (result_dir / "visual_debug_outputs").mkdir(exist_ok=True)
        self._write_empty_csv(result_dir / "predictions.csv", ["capture_id", "y_true", "y_pred", "confidence"])
        self._write_empty_csv(result_dir / "confusion_matrix.csv", ["label"])
        self._write_empty_csv(result_dir / "training_log.csv", ["epoch", "loss", "metric"])
        (result_dir / "classification_report.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
        return {"result_dir": str(result_dir), "files": sorted(path.name for path in result_dir.iterdir())}

    def write_e0_artifacts(
        self,
        result_dir: Path,
        config: ExperimentConfig,
        detections: list[dict[str, Any]],
        metrics: dict[str, Any],
        runtime_log: list[dict[str, Any]],
        source_capture_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        (result_dir / "config.yaml").write_text(self._to_simple_yaml(config.model_dump()), encoding="utf-8")
        (result_dir / "paper_reference.txt").write_text(
            "Current RF-Fingerprint-Lab-v6 morphological heuristic detector baseline\n",
            encoding="utf-8",
        )
        (result_dir / "detections.json").write_text(json.dumps(detections, indent=2), encoding="utf-8")
        (result_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (result_dir / "dataset_version.txt").write_text(config.dataset_version + "\n", encoding="utf-8")
        (result_dir / "source_capture_metadata.json").write_text(
            json.dumps(source_capture_metadata, indent=2),
            encoding="utf-8",
        )
        self._write_runtime_log(result_dir / "runtime_log.csv", runtime_log)
        return {"result_dir": str(result_dir), "files": sorted(path.name for path in result_dir.iterdir())}

    def write_e5_artifacts(
        self,
        result_dir: Path,
        config: dict[str, Any],
        features: list[dict[str, Any]],
        feature_matrix_path: Path,
        model_path: Path | None,
        metrics: dict[str, Any],
        predictions: list[dict[str, Any]],
        split_definition: dict[str, Any],
        runtime_log: list[dict[str, Any]],
        feature_importance: dict[str, Any] | None = None,
        feature_coefficients: dict[str, Any] | None = None,
        error_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        (result_dir / "config.yaml").write_text(self._to_simple_yaml(config), encoding="utf-8")
        (result_dir / "paper_reference.txt").write_text(
            "Kilic et al., Drone Classification Using RF Signal Based Spectral Features\n"
            "Nie et al., UAV Detection and Identification Based on WiFi Signal and RF Fingerprint\n"
            "O'Shea et al., Practical Signal Detection and Classification in GNU Radio\n",
            encoding="utf-8",
        )
        (result_dir / "features.json").write_text(json.dumps(features, indent=2), encoding="utf-8")
        self._write_features_csv(result_dir / "features.csv", features)
        self._write_reproducibility_contract(result_dir, config, split_definition, features)
        (result_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (result_dir / "classification_report.json").write_text(
            json.dumps(metrics.get("classification_report", {}), indent=2),
            encoding="utf-8",
        )
        (result_dir / "split_definition.json").write_text(json.dumps(split_definition, indent=2), encoding="utf-8")
        (result_dir / "dataset_version.txt").write_text(str(config.get("dataset_version", "unversioned")) + "\n", encoding="utf-8")
        self._write_runtime_log(result_dir / "runtime_log.csv", runtime_log)
        self._write_predictions_csv(result_dir / "predictions.csv", predictions)
        self._write_confusion_matrix_csv(result_dir / "confusion_matrix.csv", metrics.get("confusion_matrix", {}))
        self._write_confusion_matrix_csv(result_dir / "confusion_matrix_raw.csv", metrics.get("confusion_matrix", {}))
        self._write_confusion_matrix_csv(
            result_dir / "confusion_matrix_normalized.csv",
            self._normalized_confusion(metrics.get("confusion_matrix", {})),
        )
        (result_dir / "error_summary.json").write_text(json.dumps(error_summary or {}, indent=2), encoding="utf-8")
        if feature_importance is not None:
            (result_dir / "feature_importance.json").write_text(json.dumps(feature_importance, indent=2), encoding="utf-8")
            self._write_feature_scores_csv(result_dir / "feature_importance.csv", feature_importance)
        if feature_coefficients is not None:
            (result_dir / "feature_coefficients.json").write_text(json.dumps(feature_coefficients, indent=2), encoding="utf-8")
        return {
            "result_dir": str(result_dir),
            "files": sorted(path.name for path in result_dir.iterdir()),
            "features_npy": str(feature_matrix_path),
            "features_csv": str(result_dir / "features.csv"),
            "model_pkl": str(model_path) if model_path else None,
        }

    def write_e1_artifacts(
        self,
        result_dir: Path,
        config: dict[str, Any],
        model_path: Path,
        model_summary: str,
        metrics: dict[str, Any],
        predictions: list[dict[str, Any]],
        split_definition: dict[str, Any],
        runtime_log: list[dict[str, Any]],
        training_history: list[dict[str, Any]],
        overfitting_summary: dict[str, Any] | None = None,
        group_metrics: dict[str, Any] | None = None,
        confidence_summary: dict[str, Any] | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        (result_dir / "config.yaml").write_text(self._to_simple_yaml(config), encoding="utf-8")
        (result_dir / "paper_reference.txt").write_text(
            "Riyaz et al., Deep Learning Convolutional Neural Networks for Radio Identification\n"
            "Jian et al., Deep Learning for RF Fingerprinting: A Massive Experimental Study\n",
            encoding="utf-8",
        )
        (result_dir / "model_summary.txt").write_text(model_summary, encoding="utf-8")
        self._write_reproducibility_contract(result_dir, config, split_definition, predictions)
        (result_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (result_dir / "classification_report.json").write_text(
            json.dumps(metrics.get("classification_report", {}), indent=2),
            encoding="utf-8",
        )
        (result_dir / "split_definition.json").write_text(json.dumps(split_definition, indent=2), encoding="utf-8")
        (result_dir / "dataset_version.txt").write_text(str(config.get("dataset_version", "unversioned")) + "\n", encoding="utf-8")
        self._write_runtime_log(result_dir / "runtime_log.csv", runtime_log)
        self._write_predictions_csv(result_dir / "predictions.csv", predictions)
        self._write_confusion_matrix_csv(result_dir / "confusion_matrix_raw.csv", metrics.get("confusion_matrix", {}))
        self._write_confusion_matrix_csv(
            result_dir / "confusion_matrix_normalized.csv",
            self._normalized_confusion(metrics.get("confusion_matrix", {})),
        )
        self._write_training_history_csv(result_dir / "training_history.csv", training_history)
        (result_dir / "training_history.json").write_text(json.dumps(training_history, indent=2), encoding="utf-8")
        (result_dir / "overfitting_summary.json").write_text(json.dumps(overfitting_summary or {}, indent=2), encoding="utf-8")
        (result_dir / "group_metrics.json").write_text(json.dumps(group_metrics or {}, indent=2), encoding="utf-8")
        self._write_group_metrics_csv(result_dir / "group_metrics.csv", group_metrics or {})
        (result_dir / "confidence_summary.json").write_text(json.dumps(confidence_summary or {}, indent=2), encoding="utf-8")
        (result_dir / "model_metadata.json").write_text(json.dumps(model_metadata or {}, indent=2), encoding="utf-8")
        return {"result_dir": str(result_dir), "files": sorted(path.name for path in result_dir.iterdir()), "model_pt": str(model_path)}

    def write_e3_artifacts(
        self,
        result_dir: Path,
        config: dict[str, Any],
        model_path: Path,
        model_summary: str,
        metrics: dict[str, Any],
        predictions: list[dict[str, Any]],
        split_definition: dict[str, Any],
        runtime_log: list[dict[str, Any]],
        training_history: list[dict[str, Any]],
        overfitting_summary: dict[str, Any] | None = None,
        group_metrics: dict[str, Any] | None = None,
        confidence_summary: dict[str, Any] | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        (result_dir / "config.yaml").write_text(self._to_simple_yaml(config), encoding="utf-8")
        (result_dir / "paper_reference.txt").write_text(
            "Shen et al., Radio Frequency Fingerprint Identification for LoRa Using Deep Learning\n"
            "Lin et al., A Radio Frequency Signal Recognition Method Based on Spectrogram\n"
            "Liu et al., RF Fingerprint Recognition Based on Spectrum Waterfall Diagram\n"
            "Bremnes et al., Classification of UAVs Utilizing Fixed Boundary Empirical Wavelet Sub-Bands\n",
            encoding="utf-8",
        )
        (result_dir / "model_summary.txt").write_text(model_summary, encoding="utf-8")
        self._write_reproducibility_contract(result_dir, config, split_definition, predictions)
        (result_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (result_dir / "classification_report.json").write_text(
            json.dumps(metrics.get("classification_report", {}), indent=2),
            encoding="utf-8",
        )
        (result_dir / "split_definition.json").write_text(json.dumps(split_definition, indent=2), encoding="utf-8")
        (result_dir / "dataset_version.txt").write_text(str(config.get("dataset_version", "unversioned")) + "\n", encoding="utf-8")
        self._write_runtime_log(result_dir / "runtime_log.csv", runtime_log)
        self._write_predictions_csv(result_dir / "predictions.csv", predictions)
        self._write_confusion_matrix_csv(result_dir / "confusion_matrix_raw.csv", metrics.get("confusion_matrix", {}))
        self._write_confusion_matrix_csv(
            result_dir / "confusion_matrix_normalized.csv",
            self._normalized_confusion(metrics.get("confusion_matrix", {})),
        )
        self._write_training_history_csv(result_dir / "training_history.csv", training_history)
        (result_dir / "training_history.json").write_text(json.dumps(training_history, indent=2), encoding="utf-8")
        (result_dir / "overfitting_summary.json").write_text(json.dumps(overfitting_summary or {}, indent=2), encoding="utf-8")
        (result_dir / "group_metrics.json").write_text(json.dumps(group_metrics or {}, indent=2), encoding="utf-8")
        self._write_group_metrics_csv(result_dir / "group_metrics.csv", group_metrics or {})
        (result_dir / "confidence_summary.json").write_text(json.dumps(confidence_summary or {}, indent=2), encoding="utf-8")
        (result_dir / "model_metadata.json").write_text(json.dumps(model_metadata or {}, indent=2), encoding="utf-8")
        return {"result_dir": str(result_dir), "files": sorted(path.name for path in result_dir.iterdir()), "model_pt": str(model_path)}

    def _write_reproducibility_contract(
        self,
        result_dir: Path,
        config: dict[str, Any],
        split_definition: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        label_values = sorted({str(row.get("true_label") or row.get("label")) for row in rows if row.get("true_label") or row.get("label")})
        label_schema = {
            "label_field": config.get("label_field"),
            "labels": label_values,
            "class_count": len(label_values),
        }
        normalization = {
            "raw_iq_normalization": config.get("normalization", "none"),
            "image_normalization_mode": config.get("normalization_mode"),
            "feature_set": config.get("feature_set"),
            "input_representation": config.get("input_representation", "raw_iq"),
        }
        (result_dir / "dataset_manifest_path.txt").write_text(str(config.get("dataset_manifest_path") or "") + "\n", encoding="utf-8")
        (result_dir / "training_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        (result_dir / "label_schema.json").write_text(json.dumps(label_schema, indent=2), encoding="utf-8")
        (result_dir / "normalization_params.json").write_text(json.dumps(normalization, indent=2), encoding="utf-8")
        (result_dir / "split_strategy.txt").write_text(str(split_definition.get("strategy", "")) + "\n", encoding="utf-8")

    def list_results(self) -> list[dict[str, Any]]:
        results = []
        for path in sorted(self.results_dir.glob("*/*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.is_dir():
                metrics_path = path / "metrics.json"
                config_path = path / "config.yaml"
                metrics = self._load_json(metrics_path)
                config = self._load_yaml_like_config(config_path)
                run_key = f"{path.parent.name}:{path.name}"
                results.append(
                    {
                        "experiment_id": run_key,
                        "experiment_type": path.parent.name,
                        "technique_name": config.get("feature_set") or config.get("technique_name") or path.parent.name,
                        "paper_reference": self._safe_text(path / "paper_reference.txt").strip(),
                        "dataset_version": self._safe_text(path / "dataset_version.txt").strip(),
                        "split_strategy": (self._load_json(path / "split_definition.json") or {}).get("strategy"),
                        "created_at": path.name,
                        "status": "completed" if metrics_path.exists() else "unknown",
                        "metrics_summary": self._metrics_summary(metrics),
                        "result_path": str(path),
                        "run_id": path.name,
                        "path": str(path),
                        "has_metrics": metrics_path.exists(),
                        "has_config": config_path.exists(),
                    }
                )
        return results

    def get_experiment_detail(self, experiment_id: str) -> dict[str, Any]:
        path = self._result_path_from_id(experiment_id)
        if path is None or not path.exists():
            raise FileNotFoundError(f"Experiment result not found: {experiment_id}")
        metrics = self._load_json(path / "metrics.json") or {}
        predictions = self._read_predictions_summary(path / "predictions.csv")
        return {
            "experiment_id": f"{path.parent.name}:{path.name}",
            "experiment_type": path.parent.name,
            "config": self._load_yaml_like_config(path / "config.yaml"),
            "metrics": metrics,
            "predictions_summary": predictions,
            "confusion_matrix": metrics.get("confusion_matrix"),
            "result_files": sorted(item.name for item in path.iterdir()),
            "model_metadata": self._model_metadata(path),
            "paper_reference": self._safe_text(path / "paper_reference.txt").strip(),
            "result_path": str(path),
        }

    def compare_experiments(self, experiment_ids: list[str], metric: str = "macro_f1") -> dict[str, Any]:
        rows = []
        ids = experiment_ids or [item["experiment_id"] for item in self.list_results()]
        for experiment_id in ids:
            detail = self.get_experiment_detail(experiment_id)
            metrics = detail.get("metrics", {})
            if isinstance(metrics.get("models"), dict):
                for model_name, model_metrics in metrics["models"].items():
                    rows.append(self._comparison_row(detail, model_name, model_metrics, metric))
            else:
                rows.append(self._comparison_row(detail, metrics.get("primary_model", "default"), metrics, metric))
        reverse = metric not in {"inference_time_ms", "model_size_bytes"}
        rows.sort(key=lambda item: (item.get(metric) is not None, item.get(metric) or 0), reverse=reverse)
        return {"metric": metric, "rows": rows}

    def _write_empty_csv(self, path: Path, headers: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)

    def _write_runtime_log(self, path: Path, rows: list[dict[str, Any]]) -> None:
        headers = ["step", "status", "message", "latency_ms"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})

    def _write_predictions_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        headers = [
            "sample_id",
            "true_label",
            "predicted_label",
            "correct",
            "confidence",
            "model_name",
            "split",
            "capture_id",
            "session_id",
            "day_id",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})

    def _write_confusion_matrix_csv(self, path: Path, confusion: dict[str, Any]) -> None:
        labels = confusion.get("labels", []) if isinstance(confusion, dict) else []
        matrix = confusion.get("matrix", []) if isinstance(confusion, dict) else []
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["label", *labels])
            for label, row in zip(labels, matrix):
                writer.writerow([label, *row])

    def _write_training_history_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        headers = ["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy", "learning_rate", "epoch_time_ms"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})

    def _write_group_metrics_csv(self, path: Path, group_metrics: dict[str, Any]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["group_type", "group_value", "accuracy", "count"])
            writer.writeheader()
            for group_type, values in group_metrics.items():
                if not isinstance(values, dict):
                    continue
                for group_value, metrics in values.items():
                    if isinstance(metrics, dict):
                        writer.writerow(
                            {
                                "group_type": group_type,
                                "group_value": group_value,
                                "accuracy": metrics.get("accuracy"),
                                "count": metrics.get("count"),
                            }
                        )

    def _write_feature_scores_csv(self, path: Path, scores: dict[str, Any]) -> None:
        rows = scores.get("features", []) if isinstance(scores, dict) else []
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["feature", "score"])
            writer.writeheader()
            for row in rows:
                writer.writerow({"feature": row.get("feature"), "score": row.get("score")})

    def _write_features_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self._write_empty_csv(path, ["sample_id", "label"])
            return
        fields = sorted({key for row in rows for key in row.keys()})
        preferred = [key for key in ["sample_id", "capture_id", "session_id", "label", "true_label"] if key in fields]
        ordered = preferred + [key for key in fields if key not in preferred]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ordered, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _normalized_confusion(self, confusion: dict[str, Any]) -> dict[str, Any]:
        labels = confusion.get("labels", []) if isinstance(confusion, dict) else []
        matrix = confusion.get("matrix", []) if isinstance(confusion, dict) else []
        normalized = []
        for row in matrix:
            total = float(sum(row))
            normalized.append([float(value) / total if total else 0.0 for value in row])
        return {"labels": labels, "matrix": normalized}

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _safe_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _metrics_summary(self, metrics: dict[str, Any] | None) -> dict[str, Any]:
        metrics = metrics or {}
        keys = ["accuracy", "balanced_accuracy", "macro_f1", "precision_macro", "recall_macro", "inference_time_ms", "model_size_bytes"]
        return {key: metrics.get(key) for key in keys}

    def _result_path_from_id(self, experiment_id: str) -> Path | None:
        if ":" in experiment_id:
            experiment_type, run_id = experiment_id.split(":", 1)
            return self.results_dir / experiment_type / run_id
        matches = sorted(self.results_dir.glob(f"*/{experiment_id}"))
        return matches[0] if matches else None

    def _read_predictions_summary(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"count": 0, "errors": 0}
        with path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        errors = sum(1 for row in rows if str(row.get("correct")).lower() == "false")
        return {"count": len(rows), "errors": errors, "preview": rows[:20]}

    def _model_metadata(self, path: Path) -> dict[str, Any]:
        models = {}
        for model_path in path.glob("model*.pkl"):
            models[model_path.name] = {"size_bytes": model_path.stat().st_size}
        for model_path in path.glob("model*.pt"):
            models[model_path.name] = {"size_bytes": model_path.stat().st_size}
        metadata = self._load_json(path / "model_metadata.json")
        if metadata:
            models["metadata"] = metadata
        return models

    def _comparison_row(self, detail: dict[str, Any], model_name: str, metrics: dict[str, Any], metric: str) -> dict[str, Any]:
        return {
            "experiment_id": detail["experiment_id"],
            "experiment_type": detail["experiment_type"],
            "model_name": model_name,
            "accuracy": metrics.get("accuracy"),
            "balanced_accuracy": metrics.get("balanced_accuracy"),
            "macro_f1": metrics.get("macro_f1"),
            "precision_macro": metrics.get("precision_macro"),
            "recall_macro": metrics.get("recall_macro"),
            "training_time_ms": metrics.get("training_time_ms"),
            "inference_time_ms": metrics.get("inference_time_ms"),
            "model_size_bytes": metrics.get("model_size_bytes"),
            "feature_extraction_time_ms": metrics.get("feature_extraction_time_ms"),
            "number_of_train_samples": metrics.get("number_of_train_samples"),
            "number_of_test_samples": metrics.get("number_of_test_samples"),
            "number_of_classes": metrics.get("number_of_classes"),
            metric: metrics.get(metric),
            "result_path": detail["result_path"],
        }

    def _load_yaml_like_config(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        result: dict[str, Any] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" not in line or line.startswith(" "):
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            try:
                result[key.strip()] = json.loads(value)
            except Exception:
                result[key.strip()] = value
        return result

    def _model_summary(self, config: ExperimentConfig) -> str:
        if not config.trainable:
            return "Non-trainable baseline detector. No model weights are produced.\n"
        return (
            f"Technique: {config.technique_name or config.experiment_id}\n"
            f"Model type: {config.model_type or config.detector_type or 'unspecified'}\n"
            "Implementation status: experiment contract registered; training backend is intentionally optional.\n"
        )

    def _to_simple_yaml(self, value: Any, indent: int = 0) -> str:
        prefix = " " * indent
        if isinstance(value, dict):
            lines = []
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.append(self._to_simple_yaml(item, indent + 2))
                else:
                    lines.append(f"{prefix}{key}: {json.dumps(item)}")
            return "\n".join(lines) + "\n"
        if isinstance(value, list):
            lines = []
            for item in value:
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}-")
                    lines.append(self._to_simple_yaml(item, indent + 2))
                else:
                    lines.append(f"{prefix}- {json.dumps(item)}")
            return "\n".join(lines) + "\n"
        return f"{prefix}{json.dumps(value)}\n"
