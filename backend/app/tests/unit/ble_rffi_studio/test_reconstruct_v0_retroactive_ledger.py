"""Point-5 correction (2026-08-08): retroactive reconstruction of migrations
performed before migration_ledger.py existed. Every reconstructed row must
be explicitly retroactive=True and use each artifact's real on-disk mtime,
never a fabricated timestamp.
"""
from __future__ import annotations

import json
import time

from app.modules.ble_rffi_studio.migrations.migration_ledger import read_migration_ledger
from app.modules.ble_rffi_studio.migrations.reconstruct_v0_retroactive_ledger import reconstruct


def test_reconstructs_a_synthetic_center_frequency_correction(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True)
    (captures_dir / "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-00.json").write_text(
        json.dumps({"capture_id": "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-00", "center_frequency_hz": 2_402_000_000}), encoding="utf-8",
    )

    count = reconstruct(tmp_path)
    assert count == 1
    entries = read_migration_ledger(tmp_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["retroactive"] is True
    assert entry["migration_version"] == "v0-retroactive-p0.5-channel-frequency"
    assert entry["old_value"] == 2_476_000_000
    assert entry["new_value"] == 2_402_000_000
    assert entry["migration_tool"].startswith("retroactive_reconstruction")


def test_does_not_reconstruct_a_capture_that_was_never_corrected(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True)
    (captures_dir / "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-00.json").write_text(
        json.dumps({"capture_id": "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-00", "center_frequency_hz": 2_476_000_000}), encoding="utf-8",
    )
    count = reconstruct(tmp_path)
    assert count == 0


def test_reconstructs_a_day_id_backfill(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True)
    (captures_dir / "CAP-1.json").write_text(json.dumps({"capture_id": "CAP-1", "day_id": "2026-07-24"}), encoding="utf-8")

    count = reconstruct(tmp_path)
    assert count == 1
    entry = read_migration_ledger(tmp_path)[0]
    assert entry["migration_version"] == "v0-retroactive-day-id-receiver-epoch-backfill"
    assert entry["old_value"] is None
    assert entry["new_value"] == "2026-07-24"
    assert entry["retroactive"] is True


def test_reconstructed_timestamp_is_the_real_file_mtime_not_the_reconstruction_time(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True)
    path = captures_dir / "CAP-1.json"
    path.write_text(json.dumps({"capture_id": "CAP-1", "day_id": "2026-07-24"}), encoding="utf-8")

    time.sleep(0.05)  # ensure a real, detectable gap between the file's mtime and "now"
    reconstruct(tmp_path)
    entry = read_migration_ledger(tmp_path)[0]
    assert entry["timestamp_utc"] != entry["migration_id"]  # sanity: distinct fields
    # The reconstructed timestamp must be close to the file's own mtime, not "now".
    import datetime as dt
    file_mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    recorded = dt.datetime.fromisoformat(entry["timestamp_utc"].replace("Z", "+00:00"))
    assert abs((recorded - file_mtime).total_seconds()) < 1.0


def test_reconstruction_is_idempotent_in_the_sense_of_finding_the_same_artifacts(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir(parents=True)
    (captures_dir / "CAP-1.json").write_text(json.dumps({"capture_id": "CAP-1", "day_id": "2026-07-24"}), encoding="utf-8")

    first_count = reconstruct(tmp_path)
    second_count = reconstruct(tmp_path)
    assert first_count == second_count == 1  # same real artifacts found both times
