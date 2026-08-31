"""E6 model registry — persists model metadata in model_registry.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_path(e6_root: Path) -> Path:
    return e6_root / "model_registry.json"


def load_registry(e6_root: Path) -> List[dict[str, Any]]:
    path = _registry_path(e6_root)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_registry(e6_root: Path, registry: List[dict[str, Any]]) -> None:
    e6_root.mkdir(parents=True, exist_ok=True)
    _registry_path(e6_root).write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def register_model(
    e6_root: Path,
    model_id: str,
    model_name: str,
    algorithm: str,
    task: str,
    dataset_name: str,
    model_path: str,
    classes: List[str],
    feature_names: List[str],
    window_size: int,
    dtype: str,
    metrics: dict[str, Any],
    enabled_for_live: bool = True,
    notes: str = "",
) -> dict[str, Any]:
    registry = load_registry(e6_root)
    existing_ids = {r["model_id"] for r in registry}
    entry = {
        "model_id": model_id,
        "model_name": model_name or model_id,
        "algorithm": algorithm,
        "task": task,
        "dataset_name": dataset_name,
        "model_path": model_path,
        "classes": classes,
        "class_count": len(classes),
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "window_size": window_size,
        "dtype": dtype,
        "metrics": {
            "accuracy": metrics.get("accuracy"),
            "macro_f1": metrics.get("macro_f1"),
            "balanced_accuracy": metrics.get("balanced_accuracy"),
            "weighted_f1": metrics.get("weighted_f1"),
        },
        "enabled_for_live": enabled_for_live,
        "notes": notes,
        "registered_at": _now(),
        "status": "ready",
    }
    if model_id in existing_ids:
        registry = [entry if r["model_id"] == model_id else r for r in registry]
    else:
        registry.append(entry)
    save_registry(e6_root, registry)
    return entry


def get_model(e6_root: Path, model_id: str) -> Optional[dict[str, Any]]:
    for r in load_registry(e6_root):
        if r["model_id"] == model_id:
            return r
    return None


def set_live_enabled(e6_root: Path, model_id: str, enabled: bool) -> dict[str, Any]:
    registry = load_registry(e6_root)
    updated = None
    for r in registry:
        if r["model_id"] == model_id:
            r["enabled_for_live"] = enabled
            updated = r
    if updated is None:
        raise ValueError(f"Model not found in registry: {model_id}")
    save_registry(e6_root, registry)
    return updated


def delete_model_entry(e6_root: Path, model_id: str) -> None:
    registry = [r for r in load_registry(e6_root) if r["model_id"] != model_id]
    save_registry(e6_root, registry)


def live_ready_models(e6_root: Path) -> List[dict[str, Any]]:
    return [r for r in load_registry(e6_root) if r.get("enabled_for_live") and Path(str(r.get("model_path", ""))).exists()]
