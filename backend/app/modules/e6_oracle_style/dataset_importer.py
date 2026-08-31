"""
E6 external dataset importer.

Supports the three datasets from the Oracle-style reference project:
  - kri_wifi       KRI 16-device WiFi (SigMF, cf32)
  - uav_lightbridge DJI UAV Lightbridge (JSON + .bin, cf16_le)
  - ieee_cbrs      IEEE CBRS (SigMF, cf32_le)

And a generic SigMF importer for any new external dataset.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.modules.e6_oracle_style.dataset_manifest import (
    add_capture_to_manifest,
    new_manifest,
    save_manifest,
)
from app.modules.e6_oracle_style.sigmf_parser import (
    ieee_cbrs_label,
    kri_wifi_label,
    load_sigmf_meta,
    sigmf_center_frequency,
    sigmf_dtype,
    sigmf_sample_count,
    sigmf_sample_rate,
    uav_lightbridge_label,
)

SUPPORTED_EXTERNAL_SOURCES = {
    "kri_wifi": {
        "label": "KRI 16-Device WiFi",
        "description": "16-device 802.11 fingerprinting dataset (Nordrum et al., Northeastern University). SigMF format, cf32.",
        "metadata_glob": "**/*.sigmf-meta",
        "data_suffix": ".sigmf-data",
        "default_dtype": "cf32",
        "task": "device_fingerprinting",
        "signal_family": "wifi",
        "protocol": "ieee80211",
    },
    "uav_lightbridge": {
        "label": "UAV DJI Lightbridge",
        "description": "DJI M100 Lightbridge control-link UAV dataset (Genesys Lab). JSON + .bin format, cf16_le.",
        "metadata_glob": "**/*.json",
        "data_suffix": ".bin",
        "default_dtype": "cf16_le",
        "task": "device_fingerprinting",
        "signal_family": "uav",
        "protocol": "lightbridge",
    },
    "ieee_cbrs": {
        "label": "IEEE CBRS",
        "description": "CBRS band emitter identification dataset (IEEE). SigMF format, cf32_le.",
        "metadata_glob": "**/*.sigmf-meta",
        "data_suffix": ".sigmf-data",
        "default_dtype": "cf32_le",
        "task": "device_fingerprinting",
        "signal_family": "cbrs",
        "protocol": "cbrs_lte",
    },
    "generic_sigmf": {
        "label": "Generic SigMF Dataset",
        "description": "Any dataset in SigMF format. Labels extracted from filename or annotation core:label.",
        "metadata_glob": "**/*.sigmf-meta",
        "data_suffix": ".sigmf-data",
        "default_dtype": "cf32",
        "task": "device_fingerprinting",
        "signal_family": "unknown",
        "protocol": "",
    },
}


def scan_external_dataset(
    source_type: str,
    source_root: str,
    ieee_target: str = "auto",
    limit_files: Optional[int] = None,
) -> dict[str, Any]:
    """Scan an external dataset directory and return a summary without importing."""
    if source_type not in SUPPORTED_EXTERNAL_SOURCES:
        raise ValueError(f"Unknown external source: {source_type}. Supported: {list(SUPPORTED_EXTERNAL_SOURCES)}")
    info = SUPPORTED_EXTERNAL_SOURCES[source_type]
    root = Path(source_root)
    if not root.exists():
        raise FileNotFoundError(f"Source root not found: {root}")

    records = _collect_records(source_type, root, info, ieee_target, limit_files)
    labels: Dict[str, int] = {}
    dtypes: Dict[str, int] = {}
    total_bytes = 0
    for rec in records:
        labels[rec["label"]] = labels.get(rec["label"], 0) + 1
        dtypes[rec["dtype"]] = dtypes.get(rec["dtype"], 0) + 1
        total_bytes += int(rec.get("data_size_bytes") or 0)

    return {
        "source_type": source_type,
        "source_root": str(root),
        "source_info": info,
        "record_count": len(records),
        "label_count": len(labels),
        "labels": labels,
        "dtypes": dtypes,
        "total_data_gb": total_bytes / (1024 ** 3),
        "examples": [
            {"label": r["label"], "dtype": r["dtype"], "data_path": str(r["data_path"]), "sample_count": r.get("sample_count")}
            for r in records[:5]
        ],
    }


def import_external_dataset(
    source_type: str,
    source_root: str,
    dataset_name: str,
    e6_datasets_dir: Path,
    ieee_target: str = "auto",
    limit_files: Optional[int] = None,
    max_files_per_class: Optional[int] = None,
    progress_cb=None,
) -> dict[str, Any]:
    """Import an external dataset into E6 format."""
    def _cb(pct: int, msg: str) -> None:
        if progress_cb:
            progress_cb(pct, msg)

    if source_type not in SUPPORTED_EXTERNAL_SOURCES:
        raise ValueError(f"Unknown external source: {source_type}. Supported: {list(SUPPORTED_EXTERNAL_SOURCES)}")
    info = SUPPORTED_EXTERNAL_SOURCES[source_type]
    root = Path(source_root)
    if not root.exists():
        raise FileNotFoundError(f"Source root not found: {root}")

    dataset_dir = e6_datasets_dir / dataset_name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    manifest = new_manifest(
        dataset_name=dataset_name,
        dataset_type="external",
        source=source_type,
        task=info["task"],
        signal_family=info["signal_family"],
        protocol=info["protocol"],
        dtype=info["default_dtype"],
        notes=f"Imported from {root}",
    )

    _cb(5, f"Scanning {source_type} at {root}")
    records = _collect_records(source_type, root, info, ieee_target, limit_files)
    _cb(10, f"Found {len(records)} records · filtering…")

    # Balance by class
    if max_files_per_class is not None:
        filtered = []
        per_class: Dict[str, int] = {}
        for r in records:
            lbl = r["label"]
            if per_class.get(lbl, 0) < max_files_per_class:
                filtered.append(r)
                per_class[lbl] = per_class.get(lbl, 0) + 1
        records = filtered

    total = max(len(records), 1)
    imported = 0
    for rec in records:
        add_capture_to_manifest(
            manifest,
            capture_id=rec["capture_id"],
            iq_path=str(rec["data_path"]),
            label=rec["label"],
            dtype=rec["dtype"],
            sample_rate_hz=rec.get("sample_rate_hz"),
            center_frequency_hz=rec.get("center_frequency_hz"),
            sample_count=rec.get("sample_count"),
            group=rec.get("group", rec["capture_id"]),
            session_id="",
            notes="",
        )
        imported += 1
        pct = 10 + int(imported / total * 84)
        _cb(pct, f"Importing {imported}/{total} · {rec['label']}")

    _cb(96, "Saving manifest")
    save_manifest(dataset_dir, manifest)

    labels = sorted({c["label"] for c in manifest["captures"]})
    return {
        "dataset_name": dataset_name,
        "dataset_dir": str(dataset_dir),
        "source_type": source_type,
        "captures_imported": imported,
        "label_count": len(labels),
        "labels": labels,
    }


def _collect_records(
    source_type: str,
    root: Path,
    info: dict[str, Any],
    ieee_target: str,
    limit_files: Optional[int],
) -> list[dict[str, Any]]:
    records = []
    glob_pattern = info["metadata_glob"]
    data_suffix = info["data_suffix"]

    for meta_path in sorted(root.rglob(glob_pattern)):
        if source_type == "uav_lightbridge" and meta_path.suffix.lower() != ".json":
            continue
        # Skip SigMF meta files that are not actual metadata (avoid .sigmf-data being picked up)
        if source_type in {"kri_wifi", "ieee_cbrs", "generic_sigmf"} and not meta_path.name.endswith(".sigmf-meta"):
            continue

        data_path = meta_path.with_suffix(data_suffix)
        if not data_path.exists():
            continue

        try:
            meta = load_sigmf_meta(meta_path)
        except Exception:
            continue

        try:
            label = _label_for(source_type, meta_path, meta, ieee_target)
        except Exception:
            continue

        dtype = sigmf_dtype(meta, info["default_dtype"])
        records.append({
            "capture_id": meta_path.stem.replace(" ", "_"),
            "meta_path": meta_path,
            "data_path": data_path,
            "label": label,
            "dtype": dtype,
            "sample_rate_hz": sigmf_sample_rate(meta),
            "center_frequency_hz": sigmf_center_frequency(meta),
            "sample_count": sigmf_sample_count(meta),
            "group": str(meta_path.relative_to(root)),
            "data_size_bytes": data_path.stat().st_size,
        })

        if limit_files and len(records) >= limit_files:
            break

    return records


def _label_for(source_type: str, meta_path: Path, meta: dict[str, Any], ieee_target: str) -> str:
    if source_type == "kri_wifi":
        return kri_wifi_label(meta_path)
    if source_type == "uav_lightbridge":
        return uav_lightbridge_label(meta)
    if source_type == "ieee_cbrs":
        return ieee_cbrs_label(meta, meta_path, ieee_target)
    # generic_sigmf: try core:label in annotations
    ann = meta.get("annotations")
    if isinstance(ann, list) and ann:
        lbl = ann[0].get("core:label")
        if lbl:
            return str(lbl)
    # fallback: parent folder name
    return meta_path.parent.name or "unknown"
