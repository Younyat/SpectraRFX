from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RF_EXPERIMENT_DATASET_VERSION = "RFExperimentDatasetV1"


class RFExperimentDatasetV1Builder:
    supported_public_datasets = {
        "oracle": {
            "primary_task": "device_fingerprinting",
            "recommended_label_fields": ["transmitter_id"],
            "scientific_note": "Use primarily for RF fingerprinting of physical transmitters.",
        },
        "wisig": {
            "primary_task": "device_fingerprinting",
            "recommended_label_fields": ["transmitter_id", "receiver_id"],
            "scientific_note": "Use primarily for RF fingerprinting and receiver/domain-shift studies.",
        },
        "radioml": {
            "primary_task": "signal_recognition",
            "recommended_label_fields": ["modulation_class", "signal_type"],
            "scientific_note": "Use primarily for modulation or signal-type classification, not physical transmitter fingerprinting.",
        },
        "sig53": {
            "primary_task": "signal_recognition",
            "recommended_label_fields": ["modulation_class", "signal_type"],
            "scientific_note": "Use primarily for modulation or signal-type classification, not physical transmitter fingerprinting.",
        },
    }

    supported_custom_formats = [
        "iq",
        "cfile",
        "sigmf",
        "hdf5",
        "numpy",
        "matlab",
        "pickle",
        "csv_features",
        "spectrogram_images",
        "waterfall_images",
    ]

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.dataset_root = storage_root / "rf_experiment_lab" / "datasets"

    def preview_from_internal(self, captures: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        records, warnings = self._records_from_internal(captures, payload)
        return self._preview_response(payload, records, warnings, source_kind="internal")

    def export_from_internal(self, captures: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        records, warnings = self._records_from_internal(captures, payload)
        return self._write_manifest(payload, records, warnings, source_kind="internal")

    def preview_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        records, warnings = self._records_from_external(payload)
        return self._preview_response(payload, records, warnings, source_kind=str(payload.get("dataset_source", "external_custom")))

    def export_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        records, warnings = self._records_from_external(payload)
        return self._write_manifest(payload, records, warnings, source_kind=str(payload.get("dataset_source", "external_custom")))

    def load_manifest(self, manifest_path: str | Path) -> dict[str, Any]:
        path = Path(manifest_path)
        if not path.exists():
            raise FileNotFoundError(f"RFExperimentDatasetV1 manifest not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("RFExperimentDatasetV1 manifest must be a JSON object")
        if value.get("schema_version") != RF_EXPERIMENT_DATASET_VERSION:
            raise ValueError(f"Unsupported dataset schema: {value.get('schema_version')}")
        samples = value.get("samples")
        if not isinstance(samples, list):
            raise ValueError("RFExperimentDatasetV1 manifest requires a samples list")
        return value

    def records_for_training(self, manifest_path: str | Path) -> list[dict[str, Any]]:
        manifest = self.load_manifest(manifest_path)
        records: list[dict[str, Any]] = []
        for sample in manifest.get("samples", []):
            if isinstance(sample, dict):
                records.append(self._sample_to_capture_record(sample, manifest))
        return records

    def describe_supported_sources(self) -> dict[str, Any]:
        return {
            "schema_version": RF_EXPERIMENT_DATASET_VERSION,
            "internal_sources": ["capture_lab", "fingerprinting_registry", "rf_signal_understanding"],
            "public_dataset_profiles": self.supported_public_datasets,
            "custom_formats": self.supported_custom_formats,
            "training_contract": {
                "E1": "raw_iq_path required; samples are converted to [2, N] windows at runtime",
                "E3": "raw_iq_path, spectrogram_path or waterfall_path accepted by the dataset contract; current training path prefers raw_iq_path for reproducible generation",
                "E5": "raw_iq_path or features_path accepted; current feature extraction path prefers raw_iq_path",
            },
        }

    def _records_from_internal(self, captures: list[dict[str, Any]], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ids = {str(item) for item in payload.get("capture_ids", []) if item}
        if ids:
            captures = [item for item in captures if str(item.get("capture_id")) in ids]
        inclusion_mode = str(payload.get("inclusion_mode", "scientific_strict"))
        excluded_count = 0
        if inclusion_mode == "scientific_strict":
            before = len(captures)
            captures = [item for item in captures if self._is_scientific_ready(item)]
            excluded_count = before - len(captures)
        records = [self._capture_to_sample(capture, payload) for capture in captures]
        warnings = self._scientific_warnings(records, payload)
        if excluded_count:
            warnings.append(
                {
                    "type": "scientific_readiness_filter",
                    "message": f"{excluded_count} captures were excluded from RFExperimentDatasetV1 because they are not strong_label + accepted + ready_for_training, or legacy valid equivalents.",
                }
            )
        return records, warnings

    def _records_from_external(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        manifest_path = payload.get("source_manifest_path")
        if manifest_path:
            return self._records_from_external_manifest(Path(str(manifest_path)), payload)
        root_path = payload.get("source_path") or payload.get("root_path")
        if not root_path:
            raise ValueError("source_path, root_path or source_manifest_path is required for external dataset import")
        root = Path(str(root_path))
        if not root.exists():
            raise FileNotFoundError(f"External dataset path not found: {root}")
        source_format = str(payload.get("source_format", "auto")).lower()
        files = self._discover_files(root, source_format)
        records = [self._external_file_to_sample(path, root, payload, index) for index, path in enumerate(files)]
        return records, self._scientific_warnings(records, payload)

    def _records_from_external_manifest(self, path: Path, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            records = [self._csv_row_to_sample(row, payload, index, path.parent) for index, row in enumerate(rows)]
            return records, self._scientific_warnings(records, payload)
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, dict) and value.get("schema_version") == RF_EXPERIMENT_DATASET_VERSION:
            samples = [item for item in value.get("samples", []) if isinstance(item, dict)]
            return samples, self._scientific_warnings(samples, payload)
        rows = value.get("samples", value.get("records", [])) if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("External manifest must contain a samples or records list")
        records = [self._generic_row_to_sample(row, payload, index, path.parent) for index, row in enumerate(rows) if isinstance(row, dict)]
        return records, self._scientific_warnings(records, payload)

    def _capture_to_sample(self, capture: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        capture_id = str(capture.get("capture_id") or "capture_unknown")
        label_field = str(payload.get("label_field") or self._default_label_field(str(payload.get("task", "device_fingerprinting"))))
        label = capture.get(label_field) or capture.get("transmitter_id") or capture.get("signal_type") or capture.get("technology")
        raw_file = capture.get("raw_file")
        return self._sample(
            sample_id=capture_id,
            dataset_source=str(capture.get("source") or "internal"),
            task=str(payload.get("task", "device_fingerprinting")),
            label=label,
            label_type=label_field,
            paths={
                "raw_iq_path": raw_file,
                "metadata_path": capture.get("metadata_file"),
                "spectrogram_path": capture.get("spectrogram_path"),
                "waterfall_path": capture.get("waterfall_path"),
                "features_path": capture.get("features_path"),
            },
            rf_metadata=capture,
            split_group=self._split_group(capture, payload),
        )

    def _external_file_to_sample(self, path: Path, root: Path, payload: dict[str, Any], index: int) -> dict[str, Any]:
        relative_parts = path.relative_to(root).parts
        inferred_label = relative_parts[0] if len(relative_parts) > 1 else payload.get("default_label")
        source_format = self._file_format(path, payload)
        metadata_path = self._paired_metadata(path)
        paths = {
            "raw_iq_path": str(path) if source_format in {"iq", "cfile", "sigmf", "numpy", "matlab", "pickle", "hdf5"} else None,
            "metadata_path": str(metadata_path) if metadata_path else None,
            "spectrogram_path": str(path) if source_format == "spectrogram_images" else None,
            "waterfall_path": str(path) if source_format == "waterfall_images" else None,
            "features_path": str(path) if source_format == "csv_features" else None,
        }
        rf_metadata = {
            "source_file": str(path),
            "source_format": source_format,
            "sample_rate_hz": payload.get("sample_rate_hz"),
            "center_frequency_hz": payload.get("center_frequency_hz"),
        }
        return self._sample(
            sample_id=str(payload.get("sample_id_prefix", "external_sample")) + f"_{index:06d}",
            dataset_source=str(payload.get("dataset_source", "external_custom")),
            task=str(payload.get("task", "device_fingerprinting")),
            label=payload.get("default_label") or inferred_label,
            label_type=str(payload.get("label_field") or self._default_label_field(str(payload.get("task", "device_fingerprinting")))),
            paths=paths,
            rf_metadata=rf_metadata,
            split_group=str(payload.get("default_split_group") or inferred_label or path.parent.name),
            sha256=self._sha256(path),
        )

    def _csv_row_to_sample(self, row: dict[str, Any], payload: dict[str, Any], index: int, base: Path) -> dict[str, Any]:
        return self._generic_row_to_sample(row, payload, index, base)

    def _generic_row_to_sample(self, row: dict[str, Any], payload: dict[str, Any], index: int, base: Path) -> dict[str, Any]:
        label_field = str(payload.get("label_field") or self._default_label_field(str(payload.get("task", row.get("task", "device_fingerprinting")))))
        paths = {
            "raw_iq_path": self._resolve_optional_path(row.get("raw_iq_path") or row.get("raw_file") or row.get("iq_path"), base),
            "metadata_path": self._resolve_optional_path(row.get("metadata_path") or row.get("metadata_file"), base),
            "spectrogram_path": self._resolve_optional_path(row.get("spectrogram_path"), base),
            "waterfall_path": self._resolve_optional_path(row.get("waterfall_path"), base),
            "features_path": self._resolve_optional_path(row.get("features_path") or row.get("csv_path"), base),
        }
        return self._sample(
            sample_id=str(row.get("sample_id") or row.get("capture_id") or f"external_sample_{index:06d}"),
            dataset_source=str(row.get("dataset_source") or payload.get("dataset_source", "external_custom")),
            task=str(row.get("task") or payload.get("task", "device_fingerprinting")),
            label=row.get("label") or row.get(label_field),
            label_type=str(row.get("label_type") or label_field),
            paths=paths,
            rf_metadata={**row},
            split_group=str(row.get("split_group") or row.get("session_id") or row.get("capture_id") or f"group_{index:06d}"),
            sha256=row.get("sha256"),
        )

    def _sample(
        self,
        sample_id: str,
        dataset_source: str,
        task: str,
        label: Any,
        label_type: str,
        paths: dict[str, Any],
        rf_metadata: dict[str, Any],
        split_group: str,
        sha256: Any | None = None,
    ) -> dict[str, Any]:
        raw_iq_path = paths.get("raw_iq_path")
        resolved_sha = sha256 or rf_metadata.get("sha256_raw_iq") or rf_metadata.get("sha256")
        if not resolved_sha and raw_iq_path and Path(str(raw_iq_path)).exists():
            resolved_sha = self._sha256(Path(str(raw_iq_path)))
        return {
            "sample_id": sample_id,
            "capture_id": rf_metadata.get("capture_id") or sample_id,
            "dataset_source": dataset_source,
            "schema_version": RF_EXPERIMENT_DATASET_VERSION,
            "task": task,
            "label": None if label in ("", None) else str(label),
            "label_type": label_type,
            "paths": {key: (str(value) if value else None) for key, value in paths.items()},
            "rf_metadata": {
                "sample_rate_hz": rf_metadata.get("sample_rate_hz"),
                "center_frequency_hz": rf_metadata.get("center_frequency_hz"),
                "start_frequency_hz": rf_metadata.get("start_frequency_hz"),
                "stop_frequency_hz": rf_metadata.get("stop_frequency_hz"),
                "bandwidth_hz": rf_metadata.get("bandwidth_hz") or rf_metadata.get("occupied_bandwidth_hz"),
                "datatype": rf_metadata.get("datatype") or rf_metadata.get("file_format") or rf_metadata.get("iq_dtype"),
                "snr_db": rf_metadata.get("snr_db"),
                "gain_db": rf_metadata.get("gain_db"),
                "antenna": rf_metadata.get("antenna"),
                "sdr_device": rf_metadata.get("sdr_device"),
            },
            "session_id": rf_metadata.get("session_id"),
            "day_id": rf_metadata.get("day_id"),
            "receiver_id": rf_metadata.get("receiver_id"),
            "transmitter_id": rf_metadata.get("transmitter_id"),
            "signal_type": rf_metadata.get("signal_type") or rf_metadata.get("technology") or rf_metadata.get("signal_family"),
            "modulation_class": rf_metadata.get("modulation_class") or rf_metadata.get("modulation_family"),
            "environment_id": rf_metadata.get("environment_id") or rf_metadata.get("location_label"),
            "distance_m": rf_metadata.get("distance_m"),
            "qc_summary": self._qc_summary(rf_metadata),
            "sha256": resolved_sha,
            "split_group": split_group,
        }

    def _sample_to_capture_record(self, sample: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        paths = sample.get("paths") if isinstance(sample.get("paths"), dict) else {}
        rf = sample.get("rf_metadata") if isinstance(sample.get("rf_metadata"), dict) else {}
        label_type = str(sample.get("label_type") or "label")
        record = {
            "source": sample.get("dataset_source"),
            "capture_id": sample.get("capture_id") or sample.get("sample_id"),
            "raw_file": paths.get("raw_iq_path"),
            "metadata_file": paths.get("metadata_path"),
            "spectrogram_path": paths.get("spectrogram_path"),
            "waterfall_path": paths.get("waterfall_path"),
            "features_path": paths.get("features_path"),
            "datatype": rf.get("datatype") or "complex64",
            "sample_rate_hz": rf.get("sample_rate_hz"),
            "center_frequency_hz": rf.get("center_frequency_hz"),
            "duration_seconds": rf.get("duration_seconds"),
            "receiver_id": sample.get("receiver_id"),
            "transmitter_id": sample.get("transmitter_id") or (sample.get("label") if label_type == "transmitter_id" else None),
            "signal_type": sample.get("signal_type") or (sample.get("label") if label_type == "signal_type" else None),
            "modulation_class": sample.get("modulation_class") or (sample.get("label") if label_type == "modulation_class" else None),
            "session_id": sample.get("session_id") or sample.get("split_group"),
            "day_id": sample.get("day_id"),
            "environment_id": sample.get("environment_id"),
            "distance_m": sample.get("distance_m"),
            "qc_summary": sample.get("qc_summary"),
            "qc_status": (sample.get("qc_summary") or {}).get("qc_status") if isinstance(sample.get("qc_summary"), dict) else None,
            "snr_db": rf.get("snr_db"),
            "sha256_raw_iq": sample.get("sha256"),
            "dataset_version": manifest.get("dataset_version"),
            "dataset_schema": RF_EXPERIMENT_DATASET_VERSION,
            "split_group": sample.get("split_group"),
            label_type: sample.get("label"),
        }
        record["label"] = sample.get("label")
        return record

    def _preview_response(self, payload: dict[str, Any], records: list[dict[str, Any]], warnings: list[dict[str, Any]], source_kind: str) -> dict[str, Any]:
        return {
            "preview_only": True,
            "schema_version": RF_EXPERIMENT_DATASET_VERSION,
            "dataset_id": payload.get("dataset_id", "rf_experiment_dataset"),
            "dataset_version": payload.get("dataset_version", "unversioned"),
            "source_kind": source_kind,
            "sample_count": len(records),
            "label_schema": self._label_schema(records),
            "task_counts": self._count(records, "task"),
            "dataset_sources": self._count(records, "dataset_source"),
            "compatibility": self._compatibility(records),
            "warnings": warnings,
            "sample_preview": records[:10],
        }

    def _write_manifest(self, payload: dict[str, Any], records: list[dict[str, Any]], warnings: list[dict[str, Any]], source_kind: str) -> dict[str, Any]:
        dataset_id = str(payload.get("dataset_id", "rf_experiment_dataset"))
        dataset_version = str(payload.get("dataset_version", f"{dataset_id}_v1"))
        output_dir = Path(str(payload.get("output_dir") or (self.dataset_root / dataset_id / dataset_version)))
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": RF_EXPERIMENT_DATASET_VERSION,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "dataset_source": source_kind,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator_version": "rf_experiment_lab_dataset_builder_v1",
            "task": payload.get("task"),
            "representation": payload.get("representation"),
            "label_schema": self._label_schema(records),
            "normalization_policy": payload.get("normalization_policy", "experiment_specific_logged_in_training_config"),
            "split_policy": {
                "default_strategy": payload.get("split_strategy", "session_disjoint"),
                "scientific_default": True,
                "random_split_allowed_only_for_debug": True,
            },
            "compatibility": self._compatibility(records),
            "warnings": warnings,
            "samples": records,
        }
        manifest_path = output_dir / "rf_experiment_dataset_v1.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            **self._preview_response(payload, records, warnings, source_kind),
            "preview_only": False,
            "manifest_path": str(manifest_path),
            "manifest_sha256": self._sha256(manifest_path),
        }

    def _compatibility(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "E1_raw_iq_cnn1d": self._count_compatible(records, required_paths=["raw_iq_path"], label_types=["transmitter_id", "signal_type", "modulation_class"]),
            "E3_spectrogram_cnn2d": self._count_compatible(records, any_paths=["raw_iq_path", "spectrogram_path", "waterfall_path"], label_types=["transmitter_id", "signal_type", "modulation_class"]),
            "E5_spectral_feature_baseline": self._count_compatible(records, any_paths=["raw_iq_path", "features_path"], label_types=["transmitter_id", "signal_type", "modulation_class"]),
        }

    def _count_compatible(
        self,
        records: list[dict[str, Any]],
        required_paths: list[str] | None = None,
        any_paths: list[str] | None = None,
        label_types: list[str] | None = None,
    ) -> dict[str, Any]:
        usable = []
        for record in records:
            paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
            has_required = all(paths.get(path) for path in (required_paths or []))
            has_any = True if not any_paths else any(paths.get(path) for path in any_paths)
            has_label = record.get("label") not in (None, "") and (not label_types or record.get("label_type") in label_types)
            if has_required and has_any and has_label:
                usable.append(record)
        return {"usable_samples": len(usable), "total_samples": len(records)}

    def _scientific_warnings(self, records: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        source = str(payload.get("dataset_source", "")).lower()
        task = str(payload.get("task", "")).lower()
        if source in {"radioml", "sig53"} and task == "device_fingerprinting":
            warnings.append(
                {
                    "type": "dataset_task_mismatch",
                    "message": "RadioML and Sig53 are modulation/signal-recognition datasets and should not be used as primary physical fingerprinting evidence.",
                }
            )
        if source in {"oracle", "wisig"} and task in {"modulation_classification", "signal_recognition"}:
            warnings.append(
                {
                    "type": "dataset_task_note",
                    "message": "ORACLE and WiSig are primarily useful for RF fingerprinting/domain-shift studies; verify label semantics before signal-recognition training.",
                }
            )
        split_strategy = str(payload.get("split_strategy", "session_disjoint"))
        if split_strategy == "random":
            warnings.append({"type": "debug_split", "message": "random split is allowed only for quick debugging, not as a primary scientific result."})
        missing_hashes = sum(1 for record in records if not record.get("sha256"))
        if missing_hashes:
            warnings.append({"type": "missing_hashes", "message": f"{missing_hashes} samples do not have SHA-256 evidence hashes."})
        return warnings

    def _is_scientific_ready(self, capture: dict[str, Any]) -> bool:
        label = capture.get("transmitter_id") or capture.get("signal_type") or capture.get("modulation_class") or capture.get("label")
        label_status = capture.get("label_status")
        review_status = capture.get("review_status")
        readiness = capture.get("training_readiness")
        capture_quality = capture.get("capture_quality")
        if label_status or review_status or readiness:
            return (
                label not in (None, "", "unknown")
                and label_status == "strong_label"
                and review_status == "accepted"
                and readiness == "ready_for_training"
                and capture_quality in {None, "valid"}
            )
        return label not in (None, "", "unknown") and capture.get("qc_status") == "valid"

    def _discover_files(self, root: Path, source_format: str) -> list[Path]:
        suffixes = {
            "iq": {".iq"},
            "cfile": {".cfile"},
            "sigmf": {".sigmf-data"},
            "hdf5": {".h5", ".hdf5"},
            "numpy": {".npy", ".npz"},
            "matlab": {".mat"},
            "pickle": {".pkl", ".pickle"},
            "csv_features": {".csv"},
            "spectrogram_images": {".png", ".jpg", ".jpeg", ".npy"},
            "waterfall_images": {".png", ".jpg", ".jpeg", ".npy"},
            "auto": {".iq", ".cfile", ".sigmf-data", ".h5", ".hdf5", ".npy", ".npz", ".mat", ".pkl", ".pickle", ".csv", ".png", ".jpg", ".jpeg"},
        }
        allowed = suffixes.get(source_format, suffixes["auto"])
        return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in allowed)

    def _file_format(self, path: Path, payload: dict[str, Any]) -> str:
        explicit = str(payload.get("source_format", "auto")).lower()
        if explicit != "auto":
            return explicit
        suffix = path.suffix.lower()
        if suffix == ".iq":
            return "iq"
        if suffix == ".cfile":
            return "cfile"
        if suffix == ".sigmf-data":
            return "sigmf"
        if suffix in {".h5", ".hdf5"}:
            return "hdf5"
        if suffix in {".npy", ".npz"}:
            return "numpy"
        if suffix == ".mat":
            return "matlab"
        if suffix in {".pkl", ".pickle"}:
            return "pickle"
        if suffix == ".csv":
            return "csv_features"
        return "spectrogram_images" if suffix in {".png", ".jpg", ".jpeg"} else "unknown"

    def _paired_metadata(self, path: Path) -> Path | None:
        candidates = [path.with_suffix(".json"), Path(str(path) + ".json")]
        if path.name.endswith(".sigmf-data"):
            candidates.append(path.with_name(path.name.replace(".sigmf-data", ".sigmf-meta")))
        return next((candidate for candidate in candidates if candidate.exists()), None)

    def _resolve_optional_path(self, value: Any, base: Path) -> str | None:
        if not value:
            return None
        path = Path(str(value))
        if not path.is_absolute():
            path = base / path
        return str(path)

    def _default_label_field(self, task: str) -> str:
        if task == "device_fingerprinting":
            return "transmitter_id"
        if task in {"signal_recognition", "modulation_classification"}:
            return "modulation_class"
        return "label"

    def _qc_summary(self, rf_metadata: dict[str, Any]) -> dict[str, Any]:
        existing = rf_metadata.get("qc_summary")
        if isinstance(existing, dict):
            return existing
        quality = rf_metadata.get("quality_metrics")
        if isinstance(quality, dict):
            return {
                "qc_status": rf_metadata.get("qc_status", "accepted"),
                "snr_db": quality.get("estimated_snr_db") or quality.get("snr_db"),
                "clipping_detected": quality.get("clipping_detected"),
                "dc_offset_level": quality.get("dc_offset_level"),
                "iq_imbalance_estimate": quality.get("iq_imbalance_estimate"),
            }
        return {"qc_status": rf_metadata.get("qc_status", "unknown")}

    def _split_group(self, record: dict[str, Any], payload: dict[str, Any]) -> str:
        fields = payload.get("split_group_fields") or ["session_id", "day_id", "receiver_id", "environment_id", "capture_id"]
        values = [str(record.get(field)) for field in fields if record.get(field) not in (None, "")]
        return "|".join(values) if values else str(record.get("capture_id") or "ungrouped")

    def _label_schema(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        labels = sorted({str(record.get("label")) for record in records if record.get("label") not in (None, "")})
        return {
            "label_types": sorted({str(record.get("label_type") or "label") for record in records}),
            "labels": labels,
            "class_count": len(labels),
            "label_counts": self._count(records, "label"),
        }

    def _count(self, records: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            value = str(record.get(key) or "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
