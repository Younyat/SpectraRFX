from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BenchmarkReportBuilder:
    metric_columns = [
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "precision_macro",
        "recall_macro",
        "inference_time_ms",
        "model_size_bytes",
        "training_time_ms",
        "number_of_train_samples",
        "number_of_test_samples",
        "number_of_classes",
    ]

    def __init__(self, result_store) -> None:
        self.result_store = result_store
        self.benchmark_dir = result_store.root / "benchmarks"
        self.benchmark_dir.mkdir(parents=True, exist_ok=True)

    def build(self, payload: dict[str, Any]) -> dict[str, Any]:
        sort_metric = payload.get("sort_metric") or "macro_f1"
        experiment_ids = payload.get("experiment_ids") or [item["experiment_id"] for item in self.result_store.list_results()]
        include_predictions = bool(payload.get("include_predictions_summary", False))
        include_group_metrics = bool(payload.get("include_group_metrics", False))
        include_confusion = bool(payload.get("include_confusion_matrices", False))
        export = bool(payload.get("export", False))

        details = [self.result_store.get_experiment_detail(experiment_id) for experiment_id in experiment_ids]
        rows = self._comparison_rows(details)
        rows.sort(key=lambda row: (row.get(sort_metric) is not None, row.get(sort_metric) or 0.0), reverse=sort_metric not in {"inference_time_ms", "model_size_bytes"})
        warnings = self._warnings(details, rows)
        report = {
            "benchmark_id": datetime.now(timezone.utc).strftime("benchmark_%Y%m%dT%H%M%S%fZ"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_versions": sorted({str(row.get("dataset_version") or "unknown") for row in rows}),
            "experiment_ids": experiment_ids,
            "experiment_families": sorted({str(row.get("experiment_type")) for row in rows}),
            "paper_references": sorted({str(row.get("paper_reference") or "") for row in rows if row.get("paper_reference")}),
            "split_strategies": sorted({str(row.get("split_strategy") or "unknown") for row in rows}),
            "sort_metric": sort_metric,
            "metric_comparison_table": rows,
            "best_model_by_macro_f1": self._best(rows, "macro_f1"),
            "best_model_by_balanced_accuracy": self._best(rows, "balanced_accuracy"),
            "fastest_model_by_inference_time_ms": self._best(rows, "inference_time_ms", low=True),
            "smallest_model_by_model_size_bytes": self._best(rows, "model_size_bytes", low=True),
            "per_class_comparison": self._per_class(details),
            "per_session_comparison": self._group_comparison(details, "accuracy_by_session_id") if include_group_metrics else {},
            "per_snr_comparison": self._group_comparison(details, "accuracy_by_snr_bin") if include_group_metrics else {},
            "warnings": warnings,
            "reproducibility_summary": self._reproducibility(details, rows, warnings),
        }
        if include_predictions:
            report["predictions_summary"] = {detail["experiment_id"]: detail.get("predictions_summary", {}) for detail in details}
        if include_confusion:
            report["confusion_matrices"] = {detail["experiment_id"]: detail.get("confusion_matrix", {}) for detail in details}
        if export:
            report["export_package"] = self._export(report)
        return report

    def _comparison_rows(self, details: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for detail in details:
            metrics = detail.get("metrics", {})
            config = detail.get("config", {})
            split = self._load_json(Path(detail["result_path"]) / "split_definition.json") or {}
            model_metadata = (detail.get("model_metadata", {}) or {}).get("metadata", {})
            if isinstance(metrics.get("models"), dict):
                for model_name, model_metrics in metrics["models"].items():
                    rows.append(self._row(detail, config, split, model_metadata, model_name, model_metrics))
            else:
                rows.append(self._row(detail, config, split, model_metadata, metrics.get("primary_model") or model_metadata.get("model_type") or "default", metrics))
        return rows

    def _row(self, detail, config, split, model_metadata, model_name, metrics) -> dict[str, Any]:
        row = {
            "experiment_id": detail["experiment_id"],
            "experiment_type": detail["experiment_type"],
            "technique_name": config.get("feature_set") or config.get("technique_name") or detail["experiment_type"],
            "model_type": model_metadata.get("model_type") or model_name,
            "input_representation": config.get("input_representation") or self._inferred_representation(detail["experiment_type"]),
            "paper_reference": detail.get("paper_reference"),
            "dataset_version": self._safe_text(Path(detail["result_path"]) / "dataset_version.txt") or config.get("dataset_version"),
            "split_strategy": split.get("strategy"),
        }
        row.update({key: metrics.get(key) for key in self.metric_columns})
        return row

    def _warnings(self, details: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
        dataset_versions = {str(row.get("dataset_version") or "unknown") for row in rows}
        split_strategies = {str(row.get("split_strategy") or "unknown") for row in rows}
        missing_metrics = [
            {"experiment_id": row["experiment_id"], "missing": [key for key in self.metric_columns if row.get(key) is None]}
            for row in rows
            if any(row.get(key) is None for key in self.metric_columns)
        ]
        label_sets = [set((detail.get("metrics", {}).get("confusion_matrix") or {}).get("labels", [])) for detail in details]
        non_empty_label_sets = [labels for labels in label_sets if labels]
        low_sample_count = [row["experiment_id"] for row in rows if (row.get("number_of_test_samples") or 0) < 5 or (row.get("number_of_train_samples") or 0) < 5]
        missing_group = [
            detail["experiment_id"]
            for detail in details
            if not (self._load_json(Path(detail["result_path"]) / "group_metrics.json") or {})
        ]
        class_missing = []
        for detail in details:
            report = detail.get("metrics", {}).get("classification_report", {})
            missing = [label for label, values in report.items() if isinstance(values, dict) and int(values.get("support") or 0) == 0]
            if missing:
                class_missing.append({"experiment_id": detail["experiment_id"], "labels": missing})
        return {
            "different_dataset_versions": {"active": len(dataset_versions) > 1, "values": sorted(dataset_versions)},
            "different_split_strategies": {"active": len(split_strategies) > 1, "values": sorted(split_strategies)},
            "missing_metrics": {"active": bool(missing_metrics), "items": missing_metrics},
            "missing_group_metrics": {"active": bool(missing_group), "experiment_ids": missing_group},
            "incompatible_label_spaces": {"active": len({tuple(sorted(labels)) for labels in non_empty_label_sets}) > 1, "label_spaces": [sorted(labels) for labels in non_empty_label_sets]},
            "debug_random_split_used": {"active": any(str(row.get("split_strategy", "")).startswith("random") for row in rows)},
            "low_sample_count": {"active": bool(low_sample_count), "experiment_ids": low_sample_count},
            "class_missing_in_test": {"active": bool(class_missing), "items": class_missing},
        }

    def _reproducibility(self, details: list[dict[str, Any]], rows: list[dict[str, Any]], warnings: dict[str, Any]) -> dict[str, Any]:
        return {
            "experiment_count": len(details),
            "row_count": len(rows),
            "result_paths": {detail["experiment_id"]: detail["result_path"] for detail in details},
            "dataset_versions": sorted({str(row.get("dataset_version") or "unknown") for row in rows}),
            "split_strategies": sorted({str(row.get("split_strategy") or "unknown") for row in rows}),
            "warning_flags": {key: value.get("active") for key, value in warnings.items() if isinstance(value, dict)},
            "source_artifacts_required": ["config.yaml", "metrics.json", "split_definition.json", "dataset_version.txt", "paper_reference.txt"],
        }

    def _per_class(self, details: list[dict[str, Any]]) -> dict[str, Any]:
        label_sets = []
        reports = {}
        for detail in details:
            report = detail.get("metrics", {}).get("classification_report", {})
            labels = set(report.keys())
            if labels:
                label_sets.append(labels)
                reports[detail["experiment_id"]] = report
        if not label_sets or len({tuple(sorted(labels)) for labels in label_sets}) > 1:
            return {"available": False, "reason": "label_spaces_do_not_align"}
        labels = sorted(label_sets[0])
        return {
            "available": True,
            "labels": labels,
            "rows": [
                {
                    "experiment_id": experiment_id,
                    "label": label,
                    "precision": values.get(label, {}).get("precision"),
                    "recall": values.get(label, {}).get("recall"),
                    "f1": values.get(label, {}).get("f1"),
                    "support": values.get(label, {}).get("support"),
                }
                for experiment_id, values in reports.items()
                for label in labels
            ],
        }

    def _group_comparison(self, details: list[dict[str, Any]], group_key: str) -> dict[str, Any]:
        rows = []
        for detail in details:
            groups = self._load_json(Path(detail["result_path"]) / "group_metrics.json") or {}
            for value, metrics in (groups.get(group_key) or {}).items():
                rows.append({"experiment_id": detail["experiment_id"], "group": value, **metrics})
        return {"available": bool(rows), "group_key": group_key, "rows": rows}

    def _best(self, rows: list[dict[str, Any]], metric: str, low: bool = False) -> dict[str, Any] | None:
        candidates = [row for row in rows if row.get(metric) is not None]
        if not candidates:
            return None
        return sorted(candidates, key=lambda row: row.get(metric), reverse=not low)[0]

    def _export(self, report: dict[str, Any]) -> dict[str, Any]:
        out_dir = self.benchmark_dir / report["benchmark_id"]
        out_dir.mkdir(parents=True, exist_ok=False)
        (out_dir / "benchmark_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "benchmark_report.md").write_text(self._markdown(report), encoding="utf-8")
        self._write_table_csv(out_dir / "comparison_table.csv", report["metric_comparison_table"])
        (out_dir / "warnings.json").write_text(json.dumps(report["warnings"], indent=2), encoding="utf-8")
        (out_dir / "reproducibility_summary.json").write_text(json.dumps(report["reproducibility_summary"], indent=2), encoding="utf-8")
        return {"result_dir": str(out_dir), "files": sorted(path.name for path in out_dir.iterdir())}

    def _write_table_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        headers = [
            "experiment_id",
            "experiment_type",
            "technique_name",
            "model_type",
            "input_representation",
            "paper_reference",
            "dataset_version",
            "split_strategy",
            *self.metric_columns,
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})

    def _markdown(self, report: dict[str, Any]) -> str:
        lines = [f"# RF Experiment Lab Benchmark {report['benchmark_id']}", "", f"Created: {report['created_at']}", ""]
        lines.append("| Experiment | Model | Macro F1 | Balanced Accuracy | Inference ms | Model bytes |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in report["metric_comparison_table"]:
            lines.append(
                f"| {row.get('experiment_id')} | {row.get('model_type')} | {row.get('macro_f1')} | "
                f"{row.get('balanced_accuracy')} | {row.get('inference_time_ms')} | {row.get('model_size_bytes')} |"
            )
        return "\n".join(lines) + "\n"

    def _inferred_representation(self, experiment_type: str) -> str | None:
        return {
            "e1_raw_iq_cnn1d": "raw_iq",
            "e3_spectrogram_cnn2d": "spectrogram_or_waterfall",
            "e5_spectral_feature_baseline": "fft_psd",
        }.get(experiment_type)

    def _safe_text(self, path: Path) -> str | None:
        return path.read_text(encoding="utf-8").strip() if path.exists() else None

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None
