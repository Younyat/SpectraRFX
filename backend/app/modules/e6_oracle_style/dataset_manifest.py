"""E6 dataset manifest — read/write the canonical dataset_manifest.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_manifest(
    dataset_name: str,
    dataset_type: str,
    source: str,
    task: str,
    signal_family: str = "",
    protocol: str = "",
    center_frequency_hz: Optional[float] = None,
    sample_rate_hz: Optional[float] = None,
    bandwidth_hz: Optional[float] = None,
    dtype: str = "cf32",
    receiver_model: str = "",
    receiver_serial: str = "",
    antenna: str = "",
    gain_db: Optional[float] = None,
    environment: str = "lab",
    label_mode: str = "strong_label",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "dataset_name": dataset_name,
        "dataset_type": dataset_type,
        "source": source,
        "task": task,
        "signal_family": signal_family,
        "protocol": protocol,
        "center_frequency_hz": center_frequency_hz,
        "sample_rate_hz": sample_rate_hz,
        "bandwidth_hz": bandwidth_hz,
        "dtype": dtype,
        "receiver_model": receiver_model,
        "receiver_serial": receiver_serial,
        "antenna": antenna,
        "gain_db": gain_db,
        "environment": environment,
        "label_mode": label_mode,
        "notes": notes,
        "created_at": _now(),
        "updated_at": _now(),
        "captures": [],
        "devices": {},
        "splits": {"train": [], "validation": [], "test": []},
    }


def load_manifest(dataset_dir: Path) -> dict[str, Any]:
    manifest_path = dataset_dir / "dataset_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"dataset_manifest.json not found in {dataset_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def save_manifest(dataset_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_datasets(e6_datasets_dir: Path) -> List[dict[str, Any]]:
    result = []
    if not e6_datasets_dir.exists():
        return result
    for dataset_dir in sorted(e6_datasets_dir.iterdir()):
        manifest_path = dataset_dir / "dataset_manifest.json"
        if manifest_path.exists():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                result.append({
                    "dataset_name": m.get("dataset_name", dataset_dir.name),
                    "dataset_type": m.get("dataset_type", "unknown"),
                    "source": m.get("source", ""),
                    "task": m.get("task", ""),
                    "signal_family": m.get("signal_family", ""),
                    "dtype": m.get("dtype", "cf32"),
                    "capture_count": len(m.get("captures", [])),
                    "label_count": len({c.get("label") for c in m.get("captures", []) if c.get("label")}),
                    "created_at": m.get("created_at", ""),
                    "updated_at": m.get("updated_at", ""),
                    "dataset_dir": str(dataset_dir),
                })
            except Exception:
                pass
    return result


def add_capture_to_manifest(
    manifest: dict[str, Any],
    capture_id: str,
    iq_path: str,
    label: str,
    dtype: str,
    sample_rate_hz: Optional[float],
    center_frequency_hz: Optional[float],
    sample_count: Optional[int],
    group: str = "",
    session_id: str = "",
    notes: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    record = {
        "capture_id": capture_id,
        "iq_path": iq_path,
        "label": label,
        "dtype": dtype,
        "sample_rate_hz": sample_rate_hz,
        "center_frequency_hz": center_frequency_hz,
        "sample_count": sample_count,
        "group": group or session_id or capture_id,
        "session_id": session_id,
        "notes": notes,
        "added_at": _now(),
        **(extra or {}),
    }
    existing_ids = {c["capture_id"] for c in manifest["captures"]}
    if capture_id in existing_ids:
        manifest["captures"] = [record if c["capture_id"] == capture_id else c for c in manifest["captures"]]
    else:
        manifest["captures"].append(record)


def build_splits(
    manifest: dict[str, Any],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> dict[str, Any]:
    """Group-disjoint stratified split by (label, group)."""
    import numpy as np
    captures = manifest.get("captures", [])
    if not captures:
        return {"train": [], "validation": [], "test": []}

    rng = np.random.default_rng(seed)
    labels = sorted({c["label"] for c in captures if c.get("label")})
    train_ids, val_ids, test_ids = [], [], []

    for label in labels:
        label_caps = [c for c in captures if c.get("label") == label]
        groups = sorted({c.get("group", c["capture_id"]) for c in label_caps})
        if len(groups) < 2:
            train_ids.extend(c["capture_id"] for c in label_caps)
            continue
        groups_arr = np.array(groups)
        rng.shuffle(groups_arr)
        n_val = max(1, int(round(len(groups_arr) * val_ratio)))
        n_test = max(1, int(round(len(groups_arr) * (1 - train_ratio - val_ratio))))
        n_test = min(n_test, len(groups_arr) - n_val - 1)
        n_test = max(n_test, 0)
        val_groups = set(groups_arr[:n_val].tolist())
        test_groups = set(groups_arr[n_val:n_val + n_test].tolist())
        train_groups = set(groups_arr[n_val + n_test:].tolist())
        for c in label_caps:
            g = c.get("group", c["capture_id"])
            if g in val_groups:
                val_ids.append(c["capture_id"])
            elif g in test_groups:
                test_ids.append(c["capture_id"])
            else:
                train_ids.append(c["capture_id"])

    manifest["splits"] = {"train": train_ids, "validation": val_ids, "test": test_ids}
    return manifest["splits"]
