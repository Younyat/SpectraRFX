from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HDF5ExperimentExporter:
    generator_version = "rf_experiment_lab_hdf5_manifest_v1"
    supported_representations = [
        "raw_iq",
        "spectrogram",
        "waterfall",
        "fft_psd",
        "physical_features",
        "bispectrum",
        "csp_scd",
    ]

    def preview_manifest(self, payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        selected = self._select_records(payload, records)
        manifest = self._build_manifest(payload, selected)
        return {
            "preview_only": True,
            "available": True,
            "binary_hdf5_available": importlib.util.find_spec("h5py") is not None,
            "manifest": manifest,
            "would_write": payload.get("output_path"),
        }

    def export_manifest_json(self, output_path: str | Path, payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = self._build_manifest(payload, self._select_records(payload, records))
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "preview_only": False,
            "available": True,
            "path": str(path),
            "binary_hdf5_available": importlib.util.find_spec("h5py") is not None,
            "manifest": manifest,
        }

    def export_manifest(self, output_path: str | Path, records: list[dict[str, Any]]) -> dict[str, Any]:
        return self.export_manifest_json(output_path, {}, records)

    def dataset_version_object(self, payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        selected = self._select_records(payload, records)
        created_at = datetime.now(timezone.utc).isoformat()
        return {
            "dataset_version": payload.get("dataset_version", "experiment_dataset_v0.1"),
            "source_capture_ids": [str(record.get("capture_id")) for record in selected],
            "source_capture_hashes": self._source_hashes(selected),
            "representation_list": self._representations(payload),
            "split_strategy": payload.get("split_strategy", "metadata_or_session_disjoint"),
            "label_schema": payload.get("label_schema", self._label_schema(selected)),
            "qc_policy": payload.get("qc_policy", "accepted_for_training_doubtful_for_robustness_rejected_excluded"),
            "created_at": created_at,
            "notes": payload.get("notes", ""),
        }

    def _build_manifest(self, payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        version = self.dataset_version_object(payload, records)
        return {
            "dataset_id": payload.get("dataset_id", "rf_experiment_dataset"),
            "dataset_version": version,
            "source_captures": records,
            "source_hashes": version["source_capture_hashes"],
            "representations": self._representation_manifest(payload),
            "labels": self._labels(records),
            "splits": self._splits(records, payload),
            "metadata_fields": self._metadata_fields(records),
            "quality_control_fields": self._qc_fields(records),
            "experiment_compatibility": {
                "stage_1_signal_recognition": True,
                "stage_2_device_fingerprinting": True,
                "requires_random_window_split": False,
                "supported_representations": self.supported_representations,
            },
            "created_at": created_at,
            "generator_version": self.generator_version,
        }

    def _select_records(self, payload: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = payload.get("capture_ids") or []
        if not ids:
            return records
        wanted = {str(item) for item in ids}
        return [record for record in records if str(record.get("capture_id")) in wanted]

    def _representations(self, payload: dict[str, Any]) -> list[str]:
        requested = payload.get("representations") or ["raw_iq", "spectrogram", "waterfall", "fft_psd"]
        clean = [str(item) for item in requested]
        for placeholder in ("physical_features", "bispectrum", "csp_scd"):
            if placeholder not in clean:
                clean.append(placeholder)
        return clean

    def _representation_manifest(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": representation,
                "available": representation in {"raw_iq", "spectrogram", "waterfall", "fft_psd"},
                "status": "planned_placeholder" if representation in {"physical_features", "bispectrum", "csp_scd"} else "manifest_supported",
            }
            for representation in self._representations(payload)
        ]

    def _source_hashes(self, records: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
        hashes: dict[str, dict[str, str | None]] = {}
        for record in records:
            capture_id = str(record.get("capture_id"))
            hashes[capture_id] = {
                "raw_iq": record.get("sha256_raw_iq") or self._safe_hash(record.get("raw_file")),
                "metadata": self._safe_hash(record.get("metadata_file")),
            }
        return hashes

    def _labels(self, records: list[dict[str, Any]]) -> dict[str, list[str]]:
        keys = ["technology", "transmitter_id", "device_model", "dataset_split", "qc_status"]
        return {key: sorted({str(record.get(key)) for record in records if record.get(key) not in (None, "")}) for key in keys}

    def _splits(self, records: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy": payload.get("split_strategy", "metadata_or_session_disjoint"),
            "by_capture_id": {
                str(record.get("capture_id")): record.get("dataset_split", "unknown")
                for record in records
            },
        }

    def _metadata_fields(self, records: list[dict[str, Any]]) -> list[str]:
        fields = set()
        for record in records:
            fields.update(record.keys())
        return sorted(fields)

    def _qc_fields(self, records: list[dict[str, Any]]) -> dict[str, list[str]]:
        fields = ["qc_status", "snr_db"]
        return {field: sorted({str(record.get(field)) for record in records if record.get(field) not in (None, "")}) for field in fields}

    def _label_schema(self, records: list[dict[str, Any]]) -> dict[str, str]:
        labels = self._labels(records)
        return {key: "categorical" for key, values in labels.items() if values}

    def _safe_hash(self, path_value: Any) -> str | None:
        if not path_value:
            return None
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
