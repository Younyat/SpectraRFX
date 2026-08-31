"""One-time migration (2026-08-08, point 1): recomputes receiver_identity_id,
qualified_acquisition_profile_hash, and receiver_epoch for every real
CaptureRecord on disk, using the corrected logic in
acquisition/receiver_identity.py and acquisition/receiver_epoch_assignment.py
-- fixes the real bug the previous receiver_epoch derivation had: it used
the legacy, inconsistent `device_id`/`receiver_device_id` field (sometimes a
normalized/hashed id, sometimes the raw hardware serial for the SAME
physical unit), silently splitting one real B200 (real serial E3R04Z1B2)
into two different "epochs" with no real hardware event behind the split.

Every capture whose receiver_epoch (or the two new fields) actually changes
gets a real migration_ledger.jsonl entry via migration_ledger.record_migration
-- this migration is NOT retroactive: it runs for real, now, with real
timestamps.

Idempotent: recomputing twice in a row produces the same result and records
no further changes (verified by this module's own test).

Usage (from the backend/ directory):
    python -m app.modules.ble_rffi_studio.migrations.migrate_v3_receiver_epoch [storage_root]
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.infrastructure.ble.capture.ble_offline_replay import read_json, write_json

from ..acquisition.receiver_epoch_assignment import ReceiverEpochInput, assign_receiver_epochs
from ..acquisition.receiver_identity import compute_qualified_acquisition_profile_hash, compute_receiver_identity_id
from .migration_ledger import record_migration

MIGRATION_VERSION = "v3-receiver-epoch-2026-08-08"
_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage" / "ble_rffi_studio"


def migrate_receiver_epochs(root: Path) -> list[str]:
    """Rewrites captures/*.json in place where receiver_identity_id/
    qualified_acquisition_profile_hash/receiver_epoch/
    receiver_epoch_boundary_reason actually change. Returns the changed
    capture_ids."""
    captures_dir = root / "captures"
    if not captures_dir.is_dir():
        return []

    paths = sorted(captures_dir.glob("*.json"))
    records = [(path, read_json(path)) for path in paths]

    # Step 1: recompute the two pure, per-capture facts from fields every
    # already-persisted CaptureRecord carries (never re-reads the legacy
    # manifest -- CaptureRecord already stores sdr_model/sdr_serial/
    # sample_rate_sps/etc, and sdr_serial was always the real hardware
    # serial, unlike the buggy receiver_device_id).
    for _, data in records:
        data["receiver_identity_id"] = compute_receiver_identity_id(sdr_model=data.get("sdr_model", ""), device_serial=data.get("sdr_serial"))
        data["qualified_acquisition_profile_hash"] = compute_qualified_acquisition_profile_hash(
            sdr_model=data.get("sdr_model", ""), device_serial=data.get("sdr_serial"),
            sample_rate_sps=int(data.get("sample_rate_sps") or 0), frontend_bandwidth_hz=int(data.get("frontend_bandwidth_hz") or 0),
            gain_db=float(data.get("gain_db") or 0.0), gain_mode=data.get("gain_mode") or "unknown",
            rx_channel=data.get("rx_channel") or "", antenna_port=data.get("antenna_port") or "",
            clock_source=data.get("clock_source"), time_source=data.get("time_source"),
            capture_tool=data.get("capture_tool") or "",
        )

    # Step 2: sequential epoch assignment across every real capture -- a
    # manifest-declared receiver_epoch already on the record is honored as
    # an override (declared_receiver_epoch), matching capture_stage.py.
    epoch_inputs = [
        ReceiverEpochInput(
            capture_id=data["capture_id"], receiver_identity_id=data["receiver_identity_id"],
            qualified_acquisition_profile_hash=data["qualified_acquisition_profile_hash"],
            acquisition_started_at=data["created_at"],
            declared_receiver_epoch=data.get("receiver_epoch") if data.get("receiver_epoch_boundary_reason") == "MANIFEST_DECLARED" else None,
        )
        for _, data in records
    ]
    assignment_by_capture_id = {a.capture_id: a for a in assign_receiver_epochs(epoch_inputs)}

    changed: list[str] = []
    for path, data in records:
        capture_id = data["capture_id"]
        assignment = assignment_by_capture_id[capture_id]
        old_epoch = data.get("receiver_epoch")
        old_reason = data.get("receiver_epoch_boundary_reason")
        new_epoch = assignment.receiver_epoch
        new_reason = assignment.receiver_epoch_boundary_reason

        touched = old_epoch != new_epoch or old_reason != new_reason
        data["receiver_epoch"] = new_epoch
        data["receiver_epoch_boundary_reason"] = new_reason
        write_json(path, data)

        if touched:
            record_migration(
                root, migration_version=MIGRATION_VERSION, artifact_type="CaptureRecord", artifact_id=capture_id,
                field="receiver_epoch", old_value=old_epoch, new_value=new_epoch,
                reason=(
                    "Corrected receiver_epoch derivation: identity now normalized off the real hardware serial "
                    "(never the legacy device_id field, which inconsistently held a hashed id for some captures "
                    "and the raw serial for others of the SAME physical B200), and epoch now reflects a real "
                    "sequential session boundary (profile change or session-gap proxy) instead of a bare identity hash."
                ),
                migration_tool="migrate_v3_receiver_epoch.py",
            )
            changed.append(capture_id)
    return changed


def main(root: Path | None = None) -> None:
    root = root or _DEFAULT_ROOT
    changed = migrate_receiver_epochs(root)
    print(f"Recomputed receiver_epoch for {len(changed)} capture(s) with a real change.")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
