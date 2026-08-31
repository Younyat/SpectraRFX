"""One-time migration (2026-08-09, RQ4 packet_condition/analytical_region
separation): drops the legacy `packet_variant` key from any real, already-
persisted CaptureRecord JSON that still has it, since the field was renamed
to `packet_condition` in contracts/capture.py (never conflated with
packet_content/field_mapping.py's AnalyticalRegion -- a different concept).

Safe by construction: `packet_variant` was NEVER populated with a real,
non-null value on any real capture (confirmed: every occurrence found on
disk is `null`) -- dropping the key loses no real information. Captures that
never had the key at all are left untouched (nothing to migrate).

Every capture whose JSON actually changes gets a real migration_ledger.jsonl
entry via migration_ledger.record_migration -- NOT retroactive, runs for
real, now, with real timestamps.

Usage (from the backend/ directory):
    python -m app.modules.ble_rffi_studio.migrations.migrate_v4_packet_condition_rename [storage_root]
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.infrastructure.ble.capture.ble_offline_replay import read_json, write_json

from .migration_ledger import record_migration

MIGRATION_VERSION = "v4-packet-condition-rename-2026-08-09"
_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage" / "ble_rffi_studio"


def migrate_packet_condition_rename(root: Path) -> list[str]:
    """Rewrites captures/*.json in place, dropping a literal `packet_variant`
    key wherever present. Returns the changed capture_ids."""
    captures_dir = root / "captures"
    if not captures_dir.is_dir():
        return []

    changed: list[str] = []
    for path in sorted(captures_dir.glob("*.json")):
        data = read_json(path)
        if "packet_variant" not in data:
            continue
        old_value = data.pop("packet_variant")
        if "packet_condition" not in data:
            data["packet_condition"] = None
        write_json(path, data)

        capture_id = data.get("capture_id", path.stem)
        record_migration(
            root, migration_version=MIGRATION_VERSION, artifact_type="CaptureRecord", artifact_id=capture_id,
            field="packet_variant->packet_condition", old_value=old_value, new_value=data["packet_condition"],
            reason=(
                "Renamed packet_variant to packet_condition (RQ2/RQ3/RQ4 primary-analysis contract close-out): "
                "the old name collided with packet_content/field_mapping.py's AnalyticalRegion "
                "(FULL_BURST/ADVA_EXCLUDED/PRE_PDU) despite meaning something different -- what was physically "
                "transmitted, not which derived sample region is analyzed. The field was always null on this "
                "capture; no real value was lost."
            ),
            migration_tool="migrate_v4_packet_condition_rename.py",
        )
        changed.append(capture_id)
    return changed


def main(root: Path | None = None) -> None:
    root = root or _DEFAULT_ROOT
    changed = migrate_packet_condition_rename(root)
    print(f"Renamed packet_variant->packet_condition for {len(changed)} capture(s).")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
