from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SigMFExporter:
    generator_version = "rf_experiment_lab_sigmf_v1"

    def preview(self, iq_path: str, metadata_path: str, output_dir: str | Path | None = None) -> dict[str, Any]:
        source_data = Path(iq_path)
        source_meta = Path(metadata_path)
        metadata = self._load_json_required(source_meta)
        normalized = self._normalize_metadata(metadata, source_meta)
        validation = self.validate_metadata(normalized)
        sha256 = self._sha256_file(source_data) if source_data.exists() else None
        stem = source_data.stem
        target_dir = Path(output_dir) if output_dir else source_data.parent
        sigmf_meta = self._build_sigmf_metadata(normalized, source_data, source_meta, sha256)
        return {
            "preview_only": True,
            "would_write": {
                "sigmf_data": str(target_dir / f"{stem}.sigmf-data"),
                "sigmf_meta": str(target_dir / f"{stem}.sigmf-meta"),
            },
            "source": {
                "iq_path": str(source_data),
                "metadata_path": str(source_meta),
                "iq_exists": source_data.exists(),
                "metadata_exists": source_meta.exists(),
                "sha256_raw_iq": sha256,
            },
            "validation": validation,
            "sigmf_meta": sigmf_meta,
        }

    def export(self, iq_path: str, metadata_path: str, output_dir: str | Path) -> dict[str, Any]:
        preview = self.preview(iq_path, metadata_path, output_dir)
        if not preview["source"]["iq_exists"]:
            raise FileNotFoundError(f"IQ data file not found: {iq_path}")
        if not preview["validation"]["valid"]:
            raise ValueError("SigMF metadata validation failed: " + ", ".join(preview["validation"]["missing"]))
        source_data = Path(iq_path)
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        sigmf_data = target_dir / f"{source_data.stem}.sigmf-data"
        sigmf_meta = target_dir / f"{source_data.stem}.sigmf-meta"
        shutil.copy2(source_data, sigmf_data)
        sigmf_meta.write_text(json.dumps(preview["sigmf_meta"], indent=2), encoding="utf-8")
        return {
            "preview_only": False,
            "sigmf_data": str(sigmf_data),
            "sigmf_meta": str(sigmf_meta),
            "sha256_raw_iq": preview["source"]["sha256_raw_iq"],
            "original_files_unchanged": True,
            "validation": preview["validation"],
        }

    def export_metadata_pair(self, cfile_path: str, metadata_path: str, output_dir: str | Path) -> dict[str, Any]:
        return self.export(cfile_path, metadata_path, output_dir)

    def validate_metadata(self, normalized: dict[str, Any]) -> dict[str, Any]:
        required = ["sample_rate_hz", "center_frequency_hz", "datatype", "duration_seconds_or_num_samples"]
        missing = [field for field in required if normalized.get(field) in (None, "")]
        optional_available = [
            field for field in ("gain_db", "antenna", "sdr_device") if normalized.get(field) not in (None, "")
        ]
        return {
            "valid": not missing,
            "missing": missing,
            "optional_available": optional_available,
            "required_fields": required,
        }

    def _build_sigmf_metadata(
        self,
        normalized: dict[str, Any],
        source_data: Path,
        source_meta: Path,
        sha256_raw_iq: str | None,
    ) -> dict[str, Any]:
        annotations = self._annotations_from_metadata(normalized)
        return {
            "global": {
                "core:datatype": normalized.get("datatype"),
                "core:sample_rate": normalized.get("sample_rate_hz"),
                "core:hw": normalized.get("sdr_device"),
                "core:author": normalized.get("operator"),
                "core:description": normalized.get("description"),
                "core:version": "1.0.0",
                "rf_experiment_lab:generator": self.generator_version,
                "rf_experiment_lab:source_iq_file": str(source_data),
                "rf_experiment_lab:source_metadata_file": str(source_meta),
                "rf_experiment_lab:sha256_raw_iq": sha256_raw_iq,
                "rf_experiment_lab:gain_db": normalized.get("gain_db"),
                "rf_experiment_lab:antenna": normalized.get("antenna"),
                "rf_experiment_lab:duration_seconds": normalized.get("duration_seconds"),
                "rf_experiment_lab:num_samples": normalized.get("num_samples"),
                "rf_experiment_lab:created_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            "captures": [
                {
                    "core:sample_start": 0,
                    "core:frequency": normalized.get("center_frequency_hz"),
                    "core:datetime": normalized.get("timestamp_utc"),
                }
            ],
            "annotations": annotations,
        }

    def _annotations_from_metadata(self, normalized: dict[str, Any]) -> list[dict[str, Any]]:
        labels = normalized.get("labels", {})
        if not labels:
            return []
        return [
            {
                "core:sample_start": 0,
                "core:sample_count": normalized.get("num_samples"),
                "core:label": labels,
            }
        ]

    def _normalize_metadata(self, metadata: dict[str, Any], metadata_path: Path) -> dict[str, Any]:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        transmitter = metadata.get("transmitter", {}) if isinstance(metadata.get("transmitter"), dict) else {}
        scenario = metadata.get("scenario", {}) if isinstance(metadata.get("scenario"), dict) else {}
        quality = metadata.get("quality_metrics", {}) if isinstance(metadata.get("quality_metrics"), dict) else {}
        gain_settings = config.get("gain_settings", {}) if isinstance(config.get("gain_settings"), dict) else {}
        duration = metadata.get("duration_seconds") or config.get("capture_duration_s")
        num_samples = metadata.get("num_samples") or metadata.get("sample_count") or config.get("sample_count")
        datatype = metadata.get("datatype") or config.get("sample_dtype") or self._datatype_from_format(config.get("file_format"))
        return {
            "capture_id": metadata.get("capture_id") or metadata_path.stem,
            "sample_rate_hz": metadata.get("sample_rate_hz") or config.get("sample_rate_hz"),
            "center_frequency_hz": metadata.get("center_frequency_hz") or config.get("center_frequency_hz"),
            "datatype": datatype,
            "duration_seconds": duration,
            "num_samples": num_samples,
            "duration_seconds_or_num_samples": duration if duration is not None else num_samples,
            "gain_db": metadata.get("gain_db") or gain_settings.get("composite_gain_db") or gain_settings.get("gain_db"),
            "antenna": metadata.get("antenna") or config.get("antenna_port"),
            "sdr_device": metadata.get("sdr_device") or config.get("sdr_model") or config.get("device_source"),
            "operator": metadata.get("operator") or scenario.get("operator"),
            "timestamp_utc": metadata.get("timestamp_utc") or scenario.get("timestamp_utc"),
            "description": metadata.get("scenario_label") or scenario.get("environment") or "RF Experiment Lab SigMF export",
            "labels": {
                key: value
                for key, value in {
                    "transmitter_id": transmitter.get("transmitter_id") or metadata.get("transmitter_id"),
                    "transmitter_class": transmitter.get("transmitter_class") or metadata.get("signal_family"),
                    "technology": transmitter.get("family") or metadata.get("technology"),
                    "dataset_split": metadata.get("dataset_split"),
                }.items()
                if value not in (None, "")
            },
            "quality": quality,
        }

    def _datatype_from_format(self, file_format: Any) -> str | None:
        if not file_format:
            return None
        normalized = str(file_format).lower()
        if normalized in {"cfile", ".cfile", "iq", ".iq"}:
            return "cf32_le"
        return None

    def _load_json_required(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Metadata file not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Metadata JSON must contain an object")
        return value

    def _sha256_file(self, path: Path, chunk_size: int = 1024 * 1024) -> str:
        if not path.exists():
            raise FileNotFoundError(f"IQ data file not found: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
