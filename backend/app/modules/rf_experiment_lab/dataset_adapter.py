from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.rf_experiment_lab.unified_dataset import RFExperimentDatasetV1Builder
from app.modules.rf_experiment_lab.internal_dataset_lab import RFExperimentInternalDatasetLab


class DatasetAdapter:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.fingerprinting_capture_dir = storage_root / "fingerprinting" / "captures"
        self.signal_understanding_registry = storage_root / "rf_signal_understanding" / "capture_registry" / "captures.json"
        self.unified_dataset = RFExperimentDatasetV1Builder(storage_root)
        self.internal_dataset_lab = RFExperimentInternalDatasetLab(storage_root)

    def list_existing_captures(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        records.extend(self.internal_dataset_lab.as_capture_records())
        records.extend(self._read_fingerprinting_captures())
        records.extend(self._read_signal_understanding_captures())
        return sorted(records, key=lambda item: str(item.get("capture_id", "")))

    def dataset_summary(self) -> dict[str, Any]:
        captures = self.list_existing_captures()
        return {
            "capture_count": len(captures),
            "sources": {
                "fingerprinting": str(self.fingerprinting_capture_dir),
                "rf_signal_understanding": str(self.signal_understanding_registry),
                "rf_experiment_lab_internal": str(self.internal_dataset_lab.registry_path),
            },
            "technologies": sorted({str(item.get("technology") or item.get("transmitter_class") or "unknown") for item in captures}),
            "splits": self._count_by(captures, "dataset_split"),
            "sessions": self._count_by(captures, "session_id"),
            "qc_status": self._count_by(captures, "qc_status"),
            "unified_dataset_schema": "RFExperimentDatasetV1",
            "supported_external_sources": self.unified_dataset.describe_supported_sources(),
        }

    def list_training_records(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        manifest_path = config.get("dataset_manifest_path") or config.get("rf_experiment_dataset_path")
        if manifest_path:
            records = self.unified_dataset.records_for_training(str(manifest_path))
        else:
            records = self.list_existing_captures()
        return self.filter_training_records(records, config)

    def filter_training_records(self, records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
        policy = str(config.get("training_readiness_policy") or "scientific_strict").lower()
        if policy in {"all_debug", "debug_all", "none"} or bool(config.get("include_non_ready")):
            return records
        filtered = []
        for record in records:
            if self._is_training_ready_for_policy(record, policy):
                filtered.append(record)
        return filtered

    def training_eligibility_summary(self, config: dict[str, Any]) -> dict[str, Any]:
        manifest_path = config.get("dataset_manifest_path") or config.get("rf_experiment_dataset_path")
        if manifest_path:
            records = self.unified_dataset.records_for_training(str(manifest_path))
        else:
            records = self.list_existing_captures()
        ids = {str(item) for item in config.get("capture_ids", [])}
        if ids:
            records = [item for item in records if str(item.get("capture_id")) in ids]
        policy = str(config.get("training_readiness_policy") or "scientific_strict").lower()
        reasons: dict[str, int] = {}
        eligible = 0
        examples: list[dict[str, Any]] = []
        for record in records:
            reason = self._eligibility_reason(record, policy)
            if reason == "eligible":
                eligible += 1
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
                if len(examples) < 12:
                    examples.append(
                        {
                            "capture_id": record.get("capture_id") or record.get("sample_id"),
                            "reason": reason,
                            "label_status": record.get("label_status"),
                            "review_status": record.get("review_status"),
                            "training_readiness": record.get("training_readiness"),
                            "capture_quality": record.get("capture_quality") or record.get("qc_status"),
                            "source": record.get("source") or record.get("dataset_source"),
                        }
                    )
        return {
            "policy": policy,
            "total_considered": len(records),
            "eligible_count": eligible,
            "excluded_count": max(len(records) - eligible, 0),
            "exclusion_reasons": reasons,
            "excluded_examples": examples,
            "policy_notes": self._policy_notes(policy),
        }

    def validate_training_label_policy(self, records: list[dict[str, Any]], label_field: str, *, allow_weak_labels: bool = False) -> dict[str, Any]:
        unknown_values = {"", "unknown", "tx_unknown", "unlabeled_transmitter", "rsu_unlabeled", "profile_pending", "band_profile_pending", "weak_profile_pending", "unresolved_rf_signal", "weak_unresolved_rf_signal"}
        missing = []
        weak = []
        values = []
        for record in records:
            capture_id = str(record.get("capture_id") or record.get("sample_id") or "unknown")
            value = record.get(label_field)
            if value in (None, "") and record.get("label_type") == label_field:
                value = record.get("label")
            text = str(value or "").strip()
            if text.lower() in unknown_values:
                missing.append(capture_id)
                continue
            label_status = str(record.get("label_status") or "").strip().lower()
            if (label_status == "weak_label" or text.lower().startswith("weak_")) and not allow_weak_labels:
                weak.append(capture_id)
            values.append(text)
        return {
            "valid": not missing and not weak,
            "missing_capture_ids": missing,
            "weak_label_capture_ids": weak,
            "labels": sorted(set(values)),
            "class_count": len(set(values)),
        }

    def rf_experiment_dataset_v1_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.unified_dataset.preview_from_internal(self.list_existing_captures(), payload)

    def rf_experiment_dataset_v1_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.unified_dataset.export_from_internal(self.list_existing_captures(), payload)

    def external_dataset_import_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.unified_dataset.preview_import(payload)

    def external_dataset_import_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.unified_dataset.export_import(payload)

    def supported_dataset_sources(self) -> dict[str, Any]:
        return self.unified_dataset.describe_supported_sources()

    def validate_required_metadata(self, record: dict[str, Any]) -> dict[str, Any]:
        required = [
            "capture_id",
            "raw_file",
            "metadata_file",
            "datatype",
            "sample_rate_hz",
            "center_frequency_hz",
            "duration_seconds",
            "receiver_id",
            "timestamp_utc",
            "session_id",
        ]
        missing = [field for field in required if record.get(field) in (None, "")]
        return {"valid": not missing, "missing": missing}

    def _read_fingerprinting_captures(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.fingerprinting_capture_dir.exists():
            return records
        for path in sorted(self.fingerprinting_capture_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            records.append(self._normalize_fingerprinting(raw, path))
        return records

    def _read_signal_understanding_captures(self) -> list[dict[str, Any]]:
        if not self.signal_understanding_registry.exists():
            return []
        try:
            raw = json.loads(self.signal_understanding_registry.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        return [self._normalize_signal_understanding(item) for item in raw if isinstance(item, dict)]

    def _normalize_fingerprinting(self, record: dict[str, Any], path: Path) -> dict[str, Any]:
        config = record.get("capture_config", {}) if isinstance(record.get("capture_config"), dict) else {}
        transmitter = record.get("transmitter", {}) if isinstance(record.get("transmitter"), dict) else {}
        scenario = record.get("scenario", {}) if isinstance(record.get("scenario"), dict) else {}
        quality = record.get("quality_metrics", {}) if isinstance(record.get("quality_metrics"), dict) else {}
        review = record.get("quality_review", {}) if isinstance(record.get("quality_review"), dict) else {}
        artifacts = record.get("artifacts", {}) if isinstance(record.get("artifacts"), dict) else {}
        return {
            "source": "fingerprinting",
            "capture_id": record.get("capture_id") or path.stem,
            "raw_file": artifacts.get("iq_file") or config.get("output_path"),
            "metadata_file": artifacts.get("metadata_file") or str(path),
            "datatype": config.get("sample_dtype", "complex64"),
            "sample_rate_hz": config.get("sample_rate_hz"),
            "center_frequency_hz": config.get("center_frequency_hz"),
            "duration_seconds": config.get("capture_duration_s"),
            "gain_db": config.get("gain_settings", {}).get("gain_db") if isinstance(config.get("gain_settings"), dict) else None,
            "antenna": config.get("antenna_port"),
            "sdr_device": config.get("sdr_model"),
            "receiver_id": config.get("sdr_serial") or config.get("sdr_model"),
            "timestamp_utc": scenario.get("timestamp_utc"),
            "location_label": scenario.get("environment"),
            "operator": scenario.get("operator"),
            "technology": transmitter.get("family") or transmitter.get("transmitter_class"),
            "signal_type": transmitter.get("signal_type") or transmitter.get("transmitter_class"),
            "modulation_class": transmitter.get("modulation_class") or transmitter.get("family"),
            "protocol_family": transmitter.get("protocol_family") or transmitter.get("family"),
            "band_label": transmitter.get("band_label"),
            "profile_key": transmitter.get("profile_key"),
            "transmitter_id": transmitter.get("transmitter_id"),
            "device_model": transmitter.get("transmitter_label"),
            "session_id": record.get("session_id"),
            "environment_id": scenario.get("environment"),
            "distance_m": scenario.get("distance_m"),
            "dataset_split": record.get("dataset_split"),
            "qc_status": review.get("status"),
            "capture_quality": review.get("capture_quality"),
            "label_status": review.get("label_status"),
            "review_status": review.get("review_status"),
            "training_readiness": review.get("training_readiness"),
            "snr_db": quality.get("estimated_snr_db"),
            "sha256_raw_iq": artifacts.get("sha256"),
        }

    def _normalize_signal_understanding(self, record: dict[str, Any]) -> dict[str, Any]:
        profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
        return {
            "source": "rf_signal_understanding",
            "capture_id": record.get("capture_id"),
            "raw_file": record.get("iq_path") or record.get("raw_file") or record.get("file_path"),
            "metadata_file": record.get("metadata_path") or record.get("metadata_file"),
            "datatype": record.get("datatype") or record.get("file_format") or "complex64",
            "sample_rate_hz": record.get("sample_rate_hz"),
            "center_frequency_hz": record.get("center_frequency_hz"),
            "duration_seconds": record.get("duration_seconds") or record.get("duration_s"),
            "receiver_id": record.get("receiver_id") or record.get("source"),
            "timestamp_utc": record.get("timestamp_utc") or record.get("created_at"),
            "technology": record.get("technology") or record.get("signal_family") or profile.get("family"),
            "session_id": record.get("session_id"),
            "signal_type": profile.get("signal_type"),
            "modulation_class": profile.get("modulation_class"),
            "dataset_split": record.get("dataset_split") or profile.get("dataset_split"),
            "qc_status": record.get("qc_status"),
            "label_status": record.get("label_status") or profile.get("label_status"),
            "review_status": record.get("review_status") or profile.get("review_status"),
            "training_readiness": record.get("training_readiness") or profile.get("training_readiness"),
        }

    def _is_scientific_or_external_ready(self, record: dict[str, Any]) -> bool:
        return self._eligibility_reason(record, "scientific_strict") == "eligible"

    def _is_training_ready_for_policy(self, record: dict[str, Any], policy: str) -> bool:
        return self._eligibility_reason(record, policy) == "eligible"

    def _eligibility_reason(self, record: dict[str, Any], policy: str) -> str:
        if policy in {"all_debug", "debug_all", "none"}:
            return "eligible"
        label = record.get("transmitter_id") or record.get("signal_type") or record.get("modulation_class") or record.get("label")
        if label in (None, "", "unknown", "tx_unknown", "unlabeled_transmitter", "rsu_unlabeled"):
            return "missing_or_unknown_label"
        label_status = record.get("label_status")
        review_status = record.get("review_status")
        readiness = record.get("training_readiness")
        capture_quality = record.get("capture_quality")
        if label_status or review_status or readiness:
            if label_status != "strong_label":
                return "label_not_strong"
            if review_status in {"rejected", "manual_override"}:
                return f"review_{review_status}"
            if policy in {"training_draft", "draft", "candidate"}:
                if readiness not in {"candidate", "ready_for_training"}:
                    return "not_candidate_or_ready"
                if capture_quality in {"invalid"}:
                    return "capture_quality_invalid"
                return "eligible"
            if review_status != "accepted":
                return "review_not_accepted"
            if readiness != "ready_for_training":
                return "not_ready_for_training"
            if capture_quality not in {None, "valid"}:
                return f"capture_quality_{capture_quality}"
            return "eligible"
        if policy in {"training_draft", "draft", "candidate"}:
            return "eligible" if record.get("qc_status") in {None, "valid", "accepted", "warning", "doubtful"} else "qc_not_accepted"
        return "eligible" if record.get("qc_status") in {None, "valid", "accepted"} else "qc_not_valid"

    @staticmethod
    def _policy_notes(policy: str) -> list[str]:
        if policy in {"training_draft", "draft", "candidate"}:
            return [
                "Training Draft accepts candidate captures with strong labels and non-invalid QC for exploratory baselines.",
                "Results produced with candidate data are not primary scientific evidence until reviewed as ready_for_training.",
            ]
        if policy in {"all_debug", "debug_all", "none"}:
            return [
                "Debug mode bypasses readiness gates and may include weak, unlabeled or not-ready captures.",
                "Do not report debug runs as scientific benchmark results.",
            ]
        return [
            "Scientific strict accepts only strong_label, accepted, ready_for_training and valid captures.",
            "Candidate, doubtful, weak-label and manual-override samples are excluded by design.",
        ]

    def _count_by(self, captures: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for capture in captures:
            value = str(capture.get(key) or "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts
