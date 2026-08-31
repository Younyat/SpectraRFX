from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.config.runtime_settings import get_runtime_value
from app.modules.rf_intelligence.knowledge_base import resolve_band_profile


DEFAULT_THRESHOLDS = {
    "min_valid_snr_db": float(get_runtime_value("QC_MIN_VALID_SNR_DB", 12.0)),
    "min_doubtful_snr_db": 6.0,
    "max_valid_clipping_pct": float(get_runtime_value("QC_MAX_VALID_CLIPPING_PCT", 0.5)),
    "max_doubtful_clipping_pct": 2.0,
    "max_valid_frequency_offset_hz": 5_000.0,
    "max_doubtful_frequency_offset_hz": 20_000.0,
    "min_valid_burst_duration_ms": 1.0,
    "max_silence_pct": float(get_runtime_value("QC_MAX_SILENCE_PCT", 85.0)),
}


QC_POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "exploratory": {
        "min_snr_db": 3.0,
        "max_clipping_percentage": 5.0,
        "min_occupied_bandwidth_hz": 0.0,
        "max_occupied_bandwidth_hz": 0.0,
        "max_frequency_offset_hz": 100_000.0,
        "min_signal_duration_ms": 0.0,
        "max_silence_percentage": 95.0,
        "require_label": False,
        "require_metadata": False,
        "allow_weak_label": True,
        "allow_unlabeled": True,
        "allow_manual_override": False,
    },
    "training_draft": {
        "min_snr_db": 6.0,
        "max_clipping_percentage": 2.0,
        "min_occupied_bandwidth_hz": 0.0,
        "max_occupied_bandwidth_hz": 0.0,
        "max_frequency_offset_hz": 50_000.0,
        "min_signal_duration_ms": 1.0,
        "max_silence_percentage": 90.0,
        "require_label": False,
        "require_metadata": True,
        "allow_weak_label": True,
        "allow_unlabeled": True,
        "allow_manual_override": False,
    },
    "scientific": {
        "min_snr_db": 12.0,
        "max_clipping_percentage": 0.5,
        "min_occupied_bandwidth_hz": 1.0,
        "max_occupied_bandwidth_hz": 0.0,
        "max_frequency_offset_hz": 5_000.0,
        "min_signal_duration_ms": 1.0,
        "max_silence_percentage": 85.0,
        "require_label": True,
        "require_metadata": True,
        "allow_weak_label": False,
        "allow_unlabeled": False,
        "allow_manual_override": False,
    },
    "manual_override": {
        "min_snr_db": 0.0,
        "max_clipping_percentage": 100.0,
        "min_occupied_bandwidth_hz": 0.0,
        "max_occupied_bandwidth_hz": 0.0,
        "max_frequency_offset_hz": 0.0,
        "min_signal_duration_ms": 0.0,
        "max_silence_percentage": 100.0,
        "require_label": False,
        "require_metadata": False,
        "allow_weak_label": True,
        "allow_unlabeled": True,
        "allow_manual_override": True,
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _db10(value: float) -> float:
    return 10.0 * np.log10(max(float(value), 1e-20))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(parsed):
        return None
    return parsed


class FingerprintingService:
    def __init__(self, storage_root: Path) -> None:
        self._root = storage_root
        self._captures_dir = self._root / "captures"
        self._captures_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_root = self._root.parents[5]

    def get_dashboard_summary(self) -> dict[str, Any]:
        captures = self.list_capture_records()
        by_split = {
            "train": sum(1 for item in captures if item.get("dataset_split") == "train"),
            "val": sum(1 for item in captures if item.get("dataset_split") == "val"),
            "predict": sum(1 for item in captures if item.get("dataset_split") == "predict"),
        }
        return {
            "modes": [
                {
                    "id": "live_monitor",
                    "title": "Live Monitor",
                    "goal": "Tune the SDR, observe spectrum occupancy, verify live signal presence, and stabilize RF settings.",
                },
                {
                    "id": "guided_capture",
                    "title": "Guided Capture",
                    "goal": "Acquire labeled transmitter bursts with reproducible receiver settings and mandatory metadata.",
                },
                {
                    "id": "dataset_builder",
                    "title": "Dataset Builder",
                    "goal": "Review captures, reject weak acquisitions, segment regions of interest, and export curated datasets.",
                },
            ],
            "thresholds": deepcopy(DEFAULT_THRESHOLDS),
            "summary": {
                "total_captures": len(captures),
                "valid_captures": sum(1 for item in captures if item["quality_review"]["status"] == "valid"),
                "doubtful_captures": sum(1 for item in captures if item["quality_review"]["status"] == "doubtful"),
                "rejected_captures": sum(1 for item in captures if item["quality_review"]["status"] == "rejected"),
                "by_split": by_split,
            },
            "required_metadata": [
                "transmitter_id",
                "transmitter_class",
                "session_id",
                "sdr_model",
                "sdr_serial",
                "center_frequency_hz",
                "sample_rate_hz",
                "gain_settings",
                "capture_duration_s",
                "estimated_snr_db",
                "quality_flags",
                "sha256",
            ],
        }

    def list_capture_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self._captures_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                records.append(self._load_record(path))
            except Exception:
                continue
        return records

    def list_capture_records_by_split(self, dataset_split: str) -> list[dict[str, Any]]:
        normalized = self._normalize_split(dataset_split)
        return [item for item in self.list_capture_records() if item.get("dataset_split") == normalized]

    def get_capture_record(self, capture_id: str) -> dict[str, Any]:
        path = self._capture_path(capture_id)
        if not path.exists():
            raise ValueError(f"Fingerprinting capture not found: {capture_id}")
        return self._load_record(path)

    def create_capture_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._normalize_record(payload, capture_id=payload.get("capture_id"))
        self._save_record(record)
        return record

    def review_capture_record(self, capture_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.get_capture_record(capture_id)
        quality_review = record["quality_review"]
        quality_review["operator_decision"] = payload.get("operator_decision", quality_review.get("operator_decision"))
        quality_review["review_notes"] = payload.get("review_notes", quality_review.get("review_notes", ""))
        quality_review["export_windows"] = payload.get("export_windows", quality_review.get("export_windows", []))
        quality_review["updated_at_utc"] = _utc_now()
        transmitter = record.get("transmitter", {}) if isinstance(record.get("transmitter"), dict) else {}
        capture_config = record.get("capture_config", {}) if isinstance(record.get("capture_config"), dict) else {}
        scenario = record.get("scenario", {}) if isinstance(record.get("scenario"), dict) else {}
        artifacts = record.get("artifacts", {}) if isinstance(record.get("artifacts"), dict) else {}
        metrics = record.get("quality_metrics", {}) if isinstance(record.get("quality_metrics"), dict) else {}
        metrics["signal_family"] = record.get("signal_family", metrics.get("signal_family", "unknown"))
        metrics["qc_profile_id"] = record.get("qc_profile_id", metrics.get("qc_profile_id"))
        metrics["effective_bandwidth_hz"] = capture_config.get("effective_bandwidth_hz", metrics.get("effective_bandwidth_hz", 0.0))
        qc_policy = self._qc_policy(
            {
                "qc_policy_profile": quality_review.get("qc_policy_profile", "scientific"),
                "qc_thresholds": quality_review.get("qc_thresholds", {}),
            }
        )
        label_status = quality_review.get("label_status") or self._label_status({}, transmitter)
        metadata_check = self._metadata_check(capture_config, transmitter, scenario, artifacts)
        evaluated = self._evaluate_quality(
            metrics,
            quality_review["operator_decision"],
            qc_policy,
            label_status,
            metadata_check,
            str(quality_review.get("manual_override_reason", "") or ""),
        )
        quality_review["status"] = evaluated["status"]
        quality_review["capture_quality"] = evaluated["capture_quality"]
        quality_review["label_status"] = label_status
        quality_review["qc_policy_profile"] = evaluated["qc_policy_profile"]
        quality_review["qc_thresholds"] = qc_policy
        quality_review["metadata_check"] = metadata_check
        if quality_review["operator_decision"] == "valid":
            quality_review["review_status"] = "accepted" if evaluated["capture_quality"] == "valid" else "needs_review"
            quality_review["training_readiness"] = "ready_for_training" if label_status == "strong_label" and evaluated["capture_quality"] == "valid" and metadata_check.get("valid", False) else "candidate"
        elif quality_review["operator_decision"] == "rejected":
            quality_review["review_status"] = "rejected"
            quality_review["training_readiness"] = "not_ready"
        else:
            quality_review["review_status"] = evaluated["review_status"]
            quality_review["training_readiness"] = evaluated["training_readiness"]
        quality_review["reasons"] = evaluated["reasons"]
        quality_review["quality_flags"] = evaluated["flags"]
        quality_review["qc_profile_id"] = evaluated["qc_profile_id"]
        self._save_record(record)
        return record

    def delete_capture_record(self, capture_id: str, delete_artifacts: bool = True) -> dict[str, Any]:
        path = self._capture_path(capture_id)
        if not path.exists():
            raise ValueError(f"Fingerprinting capture not found: {capture_id}")
        record = self._load_record(path)
        removed_files: list[str] = []
        if delete_artifacts:
            removed_files = self._delete_unreferenced_artifacts(record, excluded_capture_id=capture_id)
        path.unlink()
        return {
            "capture_id": capture_id,
            "deleted": True,
            "deleted_artifacts": removed_files,
        }

    def _infer_signal_family(self, capture: dict[str, Any], defaults: dict[str, Any] | None = None) -> str:
        defaults = defaults or {}
        explicit = str(defaults.get("signal_family") or capture.get("signal_family") or "").strip().lower()
        if explicit in {"continuous_fm", "burst_rf", "packet_rf", "unknown"}:
            return explicit
        if explicit in {"broadcast_fm", "weather_broadcast", "digital_broadcast", "digital_tv", "cellular_lte", "cellular_5g"}:
            return "continuous_fm"
        if explicit and explicit != "unknown":
            return "burst_rf"
        hint = str(capture.get("modulation_hint") or capture.get("transmitter_class") or "").strip().lower()
        if hint in {"fm", "wfm", "broadcast_fm", "continuous_fm"}:
            return "continuous_fm"
        if hint in {"ask", "ook", "fsk", "psk", "lora", "ble", "packet_rf"}:
            return "burst_rf"
        return "unknown"

    @staticmethod
    def _qc_profile_for_signal_family(signal_family: str) -> dict[str, Any]:
        if signal_family == "continuous_fm":
            return {
                "qc_profile_id": "continuous_fm_v1",
                "signal_family": "continuous_fm",
                "detection_method": "spectral_peak_detection",
                "roi_policy": "full_capture_or_centered_channel",
                "use_silence_metric": False,
                "use_channel_presence_ratio": True,
                "use_spectral_snr": True,
                "use_occupied_bandwidth": True,
                "use_edge_margin": True,
            }
        return {
            "qc_profile_id": "burst_rf_v1",
            "signal_family": signal_family if signal_family in {"burst_rf", "packet_rf"} else "burst_rf",
            "detection_method": "auto_energy_burst",
            "roi_policy": "burst_region",
            "use_silence_metric": True,
            "use_burst_start": True,
            "use_burst_end": True,
        }

    @staticmethod
    def _iq_file_diagnostics(samples: np.ndarray, sample_rate_hz: float, iq_dtype: str, peak_offset_hz: float | None = None) -> dict[str, Any]:
        if samples.size == 0:
            return {"num_complex_samples": 0, "duration_seconds": 0.0, "dtype": iq_dtype, "endianness": "native"}
        abs_samples = np.abs(samples)
        power = abs_samples ** 2
        finite = np.isfinite(samples.real) & np.isfinite(samples.imag)
        return {
            "num_complex_samples": int(samples.size),
            "duration_seconds": float(samples.size / sample_rate_hz) if sample_rate_hz > 0 else 0.0,
            "dtype": iq_dtype or "complex64",
            "endianness": "native",
            "i_min": float(np.nanmin(samples.real)),
            "i_max": float(np.nanmax(samples.real)),
            "q_min": float(np.nanmin(samples.imag)),
            "q_max": float(np.nanmax(samples.imag)),
            "mean_power_db": float(_db10(float(np.nanmean(power)))),
            "rms_power_db": float(_db10(float(np.sqrt(max(float(np.nanmean(power)), 0.0))))),
            "zero_ratio": float(np.mean(abs_samples == 0.0)),
            "near_zero_ratio": float(np.mean(abs_samples < 1e-8)),
            "nan_ratio": float(np.mean(np.isnan(samples.real) | np.isnan(samples.imag))),
            "inf_ratio": float(np.mean(np.isinf(samples.real) | np.isinf(samples.imag))),
            "finite_ratio": float(np.mean(finite)),
            "spectral_peak_offset_hz": _safe_float(peak_offset_hz),
        }

    def compare_rf_captures(self, left_capture_id: str, right_capture_id: str) -> dict[str, Any]:
        left = self.get_capture_record(left_capture_id)
        right = self.get_capture_record(right_capture_id)

        def metric(record: dict[str, Any], key: str, default: float = 0.0) -> float:
            return float((record.get("quality_metrics") or {}).get(key, default) or default)

        def cfg(record: dict[str, Any], key: str, default: float = 0.0) -> float:
            return float((record.get("capture_config") or {}).get(key, default) or default)

        def diag(record: dict[str, Any], key: str, default: float = 0.0) -> float:
            return float((record.get("iq_file_diagnostics") or {}).get(key, default) or default)

        differences = {
            "sample_rate_diff_hz": cfg(left, "sample_rate_hz") - cfg(right, "sample_rate_hz"),
            "duration_diff_s": cfg(left, "capture_duration_s") - cfg(right, "capture_duration_s"),
            "mean_power_diff_db": diag(left, "mean_power_db") - diag(right, "mean_power_db"),
            "spectral_peak_diff_hz": metric(left, "peak_frequency_hz") - metric(right, "peak_frequency_hz"),
            "occupied_bw_diff_hz": metric(left, "occupied_bandwidth_hz") - metric(right, "occupied_bandwidth_hz"),
            "selected_snr_diff_db": metric(left, "selected_snr_db", metric(left, "estimated_snr_db")) - metric(right, "selected_snr_db", metric(right, "estimated_snr_db")),
            "zero_ratio_diff": diag(left, "zero_ratio") - diag(right, "zero_ratio"),
            "near_zero_ratio_diff": diag(left, "near_zero_ratio") - diag(right, "near_zero_ratio"),
        }
        method_left = (left.get("burst_detection") or {}).get("method")
        method_right = (right.get("burst_detection") or {}).get("method")
        profile_left = left.get("qc_profile_id") or (left.get("burst_detection") or {}).get("qc_profile_id")
        profile_right = right.get("qc_profile_id") or (right.get("burst_detection") or {}).get("qc_profile_id")
        findings: list[str] = []
        if profile_left != profile_right:
            findings.append("qc_profile_diff")
        if method_left != method_right:
            findings.append("detection_method_diff")
        if (left.get("quality_review") or {}).get("status") != (right.get("quality_review") or {}).get("status"):
            findings.append("decision_diff")
        if abs(differences["near_zero_ratio_diff"]) > 0.10:
            findings.append("near_zero_ratio_diff")
        if abs(differences["selected_snr_diff_db"]) > 6.0:
            findings.append("snr_diff")
        return {
            "left_capture_id": left_capture_id,
            "right_capture_id": right_capture_id,
            "metadata_diff": {
                "sample_rate_hz": [cfg(left, "sample_rate_hz"), cfg(right, "sample_rate_hz")],
                "center_frequency_hz": [cfg(left, "center_frequency_hz"), cfg(right, "center_frequency_hz")],
                "effective_bandwidth_hz": [cfg(left, "effective_bandwidth_hz"), cfg(right, "effective_bandwidth_hz")],
                "signal_family": [left.get("signal_family"), right.get("signal_family")],
            },
            "qc_profile_diff": [profile_left, profile_right],
            "detection_method_diff": [method_left, method_right],
            "roi_policy_diff": [(left.get("burst_detection") or {}).get("roi_policy"), (right.get("burst_detection") or {}).get("roi_policy")],
            "decision_diff": [(left.get("quality_review") or {}).get("status"), (right.get("quality_review") or {}).get("status")],
            "differences": differences,
            "findings": findings,
        }

    def recompute_capture_record_qc(self, capture_id: str) -> dict[str, Any]:
        record = self.get_capture_record(capture_id)
        metadata_path = Path(str((record.get("artifacts") or {}).get("metadata_file", "")).strip())
        preview_metrics = {}
        if metadata_path.exists():
            try:
                with metadata_path.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    preview_metrics = metadata.get("preview_metrics", {})
            except Exception:
                pass
        iq_path = (
            str((record.get("artifacts") or {}).get("iq_file") or "").strip()
            or str((record.get("capture_config") or {}).get("output_path") or "").strip()
        )
        capture_like = {
            "iq_file": iq_path,
            "iq_dtype": (record.get("capture_config") or {}).get("sample_dtype", "complex64"),
            "sample_rate_hz": (record.get("capture_config") or {}).get("sample_rate_hz", 0.0),
            "center_frequency_hz": (record.get("capture_config") or {}).get("center_frequency_hz", 0.0),
            "duration_seconds": (record.get("capture_config") or {}).get("capture_duration_s", 0.0),
            "sample_count": (record.get("capture_config") or {}).get("sample_count", 0),
            "bandwidth_hz": (record.get("capture_config") or {}).get("effective_bandwidth_hz", 0.0),
            "modulation_hint": (record.get("transmitter") or {}).get("transmitter_class") or (record.get("transmitter") or {}).get("family") or "unknown",
            "signal_family": record.get("signal_family"),
        }
        analysis = self._analyze_imported_capture(capture_like)
        if not analysis:
            raise ValueError(f"Unable to recompute QC for capture: {capture_id}")

        quality_metrics = record.get("quality_metrics", {})
        record["signal_family"] = analysis.get("signal_family", record.get("signal_family", "unknown"))
        record["qc_profile_id"] = analysis.get("qc_profile_id", record.get("qc_profile_id", "burst_rf_v1"))
        record["qc_profile"] = analysis.get("qc_profile", record.get("qc_profile", {}))
        record["iq_file_diagnostics"] = analysis.get("iq_file_diagnostics", record.get("iq_file_diagnostics", {}))
        record["snr"] = analysis.get("snr", record.get("snr", {}))
        quality_metrics["estimated_snr_db"] = float(analysis.get("estimated_snr_db", quality_metrics.get("estimated_snr_db", 0.0) or 0.0))
        quality_metrics["temporal_snr_db"] = _safe_float(analysis.get("temporal_snr_db"))
        quality_metrics["burst_snr_db"] = _safe_float(analysis.get("burst_snr_db"))
        quality_metrics["spectral_snr_db"] = _safe_float(analysis.get("spectral_snr_db"))
        quality_metrics["selected_snr_db"] = _safe_float(analysis.get("selected_snr_db"))
        quality_metrics["selected_snr_method"] = analysis.get("selected_snr_method")
        quality_metrics["channel_presence_ratio"] = _safe_float(analysis.get("channel_presence_ratio"))
        quality_metrics["noise_floor_db"] = _safe_float(analysis.get("noise_floor_db"))
        quality_metrics["peak_power_db"] = _safe_float(analysis.get("peak_power_db"))
        quality_metrics["average_power_db"] = _safe_float(analysis.get("average_power_db"))
        quality_metrics["occupied_bandwidth_hz"] = _safe_float(analysis.get("occupied_bandwidth_hz"))
        quality_metrics["peak_frequency_hz"] = _safe_float(analysis.get("peak_frequency_hz"))
        quality_metrics["frequency_offset_hz"] = float(analysis.get("frequency_offset_hz", quality_metrics.get("frequency_offset_hz", 0.0) or 0.0))
        quality_metrics["frequency_offset_ratio_of_capture_band"] = _safe_float(analysis.get("frequency_offset_ratio_of_capture_band"))
        quality_metrics["signal_within_capture_band"] = bool(analysis.get("signal_within_capture_band", True))
        quality_metrics["capture_band_edge_margin_hz"] = _safe_float(analysis.get("capture_band_edge_margin_hz"))
        quality_metrics["clipping_pct"] = float(analysis.get("clipping_pct", quality_metrics.get("clipping_pct", 0.0) or 0.0))
        quality_metrics["silence_pct"] = float(analysis.get("silence_pct", quality_metrics.get("silence_pct", 0.0) or 0.0))
        quality_metrics["burst_duration_ms"] = float(analysis.get("burst_duration_ms", quality_metrics.get("burst_duration_ms", 0.0) or 0.0))

        # Add live preview offset
        live_peak_freq = preview_metrics.get("live_preview_peak_frequency_hz")
        center_freq = (record.get("capture_config") or {}).get("center_frequency_hz", 0.0)
        if live_peak_freq is not None and center_freq:
            live_offset_hz = live_peak_freq - center_freq
            quality_metrics["live_offset_hz"] = live_offset_hz

        burst_detection = record.get("burst_detection", {})
        burst_detection["method"] = analysis.get("method", burst_detection.get("method", "manual"))
        burst_detection["qc_profile_id"] = analysis.get("qc_profile_id")
        burst_detection["roi_policy"] = analysis.get("roi_policy")
        burst_detection["energy_threshold_db"] = _safe_float(analysis.get("energy_threshold_db"))
        burst_detection["burst_count"] = int(analysis.get("burst_count", burst_detection.get("burst_count", 0) or 0))
        burst_detection["burst_start_sample"] = int(analysis.get("burst_start_sample", burst_detection.get("burst_start_sample", 0) or 0))
        burst_detection["burst_end_sample"] = int(analysis.get("burst_end_sample", burst_detection.get("burst_end_sample", 0) or 0))
        burst_detection["regions_of_interest"] = list(analysis.get("regions_of_interest", burst_detection.get("regions_of_interest", [])))
        burst_detection["max_burst_duration_ms"] = float(
            analysis.get("burst_duration_ms", burst_detection.get("max_burst_duration_ms", quality_metrics.get("burst_duration_ms", 0.0)) or 0.0)
        ) or burst_detection.get("max_burst_duration_ms")

        record["quality_metrics"] = quality_metrics
        record["burst_detection"] = burst_detection
        quality_review = record.get("quality_review", {})
        quality_metrics["signal_family"] = record.get("signal_family", "unknown")
        quality_metrics["qc_profile_id"] = record.get("qc_profile_id")
        quality_metrics["effective_bandwidth_hz"] = (record.get("capture_config") or {}).get("effective_bandwidth_hz", 0.0)
        transmitter = record.get("transmitter", {}) if isinstance(record.get("transmitter"), dict) else {}
        capture_config = record.get("capture_config", {}) if isinstance(record.get("capture_config"), dict) else {}
        scenario = record.get("scenario", {}) if isinstance(record.get("scenario"), dict) else {}
        artifacts = record.get("artifacts", {}) if isinstance(record.get("artifacts"), dict) else {}
        qc_policy = self._qc_policy(
            {
                "qc_policy_profile": quality_review.get("qc_policy_profile", "scientific"),
                "qc_thresholds": quality_review.get("qc_thresholds", {}),
            }
        )
        label_status = quality_review.get("label_status") or self._label_status({}, transmitter)
        metadata_check = self._metadata_check(capture_config, transmitter, scenario, artifacts)
        evaluated = self._evaluate_quality(
            quality_metrics,
            None,
            qc_policy,
            label_status,
            metadata_check,
            str(quality_review.get("manual_override_reason", "") or ""),
        )
        quality_review["automatic_status"] = evaluated["status"]
        quality_review["status"] = evaluated["status"]
        quality_review["capture_quality"] = evaluated["capture_quality"]
        quality_review["label_status"] = label_status
        quality_review["review_status"] = evaluated["review_status"]
        quality_review["training_readiness"] = evaluated["training_readiness"]
        quality_review["qc_policy_profile"] = evaluated["qc_policy_profile"]
        quality_review["qc_thresholds"] = qc_policy
        quality_review["metadata_check"] = metadata_check
        quality_review["reasons"] = evaluated["reasons"]
        quality_review["quality_flags"] = evaluated["flags"]
        quality_review["qc_profile_id"] = evaluated["qc_profile_id"]
        quality_review["recomputed_at_utc"] = _utc_now()
        quality_review["updated_at_utc"] = _utc_now()
        record["quality_review"] = quality_review

        self._save_record(record)
        return record

    def apply_band_profile_to_capture(self, capture_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        path = self._capture_path(capture_id)
        if not path.exists():
            raise ValueError(f"Capture not found: {capture_id}")
        record = self._load_record(path)
        capture_config = record.get("capture_config", {}) if isinstance(record.get("capture_config"), dict) else {}
        quality_metrics = record.get("quality_metrics", {}) if isinstance(record.get("quality_metrics"), dict) else {}
        center = _safe_float(capture_config.get("center_frequency_hz"))
        bandwidth = _safe_float(quality_metrics.get("occupied_bandwidth_hz")) or _safe_float(capture_config.get("effective_bandwidth_hz"))
        if not center or not bandwidth:
            raise ValueError("Capture needs center_frequency_hz and bandwidth/occupied_bandwidth_hz to resolve a band profile")

        resolved = resolve_band_profile(center_frequency_hz=center, bandwidth_hz=bandwidth)
        defaults = resolved.get("defaults") if isinstance(resolved.get("defaults"), dict) else {}
        if not defaults:
            raise ValueError("No band-profile defaults were produced")

        transmitter = record.get("transmitter", {}) if isinstance(record.get("transmitter"), dict) else {}
        overwrite = bool(payload.get("overwrite_existing", False))
        unknown_values = {"", "unknown", "tx_unknown", "unlabeled_transmitter", "rsu_unlabeled", "profile_pending", "band_profile_pending"}

        def should_set(value: Any) -> bool:
            return overwrite or str(value or "").strip().lower() in unknown_values

        for field in ("transmitter_label", "transmitter_class", "transmitter_id", "family", "signal_type", "modulation_class", "protocol_family", "band_label", "profile_key"):
            if should_set(transmitter.get(field)):
                transmitter[field] = defaults.get(field) or transmitter.get(field)

        confirm = bool(payload.get("confirm_as_strong_label", False))
        transmitter["ground_truth_confidence"] = "operator_confirmed" if confirm else defaults.get("ground_truth_confidence", "weak_from_band_profile")
        record["transmitter"] = transmitter
        if defaults.get("family"):
            record["signal_family"] = self._infer_signal_family({}, {"signal_family": defaults.get("family")})

        quality_review = record.get("quality_review", {}) if isinstance(record.get("quality_review"), dict) else {}
        quality_review["label_status"] = "strong_label" if confirm else defaults.get("label_status", "weak_label")
        quality_review["review_status"] = "accepted" if confirm and quality_review.get("capture_quality") == "valid" else "needs_review"
        quality_review["training_readiness"] = "ready_for_training" if confirm and quality_review.get("capture_quality") == "valid" else "candidate"
        quality_review["band_profile_resolution"] = resolved
        quality_review["updated_at_utc"] = _utc_now()
        record["quality_review"] = quality_review
        scenario = record.get("scenario", {}) if isinstance(record.get("scenario"), dict) else {}
        note = f"Band-profile defaults applied from {defaults.get('profile_key') or 'band_profiles.json'}."
        if note not in str(scenario.get("notes", "")):
            scenario["notes"] = (str(scenario.get("notes", "") or "").strip() + "\n" + note).strip()
        record["scenario"] = scenario

        self._save_record(record)
        return record

    def import_modulated_capture(self, capture: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        defaults = defaults or {}
        center_frequency_hz = float(capture.get("center_frequency_hz", 0.0))
        sample_rate_hz = float(capture.get("sample_rate_hz", 0.0))
        bandwidth_hz = float(capture.get("bandwidth_hz", sample_rate_hz))
        signal_family = self._infer_signal_family(capture, defaults)
        capture_for_analysis = {**capture, "signal_family": signal_family}
        analysis = self._analyze_imported_capture(capture_for_analysis)
        burst_duration_ms = float(
            defaults.get("burst_duration_ms", analysis.get("burst_duration_ms", float(capture.get("duration_seconds", 0.0)) * 1000.0))
        )
        payload = {
            "capture_id": capture.get("id") or f"imported-{uuid4().hex[:12]}",
            "capture_mode": "guided_capture",
            "session_id": defaults.get("session_id", "session_unassigned"),
            "dataset_split": defaults.get("dataset_split", "train"),
            "signal_family": analysis.get("signal_family", signal_family),
            "qc_profile_id": analysis.get("qc_profile_id"),
            "qc_profile": analysis.get("qc_profile", {}),
            "iq_file_diagnostics": analysis.get("iq_file_diagnostics", {}),
            "snr": analysis.get("snr", {}),
            "canonicalization": analysis.get("canonicalization", {}),
            "capture_config": {
                "device_source": defaults.get("device_source", capture.get("source_device", "uhd")),
                "sdr_model": defaults.get("sdr_model", capture.get("driver", "uhd_gnuradio")),
                "sdr_serial": defaults.get("sdr_serial", "unknown"),
                "antenna_port": defaults.get("antenna_port", capture.get("antenna", "RX2")),
                "capture_type": defaults.get("capture_type", capture.get("capture_type", "iq_file")),
                "center_frequency_hz": center_frequency_hz,
                "sample_rate_hz": sample_rate_hz,
                "effective_bandwidth_hz": bandwidth_hz,
                "frontend_bandwidth_hz": defaults.get("frontend_bandwidth_hz", bandwidth_hz),
                "gain_mode": defaults.get("gain_mode", "manual"),
                "gain_settings": {
                    "lna_db": defaults.get("lna_db"),
                    "vga_db": defaults.get("vga_db"),
                    "if_db": defaults.get("if_db"),
                    "composite_gain_db": capture.get("gain_db"),
                },
                "ppm_correction": defaults.get("ppm_correction", 0.0),
                "lo_offset_hz": defaults.get("lo_offset_hz", 0.0),
                "capture_duration_s": capture.get("duration_seconds", 0.0),
                "sample_count": capture.get("sample_count", 0),
                "file_format": capture.get("file_extension", capture.get("capture_type", "cfile")),
                "sample_dtype": capture.get("iq_dtype", "complex64"),
                "byte_order": capture.get("byte_order", "native"),
                "channel_count": defaults.get("channel_count", 1),
                "output_path": capture.get("iq_file", ""),
            },
            "transmitter": {
                "transmitter_label": defaults.get("transmitter_label", capture.get("label", "unlabeled_transmitter")),
                "transmitter_class": defaults.get("transmitter_class", capture.get("modulation_hint", "unknown")),
                "transmitter_id": defaults.get("transmitter_id", capture.get("label", "tx_unknown")),
                "family": defaults.get("family") or defaults.get("signal_type") or "unknown",
                "signal_type": defaults.get("signal_type") or defaults.get("transmitter_class", capture.get("modulation_hint", "unknown")),
                "modulation_class": defaults.get("modulation_class", capture.get("modulation_hint", "")),
                "protocol_family": defaults.get("protocol_family", defaults.get("family", "")),
                "band_label": defaults.get("band_label", ""),
                "profile_key": defaults.get("profile_key"),
                "ground_truth_confidence": defaults.get("ground_truth_confidence", "unknown"),
            },
            "scenario": {
                "operator": defaults.get("operator", "unknown"),
                "environment": defaults.get("environment", "unspecified"),
                "distance_m": defaults.get("distance_m"),
                "line_of_sight": defaults.get("line_of_sight"),
                "indoor": defaults.get("indoor"),
                "notes": defaults.get("notes", capture.get("notes", "")),
                "session_number": defaults.get("session_number", 1),
                "timestamp_utc": capture.get("generated_at_utc", _utc_now()),
            },
            "quality_metrics": {
                "estimated_snr_db": defaults.get("estimated_snr_db", analysis.get("estimated_snr_db", 0.0)),
                "temporal_snr_db": defaults.get("temporal_snr_db", analysis.get("temporal_snr_db")),
                "burst_snr_db": defaults.get("burst_snr_db", analysis.get("burst_snr_db")),
                "spectral_snr_db": defaults.get("spectral_snr_db", analysis.get("spectral_snr_db")),
                "selected_snr_db": defaults.get("selected_snr_db", analysis.get("selected_snr_db")),
                "selected_snr_method": defaults.get("selected_snr_method", analysis.get("selected_snr_method")),
                "channel_presence_ratio": defaults.get("channel_presence_ratio", analysis.get("channel_presence_ratio")),
                "noise_floor_db": defaults.get("noise_floor_db", analysis.get("noise_floor_db")),
                "peak_power_db": defaults.get("peak_power_db", analysis.get("peak_power_db")),
                "average_power_db": defaults.get("average_power_db", analysis.get("average_power_db")),
                "occupied_bandwidth_hz": defaults.get("occupied_bandwidth_hz", analysis.get("occupied_bandwidth_hz", bandwidth_hz)),
                "peak_frequency_hz": defaults.get("peak_frequency_hz", analysis.get("peak_frequency_hz", center_frequency_hz)),
                "frequency_offset_hz": defaults.get("frequency_offset_hz", analysis.get("frequency_offset_hz", 0.0)),
                "frequency_offset_ratio_of_capture_band": defaults.get("frequency_offset_ratio_of_capture_band", analysis.get("frequency_offset_ratio_of_capture_band")),
                "signal_within_capture_band": defaults.get("signal_within_capture_band", analysis.get("signal_within_capture_band", True)),
                "capture_band_edge_margin_hz": defaults.get("capture_band_edge_margin_hz", analysis.get("capture_band_edge_margin_hz")),
                "clipping_pct": defaults.get("clipping_pct", analysis.get("clipping_pct", 0.0)),
                "sample_drop_count": defaults.get("sample_drop_count", 0),
                "buffer_overflow_count": defaults.get("buffer_overflow_count", 0),
                "silence_pct": defaults.get("silence_pct", analysis.get("silence_pct", 0.0)),
                "peak_to_average_ratio_db": defaults.get("peak_to_average_ratio_db", None),
                "kurtosis": defaults.get("kurtosis", None),
                "burst_duration_ms": burst_duration_ms,
            },
            "burst_detection": {
                "method": defaults.get("method", analysis.get("method", "manual_import")),
                "qc_profile_id": analysis.get("qc_profile_id"),
                "roi_policy": analysis.get("roi_policy"),
                "energy_threshold_db": defaults.get("energy_threshold_db", analysis.get("energy_threshold_db")),
                "pre_trigger_samples": defaults.get("pre_trigger_samples", 0),
                "post_trigger_samples": defaults.get("post_trigger_samples", 0),
                "min_burst_duration_ms": defaults.get("min_burst_duration_ms", 1.0),
                "max_burst_duration_ms": defaults.get("max_burst_duration_ms", burst_duration_ms or None),
                "burst_count": defaults.get("burst_count", analysis.get("burst_count", 1)),
                "regions_of_interest": defaults.get("regions_of_interest", analysis.get("regions_of_interest", ["whole_burst"])),
                "burst_start_sample": defaults.get("burst_start_sample", analysis.get("burst_start_sample", 0)),
                "burst_end_sample": defaults.get("burst_end_sample", analysis.get("burst_end_sample", capture.get("sample_count", 0))),
            },
            "artifacts": {
                "iq_file": capture.get("iq_file"),
                "metadata_file": capture.get("metadata_file"),
                "sha256": capture.get("sha256"),
                "source_capture_id": capture.get("id"),
            },
            "preview_metrics": {
                "live_preview_snr_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_snr_db")),
                "live_preview_noise_floor_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_noise_floor_db")),
                "live_preview_peak_level_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_peak_level_db")),
                "live_preview_peak_frequency_hz": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_peak_frequency_hz")),
            },
            "label_status": defaults.get("label_status"),
        }
        return self.create_capture_record(payload)

    def _analyze_imported_capture(self, capture: dict[str, Any]) -> dict[str, Any]:
        iq_file = Path(str(capture.get("iq_file", "")).strip())
        if not iq_file.exists():
            return {}

        sample_rate_hz = float(capture.get("sample_rate_hz", 0.0) or 0.0)
        center_frequency_hz = float(capture.get("center_frequency_hz", 0.0) or 0.0)
        capture_bandwidth_hz = float(capture.get("bandwidth_hz", sample_rate_hz) or sample_rate_hz)
        iq_dtype = str(capture.get("iq_dtype", "complex64") or "complex64")
        signal_family = self._infer_signal_family(capture)
        qc_profile = self._qc_profile_for_signal_family(signal_family)
        if sample_rate_hz <= 0.0:
            return {}

        samples = self._load_complex_samples(iq_file, iq_dtype)
        if samples.size == 0:
            return {}

        power = np.abs(samples) ** 2
        mean_power = float(np.mean(power))
        if not np.isfinite(mean_power) or mean_power <= 0.0:
            return {}

        noise_power = float(np.percentile(power, 20))
        avg_power_db = _db10(mean_power)
        noise_floor_db = _db10(noise_power)
        peak_power_db = _db10(float(np.max(power)))
        clipping_pct = float(np.mean((np.abs(samples.real) >= 0.999) | (np.abs(samples.imag) >= 0.999)) * 100.0)

        window = int(min(max(sample_rate_hz * 0.0005, 64), 4096))
        kernel = np.ones(window, dtype=np.float64) / window
        smoothed = np.convolve(power.astype(np.float64), kernel, mode="same")
        energy_threshold_power = max(noise_power * (10.0 ** (6.0 / 10.0)), 1e-20)
        mask = smoothed > energy_threshold_power
        burst_start, burst_end, burst_count = self._find_burst_bounds(mask)
        burst_detected = burst_start is not None and burst_end is not None
        if burst_start is None or burst_end is None:
            burst_start = 0
            burst_end = samples.size - 1
            burst_count = 0

        temporal_silence_pct = float(np.mean(~mask) * 100.0) if mask.size > 0 else 0.0
        burst_duration_ms = max(0.0, ((burst_end - burst_start + 1) / sample_rate_hz) * 1000.0)
        signal_slice = samples[burst_start:burst_end + 1] if burst_end >= burst_start else samples
        signal_power = float(np.mean(np.abs(signal_slice) ** 2)) if signal_slice.size else mean_power
        noise_reference = power[~mask] if np.any(~mask) else power
        reference_noise_power = float(np.mean(noise_reference)) if noise_reference.size else noise_power
        signal_excess_power = max(signal_power - reference_noise_power, 0.0)
        burst_snr_db = _db10(signal_excess_power / max(reference_noise_power, 1e-20))
        if not burst_detected or temporal_silence_pct >= 99.9:
            burst_snr_db = 0.0

        spectral_samples = samples if signal_family == "continuous_fm" else (signal_slice if signal_slice.size else samples)
        if spectral_samples.size > 262144:
            stride = int(np.ceil(spectral_samples.size / 262144))
            spectral_samples = spectral_samples[::stride]

        windowed = spectral_samples * np.hanning(spectral_samples.size)
        spectrum = np.fft.fftshift(np.fft.fft(windowed))
        psd_full = np.abs(spectrum) ** 2
        freqs_full = np.fft.fftshift(np.fft.fftfreq(spectral_samples.size, d=1.0 / sample_rate_hz))
        half_capture_band_hz = min(sample_rate_hz / 2.0, max(capture_bandwidth_hz, 0.0) / 2.0)
        if half_capture_band_hz > 0.0 and half_capture_band_hz < sample_rate_hz / 2.0:
            band_mask = np.abs(freqs_full) <= half_capture_band_hz
        else:
            band_mask = np.ones(freqs_full.shape, dtype=bool)
        freqs = freqs_full[band_mask]
        psd = psd_full[band_mask]
        if psd.size == 0:
            freqs = freqs_full
            psd = psd_full

        peak_index = int(np.argmax(psd))
        peak_offset_hz = float(freqs[peak_index])
        peak_frequency_hz = center_frequency_hz + peak_offset_hz
        spectral_noise = float(np.percentile(psd, 20))
        spectral_peak = float(psd[peak_index])
        spectral_snr_db = _db10(spectral_peak / max(spectral_noise, 1e-20))
        psd_excess = np.clip(psd - spectral_noise, 0.0, None)
        psd_excess_sum = float(np.sum(psd_excess))
        centroid_offset_hz = float(np.sum(freqs * psd_excess) / psd_excess_sum) if psd_excess_sum > 0.0 else peak_offset_hz
        if psd_excess_sum > 0.0:
            cumulative = np.cumsum(psd_excess)
            total = float(cumulative[-1])
            lower_index = int(np.searchsorted(cumulative, total * 0.005))
            upper_index = int(np.searchsorted(cumulative, total * 0.995))
            lower_index = max(0, min(lower_index, freqs.size - 1))
            upper_index = max(lower_index, min(upper_index, freqs.size - 1))
            occupied_bandwidth_hz = min(abs(float(freqs[upper_index] - freqs[lower_index])), max(capture_bandwidth_hz, 0.0))
        else:
            occupied_bandwidth_hz = 0.0
        capture_band_edge_margin_hz = float(half_capture_band_hz - abs(peak_offset_hz)) if half_capture_band_hz > 0 else 0.0
        signal_within_capture_band = bool(capture_band_edge_margin_hz >= 0.0)
        frequency_offset_ratio = float(abs(peak_offset_hz) / half_capture_band_hz) if half_capture_band_hz > 0 else 0.0
        temporal_channel_presence_ratio = float(np.mean(smoothed > energy_threshold_power)) if smoothed.size else 0.0
        channel_presence_ratio = temporal_channel_presence_ratio

        occupied_ratio_for_profile = (occupied_bandwidth_hz / capture_bandwidth_hz) if capture_bandwidth_hz > 0 else 0.0
        if (
            signal_family in {"unknown", "burst_rf"}
            and capture_bandwidth_hz >= 150_000.0
            and spectral_snr_db >= DEFAULT_THRESHOLDS["min_valid_snr_db"]
            and occupied_ratio_for_profile >= 0.70
            and temporal_silence_pct > DEFAULT_THRESHOLDS["max_silence_pct"]
        ):
            signal_family = "continuous_fm"
            qc_profile = self._qc_profile_for_signal_family(signal_family)

        if signal_family == "continuous_fm":
            channel_presence_ratio = 1.0 if spectral_snr_db >= DEFAULT_THRESHOLDS["min_doubtful_snr_db"] and signal_within_capture_band else 0.0
            analysis_method = "spectral_peak_detection"
            roi_policy = "full_capture_or_centered_channel"
            silence_pct = 0.0
            selected_snr_db = float(spectral_snr_db)
            selected_snr_method = "spectral_channel_snr"
            estimated_snr_db = selected_snr_db
            burst_count = 1
            burst_start = 0
            burst_end = samples.size - 1
            burst_duration_ms = float((samples.size / sample_rate_hz) * 1000.0)
            regions_of_interest = ["whole_capture", "centered_channel"]
        else:
            analysis_method = "auto_energy_burst" if burst_detected else "no_burst_detected"
            roi_policy = "burst_region" if burst_detected else "full_capture"
            regions_of_interest = ["transient_start", "whole_burst"] if burst_detected else ["whole_burst"]
            silence_pct = temporal_silence_pct
            selected_snr_db = float(burst_snr_db)
            selected_snr_method = "burst_temporal_snr"
            estimated_snr_db = selected_snr_db
            if not burst_detected and spectral_snr_db >= DEFAULT_THRESHOLDS["min_doubtful_snr_db"]:
                analysis_method = "spectral_peak_detection"
                roi_policy = "full_capture_or_centered_channel"
                selected_snr_db = float(spectral_snr_db)
                selected_snr_method = "spectral_fallback_snr"
                estimated_snr_db = selected_snr_db
                silence_pct = 0.0
                burst_duration_ms = float((samples.size / sample_rate_hz) * 1000.0)
                burst_count = 1
                burst_start = 0
                burst_end = samples.size - 1
                regions_of_interest = ["whole_burst"]

        diagnostics = self._iq_file_diagnostics(samples, sample_rate_hz, iq_dtype, peak_offset_hz)
        canonicalization = {
            "enabled": True,
            "estimated_signal_offset_hz": float(peak_offset_hz),
            "frequency_shift_applied_hz": float(-peak_offset_hz),
            "canonical_center_hz": 0.0,
            "canonical_sample_rate_hz": float(sample_rate_hz),
            "canonical_bandwidth_hz": float(capture_bandwidth_hz),
            "preprocessing_profile_id": "continuous_fm_centered_iq_v1" if signal_family == "continuous_fm" else "burst_rf_centered_iq_v1",
        }
        snr = {
            "temporal_snr_db": float(burst_snr_db),
            "burst_snr_db": float(burst_snr_db),
            "spectral_snr_db": float(spectral_snr_db),
            "selected_snr_db": float(selected_snr_db),
            "selected_snr_method": selected_snr_method,
            "noise_estimation_method": "percentile_psd_with_temporal_percentile",
            "signal_region_hz": [-float(half_capture_band_hz), float(half_capture_band_hz)] if half_capture_band_hz else None,
            "noise_region_hz": "outside_channel_guarded_or_psd_percentile",
        }
        return {
            "signal_family": signal_family,
            "qc_profile_id": qc_profile["qc_profile_id"],
            "qc_profile": qc_profile,
            "roi_policy": roi_policy,
            "estimated_snr_db": float(estimated_snr_db),
            "temporal_snr_db": float(burst_snr_db),
            "burst_snr_db": float(burst_snr_db),
            "selected_snr_db": float(selected_snr_db),
            "selected_snr_method": selected_snr_method,
            "snr": snr,
            "iq_file_diagnostics": diagnostics,
            "canonicalization": canonicalization,
            "channel_presence_ratio": float(channel_presence_ratio),
            "temporal_channel_presence_ratio": float(temporal_channel_presence_ratio),
            "noise_floor_db": float(noise_floor_db),
            "peak_power_db": float(peak_power_db),
            "average_power_db": float(avg_power_db),
            "spectral_snr_db": float(spectral_snr_db),
            "occupied_bandwidth_hz": abs(float(occupied_bandwidth_hz)),
            "peak_frequency_hz": float(peak_frequency_hz),
            "frequency_offset_hz": float(peak_offset_hz),
            "frequency_centroid_offset_hz": float(centroid_offset_hz),
            "frequency_offset_ratio_of_capture_band": float(frequency_offset_ratio),
            "signal_within_capture_band": signal_within_capture_band,
            "capture_band_edge_margin_hz": float(capture_band_edge_margin_hz),
            "clipping_pct": float(clipping_pct),
            "silence_pct": float(silence_pct),
            "temporal_silence_pct": float(temporal_silence_pct),
            "burst_duration_ms": float(burst_duration_ms),
            "method": analysis_method,
            "energy_threshold_db": float(_db10(energy_threshold_power)),
            "burst_count": int(burst_count),
            "burst_start_sample": int(burst_start),
            "burst_end_sample": int(burst_end),
            "regions_of_interest": regions_of_interest,
        }

    @staticmethod
    def _load_complex_samples(path: Path, iq_dtype: str) -> np.ndarray:
        normalized_dtype = str(iq_dtype or "complex64").strip().lower()
        if normalized_dtype in {"complex64", "fc32", "np.complex64"}:
            return np.fromfile(path, dtype=np.complex64)
        if normalized_dtype in {"complex128", "np.complex128"}:
            return np.fromfile(path, dtype=np.complex128).astype(np.complex64)
        if normalized_dtype in {"int16", "complex int16", "ci16"}:
            raw = np.fromfile(path, dtype=np.int16)
            if raw.size < 2:
                return np.asarray([], dtype=np.complex64)
            if raw.size % 2 == 1:
                raw = raw[:-1]
            i = raw[0::2].astype(np.float32) / 32768.0
            q = raw[1::2].astype(np.float32) / 32768.0
            return (i + 1j * q).astype(np.complex64)
        return np.fromfile(path, dtype=np.complex64)

    @staticmethod
    def _find_burst_bounds(mask: np.ndarray) -> tuple[int | None, int | None, int]:
        if mask.size == 0 or not np.any(mask):
            return None, None, 0
        indices = np.flatnonzero(mask)
        transitions = np.diff(indices)
        burst_count = int(np.sum(transitions > 1) + 1)
        return int(indices[0]), int(indices[-1]), burst_count

    def _capture_path(self, capture_id: str) -> Path:
        return self._captures_dir / f"{capture_id}.json"

    def _delete_unreferenced_artifacts(self, record: dict[str, Any], excluded_capture_id: str) -> list[str]:
        removed: list[str] = []
        candidates = [
            str((record.get("artifacts") or {}).get("iq_file") or "").strip(),
            str((record.get("artifacts") or {}).get("metadata_file") or "").strip(),
            str((record.get("capture_config") or {}).get("output_path") or "").strip(),
        ]
        unique_candidates: list[Path] = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                resolved = Path(candidate).resolve()
            except OSError:
                continue
            if resolved not in unique_candidates:
                unique_candidates.append(resolved)

        for candidate in unique_candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            if not self._is_within_workspace(candidate):
                continue
            if self._is_artifact_referenced_elsewhere(candidate, excluded_capture_id=excluded_capture_id):
                continue
            candidate.unlink()
            removed.append(str(candidate))
        return removed

    def _is_artifact_referenced_elsewhere(self, artifact_path: Path, excluded_capture_id: str) -> bool:
        artifact_text = str(artifact_path)
        for path in self._captures_dir.glob("*.json"):
            if path.stem == excluded_capture_id:
                continue
            try:
                record = self._load_record(path)
            except Exception:
                continue
            references = [
                str((record.get("artifacts") or {}).get("iq_file") or "").strip(),
                str((record.get("artifacts") or {}).get("metadata_file") or "").strip(),
                str((record.get("capture_config") or {}).get("output_path") or "").strip(),
            ]
            for reference in references:
                if not reference:
                    continue
                try:
                    if str(Path(reference).resolve()) == artifact_text:
                        return True
                except OSError:
                    continue
        return False

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            workspace = self._workspace_root.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(workspace)
            return True
        except ValueError:
            return False

    def _load_record(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save_record(self, record: dict[str, Any]) -> None:
        record["updated_at_utc"] = _utc_now()
        with self._capture_path(record["capture_id"]).open("w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)

    def _normalize_record(self, payload: dict[str, Any], capture_id: str | None = None) -> dict[str, Any]:
        capture_id = capture_id or uuid4().hex[:12]
        capture_config = deepcopy(payload.get("capture_config", {}))
        transmitter = deepcopy(payload.get("transmitter", {}))
        scenario = deepcopy(payload.get("scenario", {}))
        quality_metrics = deepcopy(payload.get("quality_metrics", {}))
        burst_detection = deepcopy(payload.get("burst_detection", {}))
        artifacts = deepcopy(payload.get("artifacts", {}))
        preview_metrics = deepcopy(payload.get("preview_metrics", {}))

        # Calculate live offset
        live_offset_hz = None
        live_peak_freq = preview_metrics.get("live_preview_peak_frequency_hz")
        center_freq = capture_config.get("center_frequency_hz", 0.0)
        if live_peak_freq is not None and center_freq:
            live_offset_hz = live_peak_freq - center_freq
        quality_metrics["live_offset_hz"] = live_offset_hz

        iq_path = artifacts.get("iq_file") or capture_config.get("output_path")
        if iq_path and not artifacts.get("sha256"):
            iq_file = Path(iq_path)
            if iq_file.exists():
                artifacts["sha256"] = _sha256_file(iq_file)

        qc_policy = self._qc_policy(payload)
        label_status = self._label_status(payload, transmitter)
        metadata_check = self._metadata_check(capture_config, transmitter, scenario, artifacts)
        quality = self._evaluate_quality(
            {
                "estimated_snr_db": float(quality_metrics.get("estimated_snr_db", 0.0) or 0.0),
                "selected_snr_db": float(quality_metrics.get("selected_snr_db", quality_metrics.get("estimated_snr_db", 0.0)) or 0.0),
                "signal_family": payload.get("signal_family", "unknown"),
                "qc_profile_id": payload.get("qc_profile_id"),
                "effective_bandwidth_hz": float(capture_config.get("effective_bandwidth_hz", 0.0) or 0.0),
                "occupied_bandwidth_hz": float(quality_metrics.get("occupied_bandwidth_hz", 0.0) or 0.0),
                "channel_presence_ratio": float(quality_metrics.get("channel_presence_ratio", 0.0) or 0.0),
                "frequency_offset_hz": float(quality_metrics.get("frequency_offset_hz", 0.0) or 0.0),
                "frequency_offset_ratio_of_capture_band": float(quality_metrics.get("frequency_offset_ratio_of_capture_band", 0.0) or 0.0),
                "signal_within_capture_band": bool(quality_metrics.get("signal_within_capture_band", True)),
                "clipping_pct": float(quality_metrics.get("clipping_pct", 0.0) or 0.0),
                "sample_drop_count": int(quality_metrics.get("sample_drop_count", 0) or 0),
                "buffer_overflow_count": int(quality_metrics.get("buffer_overflow_count", 0) or 0),
                "silence_pct": float(quality_metrics.get("silence_pct", 0.0) or 0.0),
                "burst_duration_ms": float(quality_metrics.get("burst_duration_ms", 0.0) or 0.0),
                "live_offset_hz": live_offset_hz,
            },
            payload.get("operator_decision"),
            qc_policy,
            label_status,
            metadata_check,
            str(payload.get("manual_override_reason", "") or ""),
        )

        timestamp_utc = scenario.get("timestamp_utc") or _utc_now()
        dataset_split = self._normalize_split(payload.get("dataset_split", "train"))
        dataset_destination = str(capture_config.get("dataset_destination", "")).strip()
        if not dataset_destination:
            dataset_destination = f"fingerprinting/{dataset_split}"
        return {
            "capture_id": capture_id,
            "capture_mode": payload.get("capture_mode", "guided_capture"),
            "session_id": payload.get("session_id", scenario.get("session_id", "session_unassigned")),
            "dataset_split": dataset_split,
            "created_at_utc": payload.get("created_at_utc", _utc_now()),
            "capture_config": {
                "device_source": capture_config.get("device_source", "uhd"),
                "sdr_model": capture_config.get("sdr_model", "unknown"),
                "sdr_serial": capture_config.get("sdr_serial", "unknown"),
                "gain_stage": capture_config.get("gain_stage", "manual"),
                "antenna_port": capture_config.get("antenna_port", "RX2"),
                "capture_type": capture_config.get("capture_type", "iq_file"),
                "center_frequency_hz": capture_config.get("center_frequency_hz", 0.0),
                "sample_rate_hz": capture_config.get("sample_rate_hz", 0.0),
                "effective_bandwidth_hz": capture_config.get("effective_bandwidth_hz", 0.0),
                "frontend_bandwidth_hz": capture_config.get("frontend_bandwidth_hz"),
                "gain_mode": capture_config.get("gain_mode", "manual"),
                "gain_settings": capture_config.get("gain_settings", {}),
                "ppm_correction": capture_config.get("ppm_correction", 0.0),
                "lo_offset_hz": capture_config.get("lo_offset_hz", 0.0),
                "capture_duration_s": capture_config.get("capture_duration_s", 0.0),
                "sample_count": capture_config.get("sample_count", 0),
                "file_format": capture_config.get("file_format", "cfile"),
                "sample_dtype": capture_config.get("sample_dtype", "complex64"),
                "byte_order": capture_config.get("byte_order", "native"),
                "channel_count": capture_config.get("channel_count", 1),
                "output_path": capture_config.get("output_path", ""),
                "dataset_destination": dataset_destination,
            },
            "transmitter": {
                "transmitter_label": transmitter.get("transmitter_label", ""),
                "transmitter_class": transmitter.get("transmitter_class", ""),
                "transmitter_id": transmitter.get("transmitter_id", ""),
                "family": transmitter.get("family", ""),
                "signal_type": transmitter.get("signal_type", transmitter.get("transmitter_class", "")),
                "modulation_class": transmitter.get("modulation_class", ""),
                "protocol_family": transmitter.get("protocol_family", ""),
                "band_label": transmitter.get("band_label", ""),
                "profile_key": transmitter.get("profile_key"),
                "ground_truth_confidence": transmitter.get("ground_truth_confidence", "unknown"),
            },
            "scenario": {
                "operator": scenario.get("operator", "unknown"),
                "environment": scenario.get("environment", "unspecified"),
                "distance_m": scenario.get("distance_m"),
                "line_of_sight": scenario.get("line_of_sight"),
                "indoor": scenario.get("indoor"),
                "notes": scenario.get("notes", ""),
                "session_number": scenario.get("session_number", 1),
                "timestamp_utc": timestamp_utc,
            },
            "quality_metrics": quality_metrics,
            "burst_detection": {
                "method": burst_detection.get("method", "manual"),
                "energy_threshold_db": burst_detection.get("energy_threshold_db"),
                "pre_trigger_samples": burst_detection.get("pre_trigger_samples", 0),
                "post_trigger_samples": burst_detection.get("post_trigger_samples", 0),
                "min_burst_duration_ms": burst_detection.get("min_burst_duration_ms", 1.0),
                "max_burst_duration_ms": burst_detection.get("max_burst_duration_ms"),
                "burst_count": burst_detection.get("burst_count", 1),
                "regions_of_interest": burst_detection.get("regions_of_interest", []),
                "burst_start_sample": burst_detection.get("burst_start_sample"),
                "burst_end_sample": burst_detection.get("burst_end_sample"),
            },
            "quality_review": {
                "status": quality["status"],
                "capture_quality": quality["capture_quality"],
                "label_status": label_status,
                "review_status": quality["review_status"],
                "training_readiness": quality["training_readiness"],
                "qc_policy_profile": quality["qc_policy_profile"],
                "qc_thresholds": qc_policy,
                "metadata_check": metadata_check,
                "manual_override_reason": payload.get("manual_override_reason", ""),
                "reasons": quality["reasons"],
                "quality_flags": quality["flags"],
                "operator_decision": payload.get("operator_decision"),
                "review_notes": payload.get("review_notes", ""),
                "export_windows": payload.get("export_windows", []),
                "updated_at_utc": _utc_now(),
            },
            "artifacts": artifacts,
            "preview_metrics": {
                "live_preview_snr_db": _safe_float(preview_metrics.get("live_preview_snr_db")),
                "live_preview_noise_floor_db": _safe_float(preview_metrics.get("live_preview_noise_floor_db")),
                "live_preview_peak_level_db": _safe_float(preview_metrics.get("live_preview_peak_level_db")),
                "live_preview_peak_frequency_hz": _safe_float(preview_metrics.get("live_preview_peak_frequency_hz")),
            },
        }

    @staticmethod
    def _normalize_split(value: Any) -> str:
        normalized = str(value or "train").strip().lower()
        if normalized not in {"train", "val", "predict"}:
            raise ValueError("dataset_split must be one of: train, val, predict")
        return normalized

    def _qc_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested = str(payload.get("qc_policy_profile") or "scientific").strip().lower().replace(" ", "_").replace("-", "_")
        profile = deepcopy(QC_POLICY_PROFILES.get(requested, QC_POLICY_PROFILES["scientific"]))
        overrides = payload.get("qc_thresholds") if isinstance(payload.get("qc_thresholds"), dict) else {}
        for key in list(profile.keys()):
            if key in overrides and overrides[key] not in (None, ""):
                profile[key] = overrides[key]
        profile["profile"] = requested if requested in QC_POLICY_PROFILES else "scientific"
        return profile

    def _label_status(self, payload: dict[str, Any], transmitter: dict[str, Any]) -> str:
        explicit = str(payload.get("label_status") or "").strip().lower()
        if explicit in {"unlabeled", "weak_label", "strong_label"}:
            return explicit
        label = str(transmitter.get("transmitter_id") or transmitter.get("transmitter_label") or "").strip().lower()
        confidence = str(transmitter.get("ground_truth_confidence") or "").strip().lower()
        if not label or label in {"unknown", "tx_unknown", "unlabeled_transmitter", "rsu_unlabeled"}:
            return "unlabeled"
        if confidence in {"confirmed", "strong", "operator_confirmed", "manual_confirmed"}:
            return "strong_label"
        return "weak_label"

    def _metadata_check(self, capture_config: dict[str, Any], transmitter: dict[str, Any], scenario: dict[str, Any], artifacts: dict[str, Any]) -> dict[str, Any]:
        required = {
            "center_frequency_hz": capture_config.get("center_frequency_hz"),
            "sample_rate_hz": capture_config.get("sample_rate_hz"),
            "capture_duration_s": capture_config.get("capture_duration_s"),
            "raw_iq_path": artifacts.get("iq_file") or capture_config.get("output_path"),
            "session_or_timestamp": scenario.get("timestamp_utc") or scenario.get("session_id"),
        }
        missing = [key for key, value in required.items() if value in (None, "", 0)]
        return {"valid": not missing, "missing": missing}

    def _evaluate_quality(
        self,
        metrics: dict[str, Any],
        operator_decision: str | None,
        qc_policy: dict[str, Any] | None = None,
        label_status: str = "unlabeled",
        metadata_check: dict[str, Any] | None = None,
        manual_override_reason: str = "",
    ) -> dict[str, Any]:
        reasons: list[str] = []
        flags: list[str] = []
        qc_policy = qc_policy or deepcopy(QC_POLICY_PROFILES["scientific"])
        metadata_check = metadata_check or {"valid": True, "missing": []}
        policy_profile = str(qc_policy.get("profile", "scientific"))

        signal_family = str(metrics.get("signal_family") or "burst_rf").strip().lower()
        qc_profile_id = str(metrics.get("qc_profile_id") or ("continuous_fm_v1" if signal_family == "continuous_fm" else "burst_rf_v1"))
        snr = float(metrics.get("selected_snr_db", metrics.get("estimated_snr_db", 0.0)) or 0.0)
        clipping_pct = float(metrics.get("clipping_pct", 0.0) or 0.0)
        silence_pct = float(metrics.get("silence_pct", 0.0) or 0.0)
        sample_drop_count = int(metrics.get("sample_drop_count", 0) or 0)
        buffer_overflow_count = int(metrics.get("buffer_overflow_count", 0) or 0)
        burst_duration_ms = float(metrics.get("burst_duration_ms", 0.0) or 0.0)
        occupied_bw = float(metrics.get("occupied_bandwidth_hz", 0.0) or 0.0)
        effective_bw = float(metrics.get("effective_bandwidth_hz", 0.0) or 0.0)
        occupied_ratio = occupied_bw / effective_bw if effective_bw > 0 else 0.0
        frequency_offset_hz = abs(float(metrics.get("frequency_offset_hz", 0.0) or 0.0))

        min_snr = float(qc_policy.get("min_snr_db", DEFAULT_THRESHOLDS["min_valid_snr_db"]) or 0.0)
        max_clipping = float(qc_policy.get("max_clipping_percentage", DEFAULT_THRESHOLDS["max_valid_clipping_pct"]) or 0.0)
        min_occupied = float(qc_policy.get("min_occupied_bandwidth_hz", 0.0) or 0.0)
        max_occupied = float(qc_policy.get("max_occupied_bandwidth_hz", 0.0) or 0.0)
        max_offset = float(qc_policy.get("max_frequency_offset_hz", DEFAULT_THRESHOLDS["max_valid_frequency_offset_hz"]) or 0.0)
        min_duration = float(qc_policy.get("min_signal_duration_ms", DEFAULT_THRESHOLDS["min_valid_burst_duration_ms"]) or 0.0)
        max_silence = float(qc_policy.get("max_silence_percentage", DEFAULT_THRESHOLDS["max_silence_pct"]) or 0.0)

        if snr < DEFAULT_THRESHOLDS["min_doubtful_snr_db"]:
            reasons.append("insufficient_snr")
            flags.append("snr_low")
        elif snr < DEFAULT_THRESHOLDS["min_valid_snr_db"]:
            reasons.append("borderline_snr")
            flags.append("snr_borderline")
        if snr < min_snr:
            reasons.append("profile_min_snr_not_met")
            flags.append("profile_snr_warning")

        if clipping_pct > DEFAULT_THRESHOLDS["max_doubtful_clipping_pct"]:
            reasons.append("adc_clipping")
            flags.append("clipping_high")
        elif clipping_pct > DEFAULT_THRESHOLDS["max_valid_clipping_pct"]:
            reasons.append("moderate_clipping")
            flags.append("clipping_present")
        if clipping_pct > max_clipping:
            reasons.append("profile_clipping_limit_exceeded")
            flags.append("profile_clipping_warning")

        signal_within_capture_band = bool(metrics.get("signal_within_capture_band", True))
        offset_ratio = float(metrics.get("frequency_offset_ratio_of_capture_band", 0.0) or 0.0)
        capture_band_edge_margin_hz = float(metrics.get("capture_band_edge_margin_hz", 0.0) or 0.0)
        analysis_method = str(metrics.get("method", metrics.get("analysis_method", "")) or "").strip().lower()
        marker_confined_burst = (
            qc_profile_id == "burst_rf_v1"
            and signal_within_capture_band
            and capture_band_edge_margin_hz >= 50_000.0
        )

        if not signal_within_capture_band:
            reasons.append("signal_outside_capture_band")
            flags.append("offset_outside_capture_band")
        elif qc_profile_id == "continuous_fm_v1":
            if offset_ratio >= 0.90:
                reasons.append("signal_near_capture_edge")
                flags.append("offset_near_capture_edge")
        elif qc_profile_id == "burst_rf_v1":
            if offset_ratio > 0.65:
                flags.append("peak_not_ideally_centered")
            if occupied_ratio >= 0.98:
                flags.append("occupied_bandwidth_near_capture_limit")
            elif occupied_ratio > 0.90:
                flags.append("occupied_bandwidth_high")
            if 0.0 < capture_band_edge_margin_hz < 50_000.0:
                flags.append("low_margin_to_nearest_edge")
                if capture_band_edge_margin_hz < 20_000.0:
                    reasons.append("extremely_low_margin_to_nearest_edge")
        else:
            if offset_ratio >= 0.90:
                reasons.append("signal_near_capture_edge")
                flags.append("offset_near_capture_edge")

        if signal_family == "continuous_fm":
            channel_presence_ratio = float(metrics.get("channel_presence_ratio", 0.0) or 0.0)
            if channel_presence_ratio < 0.50:
                reasons.append("channel_not_present")
                flags.append("channel_presence_low")
            elif occupied_ratio > 0.95:
                reasons.append("bandwidth_too_tight")
                flags.append("occupied_bandwidth_near_capture_limit")
            elif occupied_ratio > 0.85:
                reasons.append("bandwidth_tight")
                flags.append("occupied_bandwidth_high")
        else:
            if silence_pct > DEFAULT_THRESHOLDS["max_silence_pct"]:
                reasons.append("absence_of_activity")
                flags.append("silence_high")
            if burst_duration_ms and burst_duration_ms < DEFAULT_THRESHOLDS["min_valid_burst_duration_ms"]:
                reasons.append("duration_insufficient")
                flags.append("burst_too_short")
        if silence_pct > max_silence:
            reasons.append("profile_silence_limit_exceeded")
            flags.append("profile_silence_warning")
        if burst_duration_ms < min_duration:
            reasons.append("profile_signal_duration_too_short")
            flags.append("profile_duration_warning")
        if min_occupied > 0 and occupied_bw < min_occupied:
            reasons.append("occupied_bandwidth_too_small")
            flags.append("occupied_bandwidth_low")
        if max_occupied > 0 and occupied_bw > max_occupied:
            reasons.append("occupied_bandwidth_too_large")
            flags.append("occupied_bandwidth_high")
        if max_offset > 0 and frequency_offset_hz > max_offset:
            flags.append("profile_frequency_offset_warning")
            if not marker_confined_burst:
                reasons.append("profile_frequency_offset_limit_exceeded")
        if bool(qc_policy.get("require_metadata")) and not metadata_check.get("valid", False):
            reasons.append("metadata_incomplete")
            flags.append("metadata_missing")
        if bool(qc_policy.get("require_label")) and label_status != "strong_label":
            reasons.append("strong_label_required")
            flags.append("label_not_strong")
        if label_status == "weak_label" and not bool(qc_policy.get("allow_weak_label")):
            reasons.append("weak_label_not_allowed")
            flags.append("weak_label")
        if label_status == "unlabeled" and not bool(qc_policy.get("allow_unlabeled")):
            reasons.append("unlabeled_not_allowed")
            flags.append("unlabeled")

        if sample_drop_count > 0:
            reasons.append("sample_drops_detected")
            flags.append("sample_drop")
        if buffer_overflow_count > 0:
            reasons.append("buffer_overflow")
            flags.append("buffer_overflow")

        # Check for pre-post QC mismatch
        live_offset_hz = metrics.get("live_offset_hz")
        offline_offset_hz = metrics.get("frequency_offset_hz", 0.0)
        effective_bandwidth_hz = metrics.get("effective_bandwidth_hz", 0.0)
        if live_offset_hz is not None and effective_bandwidth_hz > 0:
            offset_delta_hz = abs(live_offset_hz - offline_offset_hz)
            mismatch_threshold_hz = 0.15 * effective_bandwidth_hz
            if offset_delta_hz > mismatch_threshold_hz:
                flags.append("pre_post_qc_mismatch")
                metrics["pre_post_offset_delta_hz"] = offset_delta_hz

        status = "valid"
        reject_reasons = {"insufficient_snr", "adc_clipping", "signal_outside_capture_band", "sample_drops_detected", "buffer_overflow"}
        if signal_family == "continuous_fm":
            reject_reasons.add("channel_not_present")
        else:
            reject_reasons.update({"absence_of_activity", "duration_insufficient"})
        if reasons:
            status = "rejected" if any(item in reasons for item in reject_reasons) else "doubtful"

        if qc_profile_id == "burst_rf_v1" and analysis_method == "spectral_peak_detection":
            if snr >= 15.0 and clipping_pct <= 1.0 and not any(item in reasons for item in reject_reasons):
                status = "valid"

        if operator_decision in {"valid", "doubtful", "rejected"}:
            status = operator_decision

        severe_reasons = {"adc_clipping", "signal_outside_capture_band", "sample_drops_detected", "buffer_overflow", "absence_of_activity"}
        advisory_flags = {
            "occupied_bandwidth_high",
            "occupied_bandwidth_near_capture_limit",
            "peak_not_ideally_centered",
            "pre_post_qc_mismatch",
            "profile_frequency_offset_warning",
        }
        blocking_flags = [flag for flag in flags if flag not in advisory_flags]
        capture_quality = "valid"
        if any(item in reasons for item in severe_reasons) or status == "rejected":
            capture_quality = "invalid"
        elif policy_profile in {"exploratory", "training_draft"} and reasons:
            capture_quality = "warning"
        elif status == "doubtful":
            capture_quality = "doubtful"
        elif reasons or blocking_flags:
            capture_quality = "warning"

        review_status = "needs_review"
        training_readiness = "not_ready"
        if policy_profile == "manual_override":
            if not manual_override_reason.strip():
                reasons.append("manual_override_reason_required")
                flags.append("manual_override_reason_missing")
            review_status = "manual_override"
            training_readiness = "debug_only"
            if status == "valid":
                status = "doubtful"
        elif policy_profile == "exploratory":
            review_status = "needs_review"
            training_readiness = "not_ready"
        elif policy_profile == "training_draft":
            review_status = "needs_review"
            training_readiness = "candidate" if capture_quality in {"valid", "warning"} and label_status != "unlabeled" else "not_ready"
        else:
            if capture_quality == "valid" and label_status == "strong_label" and metadata_check.get("valid", False):
                review_status = "accepted"
                training_readiness = "ready_for_training"

        return {
            "status": status,
            "capture_quality": capture_quality,
            "review_status": review_status,
            "training_readiness": training_readiness,
            "qc_policy_profile": policy_profile,
            "reasons": sorted(set(reasons)),
            "flags": sorted(set(flags)),
            "qc_profile_id": qc_profile_id,
        }

