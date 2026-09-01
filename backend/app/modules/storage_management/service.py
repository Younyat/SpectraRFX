"""Real, filesystem-grounded disk-usage inventory + confirmation-gated
deletion for everything under `settings.storage.storage_root`.

Every number here comes directly from `Path.stat()`/`os.walk` over the real
files on disk -- nothing is estimated, cached, or derived from a database
that could drift from reality. The one exception is BLE I/Q captures, which
are enriched with real fields already computed by `BleCaptureJobManager`
(`created_at_utc`, `capture_role`, `dataset_eligible`, ...) read from each
capture's own `capture_manifest.json` -- reused, not recomputed.

"Preserved" is a disclosed HEURISTIC, not a hard delete-block: every BLE I/Q
capture defaults to preserved=True (it is primary, irreplaceable evidence),
and every other item defaults to preserved=True unless its path matches a
known regenerable-cache/temp naming pattern. Deletion is never blocked by
this flag -- the operator always sees an explicit confirmation step
(enforced by `confirm=True` here, and by a real modal on the frontend); the
flag only changes how strongly that confirmation warns them.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_NOT_PRESERVED_NAME_HINTS = {"offline_replays", "temp", "tmp", "cache", "logs", "__pycache__"}


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _walk_stats(path: Path) -> tuple[int, int, str | None]:
    total_bytes = 0
    file_count = 0
    latest_mtime: float | None = None
    for entry in path.rglob("*"):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        file_count += 1
        if latest_mtime is None or stat.st_mtime > latest_mtime:
            latest_mtime = stat.st_mtime
    return total_bytes, file_count, (_utc(latest_mtime) if latest_mtime is not None else None)


def _is_preserved_by_name(relative_path: Path) -> bool:
    return not any(part in _NOT_PRESERVED_NAME_HINTS for part in relative_path.parts)


class StorageManagementError(Exception):
    pass


class StorageManagementService:
    def __init__(self, storage_root: Path, capture_manager: Any = None) -> None:
        self.storage_root = storage_root
        self.capture_manager = capture_manager

    def summary(self) -> dict[str, Any]:
        if not self.storage_root.is_dir():
            return {"storage_root": str(self.storage_root), "total_bytes": 0, "total_file_count": 0, "categories": []}
        categories = []
        total_bytes = 0
        total_file_count = 0
        for entry in sorted(self.storage_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            size_bytes, file_count, last_modified_utc = _walk_stats(entry)
            total_bytes += size_bytes
            total_file_count += file_count
            categories.append({
                "name": entry.name,
                "relative_path": entry.name,
                "total_bytes": size_bytes,
                "file_count": file_count,
                "last_modified_utc": last_modified_utc,
            })
        categories.sort(key=lambda category: category["total_bytes"], reverse=True)
        return {
            "storage_root": str(self.storage_root),
            "total_bytes": total_bytes,
            "total_file_count": total_file_count,
            "categories": categories,
        }

    def list_items(self, relative_path: str) -> dict[str, Any]:
        target = self._resolve(relative_path)
        if not target.is_dir():
            raise FileNotFoundError(relative_path)

        ble_iq_captures_dir = self.storage_root / "ble" / "iq_captures"
        if target == ble_iq_captures_dir and self.capture_manager is not None:
            return {"relative_path": relative_path, "items": self._list_ble_captures(ble_iq_captures_dir)}

        items = []
        for entry in sorted(target.iterdir(), key=lambda item: item.name):
            item_relative = entry.relative_to(self.storage_root)
            if entry.is_dir():
                size_bytes, file_count, last_modified_utc = _walk_stats(entry)
                kind = "directory"
            else:
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                size_bytes, file_count, last_modified_utc = stat.st_size, 1, _utc(stat.st_mtime)
                kind = "file"
            preserved = _is_preserved_by_name(item_relative)
            items.append({
                "item_id": str(item_relative).replace("\\", "/"),
                "display_name": entry.name,
                "kind": kind,
                "size_bytes": size_bytes,
                "file_count": file_count,
                "last_modified_utc": last_modified_utc,
                "preserved": preserved,
                "preserved_reason": (
                    "No specific regenerable-cache pattern matched -- treated as potentially "
                    "primary/irreplaceable data by default." if preserved else
                    "Folder name matches a known regenerable-cache/temporary-data pattern."
                ),
            })
        items.sort(key=lambda item: item["size_bytes"], reverse=True)
        return {"relative_path": relative_path, "items": items}

    def _list_ble_captures(self, iq_captures_dir: Path) -> list[dict[str, Any]]:
        manifests_by_id = {
            manifest["capture_id"]: manifest
            for manifest in self.capture_manager.list_captures()
            if manifest.get("capture_id")
        }
        items = []
        for entry in iq_captures_dir.iterdir():
            if not entry.is_dir():
                continue
            size_bytes, file_count, last_modified_utc = _walk_stats(entry)
            manifest = manifests_by_id.get(entry.name)
            if manifest is not None:
                items.append({
                    "item_id": f"ble/iq_captures/{entry.name}",
                    "display_name": entry.name,
                    "kind": "ble_capture",
                    "size_bytes": size_bytes,
                    "file_count": file_count,
                    "created_at_utc": manifest.get("created_at_utc"),
                    "last_modified_utc": last_modified_utc,
                    "preserved": True,
                    "preserved_reason": "Primary raw I/Q evidence from a real SDR capture. Deleting it "
                                         "is irreversible -- the only way to get it back is a new physical recording.",
                    "extra": {
                        "capture_role": manifest.get("capture_role"),
                        "ble_channel": manifest.get("ble_channel"),
                        "sample_rate_sps": manifest.get("sample_rate_sps"),
                        "dataset_eligible": manifest.get("dataset_eligible"),
                        "scientific_campaign_member": manifest.get("scientific_campaign_member"),
                        "execution_purpose": manifest.get("execution_purpose"),
                    },
                })
            else:
                items.append({
                    "item_id": f"ble/iq_captures/{entry.name}",
                    "display_name": entry.name,
                    "kind": "ble_capture_incomplete",
                    "size_bytes": size_bytes,
                    "file_count": file_count,
                    "created_at_utc": None,
                    "last_modified_utc": last_modified_utc,
                    "preserved": True,
                    "preserved_reason": "No completed capture manifest found (interrupted or in-progress "
                                         "job) -- treated as preserved by default since it may still hold recoverable evidence.",
                    "extra": {},
                })
        items.sort(key=lambda item: item.get("created_at_utc") or item.get("last_modified_utc") or "", reverse=True)
        return items

    def delete_item(self, item_id: str, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise StorageManagementError("Deletion requires explicit confirmation.")
        target = self._resolve(item_id)
        if target == self.storage_root.resolve():
            raise StorageManagementError("Refusing to delete the storage root itself.")
        if not target.exists():
            raise FileNotFoundError(item_id)
        size_bytes, _file_count, _mtime = (
            _walk_stats(target) if target.is_dir() else (target.stat().st_size, 1, None)
        )
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"deleted_item_id": item_id, "freed_bytes": size_bytes}

    def _resolve(self, relative_path: str) -> Path:
        cleaned = relative_path.strip("/\\")
        storage_root_resolved = self.storage_root.resolve()
        candidate = (self.storage_root / cleaned).resolve() if cleaned else storage_root_resolved
        if candidate != storage_root_resolved and storage_root_resolved not in candidate.parents:
            raise StorageManagementError(f"Path escapes the storage root: {relative_path}")
        return candidate
