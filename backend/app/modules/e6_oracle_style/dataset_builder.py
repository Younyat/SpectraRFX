"""
E6 local dataset builder.

Creates ORACLE-style datasets from captures made in the local lab
(Capture Lab IQ files, Spectrum Lab marker captures, etc.)
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.modules.e6_oracle_style.dataset_manifest import (
    add_capture_to_manifest,
    load_manifest,
    new_manifest,
    save_manifest,
)
from app.modules.e6_oracle_style.iq_loader import _file_sample_count


def create_local_dataset(
    dataset_name: str,
    e6_datasets_dir: Path,
    task: str = "device_fingerprinting",
    signal_family: str = "",
    protocol: str = "",
    center_frequency_hz: Optional[float] = None,
    sample_rate_hz: Optional[float] = None,
    bandwidth_hz: Optional[float] = None,
    dtype: str = "cf32",
    receiver_model: str = "USRP B200",
    receiver_serial: str = "",
    antenna: str = "RX2",
    gain_db: Optional[float] = None,
    environment: str = "lab",
    notes: str = "",
) -> dict[str, Any]:
    """Create a new empty local dataset manifest."""
    _validate_dataset_name(dataset_name)
    dataset_dir = e6_datasets_dir / dataset_name
    if dataset_dir.exists() and (dataset_dir / "dataset_manifest.json").exists():
        raise ValueError(f"Dataset '{dataset_name}' already exists. Use add_capture or delete it first.")
    dataset_dir.mkdir(parents=True, exist_ok=True)

    manifest = new_manifest(
        dataset_name=dataset_name,
        dataset_type="local",
        source="local_capture",
        task=task,
        signal_family=signal_family,
        protocol=protocol,
        center_frequency_hz=center_frequency_hz,
        sample_rate_hz=sample_rate_hz,
        bandwidth_hz=bandwidth_hz,
        dtype=dtype,
        receiver_model=receiver_model,
        receiver_serial=receiver_serial,
        antenna=antenna,
        gain_db=gain_db,
        environment=environment,
        notes=notes,
    )
    save_manifest(dataset_dir, manifest)
    return {"dataset_name": dataset_name, "dataset_dir": str(dataset_dir), "status": "created"}


def add_local_capture(
    dataset_name: str,
    e6_datasets_dir: Path,
    iq_path: str,
    label: str,
    session_id: str = "",
    dtype: Optional[str] = None,
    sample_rate_hz: Optional[float] = None,
    center_frequency_hz: Optional[float] = None,
    sample_count: Optional[int] = None,
    notes: str = "",
) -> dict[str, Any]:
    """Register an existing IQ file as a capture in a local dataset."""
    dataset_dir = e6_datasets_dir / dataset_name
    manifest = load_manifest(dataset_dir)

    iq = Path(iq_path)
    if not iq.exists():
        raise FileNotFoundError(f"IQ file not found: {iq_path}")

    resolved_dtype = dtype or manifest.get("dtype") or "cf32"
    resolved_sample_count = sample_count
    if resolved_sample_count is None:
        try:
            resolved_sample_count = _file_sample_count(iq, resolved_dtype)
        except Exception:
            pass

    capture_id = _make_capture_id(str(iq), label, session_id)
    group = session_id or iq.stem

    add_capture_to_manifest(
        manifest,
        capture_id=capture_id,
        iq_path=str(iq),
        label=label,
        dtype=resolved_dtype,
        sample_rate_hz=sample_rate_hz or manifest.get("sample_rate_hz"),
        center_frequency_hz=center_frequency_hz or manifest.get("center_frequency_hz"),
        sample_count=resolved_sample_count,
        group=group,
        session_id=session_id,
        notes=notes,
    )
    # Update device registry
    if label not in manifest.get("devices", {}):
        manifest.setdefault("devices", {})[label] = {"transmitter_id": label, "added_captures": 0}
    manifest["devices"][label]["added_captures"] = manifest["devices"][label].get("added_captures", 0) + 1

    save_manifest(dataset_dir, manifest)
    labels = sorted({c["label"] for c in manifest["captures"]})
    return {
        "dataset_name": dataset_name,
        "capture_id": capture_id,
        "label": label,
        "iq_path": str(iq),
        "total_captures": len(manifest["captures"]),
        "labels": labels,
    }


def register_device(
    dataset_name: str,
    e6_datasets_dir: Path,
    transmitter_id: str,
    device_type: str = "",
    vendor: str = "",
    model: str = "",
    serial: str = "",
    mac_address: str = "",
    notes: str = "",
) -> dict[str, Any]:
    dataset_dir = e6_datasets_dir / dataset_name
    manifest = load_manifest(dataset_dir)
    manifest.setdefault("devices", {})[transmitter_id] = {
        "transmitter_id": transmitter_id,
        "device_type": device_type,
        "vendor": vendor,
        "model": model,
        "serial": serial,
        "mac_address": mac_address,
        "notes": notes,
    }
    save_manifest(dataset_dir, manifest)
    return {"dataset_name": dataset_name, "transmitter_id": transmitter_id, "status": "registered"}


def get_dataset_summary(dataset_name: str, e6_datasets_dir: Path) -> dict[str, Any]:
    dataset_dir = e6_datasets_dir / dataset_name
    manifest = load_manifest(dataset_dir)
    captures = manifest.get("captures", [])
    labels = sorted({c.get("label", "") for c in captures if c.get("label")})
    label_counts = {lbl: sum(1 for c in captures if c.get("label") == lbl) for lbl in labels}
    splits = manifest.get("splits", {})
    return {
        "dataset_name": dataset_name,
        "dataset_type": manifest.get("dataset_type"),
        "source": manifest.get("source"),
        "task": manifest.get("task"),
        "signal_family": manifest.get("signal_family"),
        "dtype": manifest.get("dtype"),
        "environment": manifest.get("environment"),
        "capture_count": len(captures),
        "label_count": len(labels),
        "labels": labels,
        "label_counts": label_counts,
        "devices": manifest.get("devices", {}),
        "splits": {
            "train": len(splits.get("train", [])),
            "validation": len(splits.get("validation", [])),
            "test": len(splits.get("test", [])),
        },
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
    }


def delete_dataset(dataset_name: str, e6_datasets_dir: Path) -> dict[str, Any]:
    """Remove a dataset manifest (does NOT delete the original IQ files)."""
    import shutil
    dataset_dir = e6_datasets_dir / dataset_name
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_name}")
    shutil.rmtree(dataset_dir)
    return {"dataset_name": dataset_name, "status": "deleted"}


def _validate_dataset_name(name: str) -> None:
    if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
        raise ValueError(f"Invalid dataset name '{name}'. Use only letters, digits, underscores, hyphens.")


def _make_capture_id(iq_path: str, label: str, session_id: str) -> str:
    key = f"{iq_path}|{label}|{session_id}"
    return hashlib.md5(key.encode()).hexdigest()[:12]
