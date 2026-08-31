from __future__ import annotations

import importlib.util
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from app.modules.rf_experiment_lab.experiment_config_schema import ExperimentSplitConfig
from app.modules.rf_experiment_lab.metrics_service import MetricsService


class E5SpectralBaselineService:
    experiment_id = "e5_spectral_feature_baseline"
    paper_reference = "Kilic et al.; Nie et al.; O'Shea et al."
    default_models = ["logistic_regression", "random_forest", "svm_rbf", "knn"]
    feature_names = [
        "mean_power",
        "peak_power",
        "peak_frequency_offset_hz",
        "occupied_bandwidth_hz",
        "spectral_centroid",
        "spectral_spread",
        "spectral_flatness",
        "spectral_entropy",
        "band_energy_ratio_low",
        "band_energy_ratio_mid",
        "band_energy_ratio_high",
        "noise_floor_estimate",
        "snr_db",
    ]

    def __init__(self, representation_service, dataset_adapter, split_manager, result_store) -> None:
        self.representation_service = representation_service
        self.dataset_adapter = dataset_adapter
        self.split_manager = split_manager
        self.result_store = result_store
        self.metrics_service = MetricsService()

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._config(payload)
        captures = self._selected_captures(config)
        label_status = self._label_status(captures, config)
        split = self._split(captures, config)
        eligibility = self.dataset_adapter.training_eligibility_summary(config)
        return {
            "experiment_id": self.experiment_id,
            "preview_only": True,
            "training_started": False,
            "paper_reference": self.paper_reference,
            "input_representation": config["input_representation"],
            "feature_set": config["feature_set"],
            "feature_names": self.feature_names,
            "mfcc": {"available": False, "status": "not_implemented", "message": "MFCC remains optional until dependency support is enabled."},
            "lfcc": {"available": False, "status": "not_implemented", "message": "LFCC is registered but not enabled in E5 v0.1."},
            "models": self._available_models(config),
            "dataset": {
                "capture_count": len(captures),
                "class_count": len(label_status["labels"]),
                "labels": label_status["labels"],
                "missing_label_capture_ids": label_status["missing_capture_ids"],
                "weak_label_capture_ids": label_status["weak_label_capture_ids"],
                "label_field": config["label_field"],
                "training_readiness_policy": config["training_readiness_policy"],
                "training_eligibility": eligibility,
            },
            "split": split,
            "available_for_training": bool(captures) and not label_status["missing_capture_ids"] and not label_status["weak_label_capture_ids"] and self._sklearn_available(config),
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._config(payload)
        if not self._sklearn_available(config):
            raise RuntimeError("scikit-learn is unavailable; E5 training is disabled but feature extraction remains available")
        captures = self._selected_captures(config)
        eligibility = self.dataset_adapter.training_eligibility_summary(config)
        if not captures:
            raise ValueError(
                "E5 found no eligible captures for training under "
                f"{config['training_readiness_policy']}. "
                f"Considered {eligibility['total_considered']} records, excluded {eligibility['excluded_count']}. "
                f"Reasons: {eligibility['exclusion_reasons']}. "
                "Use Dataset Builder to mark reviewed samples as ready_for_training for scientific runs, "
                "or select training_draft for exploratory baselines with candidate captures."
            )
        label_status = self._label_status(captures, config)
        if label_status["missing_capture_ids"] or label_status["weak_label_capture_ids"]:
            raise ValueError(
                "E5 scientific training requires reviewed labels. "
                f"Missing: {', '.join(label_status['missing_capture_ids']) or 'none'}. "
                f"Weak/unconfirmed: {', '.join(label_status['weak_label_capture_ids']) or 'none'}. "
                "Use Dataset Builder to confirm labels, or set allow_weak_labels_debug=true only for debug runs."
            )
        if len(label_status["labels"]) < 2:
            raise ValueError(
                "E5 requires at least two classes for training after readiness filtering. "
                f"Label field: {config['label_field']}. Labels found: {label_status['labels']}. "
                f"Training readiness policy: {config['training_readiness_policy']}. "
                f"Eligibility summary: {eligibility}. "
                "For E5 signal recognition, use label_field=signal_type or modulation_class. "
                "For transmitter fingerprinting, use transmitter_id only after physical device labels are confirmed."
            )

        runtime_log: list[dict[str, Any]] = []
        started = time.perf_counter()
        feature_rows, x, y, capture_ids = self._extract_features(captures, config)
        feature_time_ms = (time.perf_counter() - started) * 1000.0
        runtime_log.append({"step": "feature_extraction", "status": "ok", "message": f"{len(feature_rows)} rows", "latency_ms": feature_time_ms})

        split = self._split(captures, config)
        assignments = split["assignments"]
        train_idx = [idx for idx, capture_id in enumerate(capture_ids) if assignments.get(capture_id) == "train"]
        eval_idx = [idx for idx, capture_id in enumerate(capture_ids) if assignments.get(capture_id) in {"validation", "test"}]
        if not train_idx or not eval_idx:
            raise ValueError("E5 split produced empty train or evaluation set; add more disjoint groups")
        train_labels = {y[idx] for idx in train_idx}
        eval_labels = {y[idx] for idx in eval_idx}
        if len(train_labels) < 2:
            raise ValueError("E5 training split must contain at least two classes")
        missing_from_train = sorted(eval_labels - train_labels)
        if missing_from_train:
            raise ValueError("E5 closed-set evaluation has classes missing from train split: " + ", ".join(missing_from_train))

        result_dir = self.result_store.root / "results" / self.experiment_id / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result_dir.mkdir(parents=True, exist_ok=False)
        feature_matrix_path = result_dir / "features.npy"
        np.save(feature_matrix_path, x.astype(np.float32))

        capture_lookup = {str(item.get("capture_id")): item for item in captures}
        model_results, predictions, model_path, feature_importance, feature_coefficients, error_summary = self._train_and_evaluate(
            config, x, y, capture_ids, train_idx, eval_idx, assignments, result_dir, capture_lookup, feature_time_ms
        )
        primary_name = next(iter(model_results))
        metrics = {
            **model_results[primary_name],
            "models": model_results,
            "comparison": [self._comparison_row(name, values) for name, values in model_results.items()],
            "primary_model": primary_name,
            "training_time_ms": model_results[primary_name].get("training_time_ms"),
            "inference_time_ms": model_results[primary_name].get("inference_time_ms"),
            "model_size_bytes": Path(model_path).stat().st_size if model_path else None,
            "feature_extraction_time_ms": feature_time_ms,
        }

        package = self.result_store.write_e5_artifacts(
            result_dir=result_dir,
            config=config,
            features=feature_rows,
            feature_matrix_path=feature_matrix_path,
            model_path=Path(model_path) if model_path else None,
            metrics=metrics,
            predictions=predictions,
            split_definition=split,
            runtime_log=runtime_log,
            feature_importance=feature_importance,
            feature_coefficients=feature_coefficients,
            error_summary=error_summary,
        )
        return {
            "experiment_id": self.experiment_id,
            "preview_only": False,
            "training_started": True,
            "training_completed": True,
            "paper_reference": self.paper_reference,
            "config": config,
            "metrics": metrics,
            "result_package": package,
        }

    def _config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "dataset_version": payload.get("dataset_version", "unversioned"),
            "task": payload.get("task", "signal_recognition"),
            "dataset_manifest_path": payload.get("dataset_manifest_path") or payload.get("rf_experiment_dataset_path"),
            "capture_ids": payload.get("capture_ids") or [],
            "input_representation": payload.get("input_representation", "fft_psd"),
            "feature_set": payload.get("feature_set", "psd_basic"),
            "models": payload.get("models") or self.default_models,
            "label_field": payload.get("label_field") or ("transmitter_id" if payload.get("task") == "device_fingerprinting" else "signal_type"),
            "split": payload.get("split") or {"strategy": "session_disjoint", "group_by": ["session_id"]},
            "window_size_samples": int(payload.get("window_size_samples", 4096)),
            "overlap": float(payload.get("overlap", 0.0)),
            "n_fft": int(payload.get("n_fft", 1024)),
            "welch_nperseg": int(payload.get("welch_nperseg", 1024)),
            "force_sklearn_unavailable": bool(payload.get("force_sklearn_unavailable", False)),
            "training_readiness_policy": payload.get("training_readiness_policy", "scientific_strict"),
            "allow_weak_labels_debug": bool(payload.get("allow_weak_labels_debug", False)),
        }

    def _selected_captures(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        captures = self.dataset_adapter.list_training_records(config)
        ids = {str(item) for item in config.get("capture_ids", [])}
        if ids:
            captures = [item for item in captures if str(item.get("capture_id")) in ids]
        return [item for item in captures if item.get("raw_file") and item.get("metadata_file")]

    def _label_status(self, captures: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.validate_training_label_policy(
            captures,
            config["label_field"],
            allow_weak_labels=bool(config.get("allow_weak_labels_debug")),
        )

    def _split(self, captures: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        split_payload = config.get("split") or {}
        split_config = ExperimentSplitConfig.model_validate(
            {
                "strategy": split_payload.get("strategy", "session_disjoint"),
                "group_by": split_payload.get("group_by", ["session_id"]),
                "train_ratio": split_payload.get("train_ratio", 0.7),
                "validation_ratio": split_payload.get("validation_ratio", 0.15),
                "test_ratio": split_payload.get("test_ratio", 0.15),
            }
        )
        return self.split_manager.build_split(captures, split_config)

    def _available_models(self, config: dict[str, Any]) -> dict[str, Any]:
        sklearn = self._sklearn_available(config)
        return {
            "logistic_regression": {"available": sklearn, "requires": "scikit-learn"},
            "random_forest": {"available": sklearn, "requires": "scikit-learn"},
            "svm_rbf": {"available": sklearn, "requires": "scikit-learn"},
            "knn": {"available": sklearn, "requires": "scikit-learn"},
        }

    def _sklearn_available(self, config: dict[str, Any]) -> bool:
        return not config.get("force_sklearn_unavailable") and importlib.util.find_spec("sklearn") is not None

    def _extract_features(self, captures: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], np.ndarray, list[str], list[str]]:
        rows = []
        vectors = []
        labels = []
        capture_ids = []
        for capture in captures:
            payload = {
                "metadata_path": capture["metadata_file"],
                "iq_path": capture["raw_file"],
                "window_size_samples": config["window_size_samples"],
                "max_preview_windows": 1,
                "n_fft": config["n_fft"],
                "welch_nperseg": config["welch_nperseg"],
                "preview": True,
            }
            context, windows = self.representation_service.spectral_feature_source_windows(payload)
            if not windows:
                continue
            iq = self.representation_service.read_iq_window_for_features(context, windows[0])
            computed = self.representation_service.fft_psd_for_features(iq, context, payload, windows[0])
            vector = self._psd_features(computed, capture)
            label = self._label_value(capture, config["label_field"])
            rows.append({"capture_id": str(capture.get("capture_id")), "label": label, "features": dict(zip(self.feature_names, vector))})
            vectors.append(vector)
            labels.append(label)
            capture_ids.append(str(capture.get("capture_id")))
        if not vectors:
            raise ValueError("No usable spectral features could be extracted")
        return rows, np.asarray(vectors, dtype=np.float32), labels, capture_ids

    @staticmethod
    def _label_value(capture: dict[str, Any], label_field: str) -> str:
        value = capture.get(label_field)
        if value in (None, "") and capture.get("label_type") == label_field:
            value = capture.get("label")
        return str(value)

    def _psd_features(self, computed: dict[str, Any], capture: dict[str, Any]) -> list[float]:
        data = np.asarray(computed["data"], dtype=np.float32)
        freq = data[0]
        mag = np.maximum(data[1], 1e-12)
        power = mag ** 2
        total = float(np.sum(power))
        weights = power / max(total, 1e-20)
        centroid = float(np.sum(freq * weights))
        spread = float(np.sqrt(np.sum(((freq - centroid) ** 2) * weights)))
        entropy = float(-np.sum(weights * np.log2(np.maximum(weights, 1e-20))) / max(np.log2(weights.size), 1e-20))
        flatness = float(np.exp(np.mean(np.log(np.maximum(power, 1e-20)))) / max(np.mean(power), 1e-20))
        thirds = np.array_split(power, 3)
        ratios = [float(np.sum(part) / max(total, 1e-20)) for part in thirds]
        center = float(capture.get("center_frequency_hz") or np.mean(freq))
        peak_idx = int(np.argmax(power))
        return [
            float(np.mean(power)),
            float(np.max(power)),
            float(freq[peak_idx] - center),
            float(computed.get("occupied_bandwidth_hz") or 0.0),
            centroid,
            spread,
            flatness,
            entropy,
            ratios[0],
            ratios[1],
            ratios[2],
            float(computed.get("noise_floor_db") or 0.0),
            float(capture.get("snr_db") or 0.0),
        ]

    def _train_and_evaluate(self, config, x, y, capture_ids, train_idx, eval_idx, assignments, result_dir, capture_lookup, feature_time_ms):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVC

        factories = {
            "logistic_regression": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=42)),
            "random_forest": lambda: RandomForestClassifier(n_estimators=100, random_state=42),
            "svm_rbf": lambda: make_pipeline(StandardScaler(), SVC(kernel="rbf", gamma="scale")),
            "knn": lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=max(1, min(3, len(train_idx))))),
        }
        results = {}
        all_predictions = []
        model_path = None
        feature_importance = None
        feature_coefficients = None
        primary_errors = None
        for name in config["models"]:
            if name not in factories:
                continue
            model = factories[name]()
            started = time.perf_counter()
            model.fit(x[train_idx], [y[idx] for idx in train_idx])
            training_time = (time.perf_counter() - started) * 1000.0
            started = time.perf_counter()
            pred = list(model.predict(x[eval_idx]))
            inference_time = (time.perf_counter() - started) * 1000.0
            confidence = self._confidence_scores(model, x[eval_idx])
            truth = [y[idx] for idx in eval_idx]
            metrics = self.metrics_service.classification_metrics(truth, pred)
            metrics["per_class_precision"] = {label: item["precision"] for label, item in metrics["classification_report"].items()}
            metrics["per_class_recall"] = {label: item["recall"] for label, item in metrics["classification_report"].items()}
            metrics["training_time_ms"] = training_time
            metrics["inference_time_ms"] = inference_time
            metrics["feature_extraction_time_ms"] = feature_time_ms
            metrics["number_of_train_samples"] = len(train_idx)
            metrics["number_of_test_samples"] = len(eval_idx)
            metrics["number_of_classes"] = len(set(y))
            model_specific_path = result_dir / f"model_{name}.pkl"
            with model_specific_path.open("wb") as handle:
                pickle.dump({"model_name": name, "model": model, "feature_names": self.feature_names}, handle)
            metrics["model_size_bytes"] = model_specific_path.stat().st_size
            metrics["feature_importance_status"] = "not_available"
            results[name] = metrics
            model_predictions = []
            for idx, predicted, score in zip(eval_idx, pred, confidence):
                capture = capture_lookup.get(capture_ids[idx], {})
                row = {
                    "sample_id": f"{capture_ids[idx]}:{name}",
                    "true_label": y[idx],
                    "predicted_label": predicted,
                    "correct": str(y[idx] == predicted).lower(),
                    "confidence": score,
                    "model_name": name,
                    "split": assignments.get(capture_ids[idx]),
                    "capture_id": capture_ids[idx],
                    "session_id": capture.get("session_id"),
                    "day_id": capture.get("day_id"),
                }
                all_predictions.append(row)
                model_predictions.append(row)
            if name == "random_forest" and hasattr(model, "feature_importances_"):
                feature_importance = {
                    "model_name": name,
                    "features": [
                        {"feature": feature, "score": float(score)}
                        for feature, score in zip(self.feature_names, model.feature_importances_)
                    ],
                }
                results[name]["feature_importance_status"] = "available"
            elif name == "logistic_regression":
                final_model = model.steps[-1][1] if hasattr(model, "steps") else model
                if hasattr(final_model, "coef_"):
                    feature_coefficients = {
                        "model_name": name,
                        "features": [
                            {"feature": feature, "coefficient": float(score)}
                            for feature, score in zip(self.feature_names, np.asarray(final_model.coef_)[0])
                        ],
                    }
            if model_path is None:
                model_path = result_dir / "model.pkl"
                with model_path.open("wb") as handle:
                    pickle.dump({"model_name": name, "model": model, "feature_names": self.feature_names}, handle)
                primary_errors = self._error_summary(model_predictions, capture_lookup)
        if not results:
            raise ValueError("No supported E5 models were selected")
        return results, all_predictions, str(model_path) if model_path else None, feature_importance, feature_coefficients, primary_errors

    def _confidence_scores(self, model, x_eval: np.ndarray) -> list[float | None]:
        if hasattr(model, "predict_proba"):
            try:
                probs = model.predict_proba(x_eval)
                return [float(np.max(row)) for row in probs]
            except Exception:
                pass
        if hasattr(model, "decision_function"):
            try:
                scores = np.asarray(model.decision_function(x_eval))
                if scores.ndim == 1:
                    return [float(abs(value)) for value in scores]
                return [float(np.max(row)) for row in scores]
            except Exception:
                pass
        return [None for _ in range(len(x_eval))]

    def _error_summary(self, predictions: list[dict[str, Any]], capture_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
        errors = [row for row in predictions if row.get("correct") == "false"]
        total = len(predictions)
        pairs: dict[str, int] = {}
        per_class: dict[str, int] = {}
        by_session: dict[str, int] = {}
        by_snr: dict[str, int] = {}
        for row in errors:
            pair = f"{row.get('true_label')}->{row.get('predicted_label')}"
            pairs[pair] = pairs.get(pair, 0) + 1
            label = str(row.get("true_label"))
            per_class[label] = per_class.get(label, 0) + 1
            capture = capture_lookup.get(str(row.get("capture_id")), {})
            session = str(capture.get("session_id") or "unknown")
            by_session[session] = by_session.get(session, 0) + 1
            snr = str(capture.get("snr_db") or "unknown")
            by_snr[snr] = by_snr.get(snr, 0) + 1
        return {
            "total_errors": len(errors),
            "error_rate": len(errors) / max(total, 1),
            "most_confused_pairs": sorted(pairs.items(), key=lambda item: item[1], reverse=True),
            "per_class_errors": per_class,
            "errors_by_session": by_session,
            "errors_by_snr": by_snr,
        }

    def _comparison_row(self, model_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
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
        }
