from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RFExperimentInternalDatasetLab:
    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root / "rf_experiment_lab" / "internal_dataset_lab"
        self.samples_dir = self.root / "samples"
        self.registry_path = self.root / "samples.json"
        self.samples_dir.mkdir(parents=True, exist_ok=True)

    def list_samples(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return value if isinstance(value, list) else []

    def create_sample(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_iq = Path(str(payload.get("iq_path") or payload.get("raw_iq_path") or ""))
        if not source_iq.exists():
            raise FileNotFoundError(f"iq_path not found: {source_iq}")
        sample_id = str(payload.get("sample_id") or f"rfexp_sample_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}")
        target_dir = self.samples_dir / sample_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_iq = target_dir / source_iq.name
        if source_iq.resolve() != target_iq.resolve():
            shutil.copy2(source_iq, target_iq)
        metadata = self._metadata(payload, sample_id, target_iq)
        metadata_path = target_dir / f"{sample_id}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        record = {
            "sample_id": sample_id,
            "capture_id": sample_id,
            "source": "rf_experiment_lab_internal",
            "raw_file": str(target_iq),
            "metadata_file": str(metadata_path),
            "datatype": metadata["datatype"],
            "sample_rate_hz": metadata["sample_rate_hz"],
            "center_frequency_hz": metadata["center_frequency_hz"],
            "duration_seconds": metadata.get("duration_seconds"),
            "label": metadata.get("label"),
            "task": metadata.get("task"),
            "transmitter_id": metadata.get("transmitter_id"),
            "signal_type": metadata.get("signal_type"),
            "modulation_class": metadata.get("modulation_class"),
            "session_id": metadata.get("session_id"),
            "receiver_id": metadata.get("receiver_id"),
            "environment_id": metadata.get("environment_id"),
            "distance_m": metadata.get("distance_m"),
            "sha256_raw_iq": metadata["sha256"],
            "qc_status": metadata.get("qc_summary", {}).get("qc_status"),
            "split_group": metadata.get("split_group"),
            "review_status": "unreviewed",
            "created_at": metadata["created_at"],
        }
        records = [item for item in self.list_samples() if item.get("sample_id") != sample_id]
        records.append(record)
        self.registry_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return {"sample": record, "metadata": metadata}

    def review_sample(self, sample_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        records = self.list_samples()
        target = None
        for record in records:
            if record.get("sample_id") == sample_id:
                record["review_status"] = payload.get("review_status", "accepted")
                record["review_notes"] = payload.get("notes", "")
                record["label"] = payload.get("label", record.get("label"))
                for key in ("transmitter_id", "signal_type", "modulation_class", "task", "split_group"):
                    if payload.get(key) not in (None, ""):
                        record[key] = payload.get(key)
                target = record
                break
        if target is None:
            raise FileNotFoundError(f"RF Experiment Lab sample not found: {sample_id}")
        self.registry_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return target

    def as_capture_records(self) -> list[dict[str, Any]]:
        return [record for record in self.list_samples() if record.get("review_status") != "rejected"]

    def _metadata(self, payload: dict[str, Any], sample_id: str, iq_path: Path) -> dict[str, Any]:
        sample_rate = payload.get("sample_rate_hz")
        center = payload.get("center_frequency_hz")
        if sample_rate in (None, "") or center in (None, ""):
            raise ValueError("sample_rate_hz and center_frequency_hz are required for RF Experiment Lab dataset capture")
        task = str(payload.get("task", "device_fingerprinting"))
        label = payload.get("label") or payload.get("transmitter_id") or payload.get("signal_type") or payload.get("modulation_class")
        qc_summary = payload.get("qc_summary") if isinstance(payload.get("qc_summary"), dict) else {}
        qc_summary.setdefault("qc_status", "pending_review")
        return {
            "sample_id": sample_id,
            "capture_id": sample_id,
            "dataset_source": "rf_experiment_lab_internal",
            "task": task,
            "label": label,
            "label_type": payload.get("label_type") or ("transmitter_id" if task == "device_fingerprinting" else "modulation_class"),
            "raw_file": str(iq_path),
            "metadata_file": str(iq_path.with_suffix(".json")),
            "datatype": payload.get("datatype", "complex64"),
            "sample_rate_hz": sample_rate,
            "center_frequency_hz": center,
            "start_frequency_hz": payload.get("start_frequency_hz"),
            "stop_frequency_hz": payload.get("stop_frequency_hz"),
            "duration_seconds": payload.get("duration_seconds"),
            "transmitter_id": payload.get("transmitter_id"),
            "signal_type": payload.get("signal_type"),
            "modulation_class": payload.get("modulation_class"),
            "session_id": payload.get("session_id") or "rfexp_session_unassigned",
            "receiver_id": payload.get("receiver_id"),
            "environment_id": payload.get("environment_id"),
            "distance_m": payload.get("distance_m"),
            "split_group": payload.get("split_group") or payload.get("session_id") or sample_id,
            "sha256": self._sha256(iq_path),
            "qc_summary": qc_summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
