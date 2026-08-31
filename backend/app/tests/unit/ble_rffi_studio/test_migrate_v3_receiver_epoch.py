"""Point-1 correction (2026-08-08): historical backfill migration.
Reproduces the exact real bug found on disk -- the SAME physical B200 split
into two receiver_epochs purely because some captures record the legacy
device_id as a hashed string and others as the raw serial -- and verifies
the migration unifies them, is idempotent, and logs a real migration_ledger
entry for every capture whose receiver_epoch actually changes.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.migrations.migrate_v3_receiver_epoch import migrate_receiver_epochs
from app.modules.ble_rffi_studio.migrations.migration_ledger import read_migration_ledger

_BASE_CAPTURE = {
    "schema_version": "ble-rffi-studio-capture-v1", "project_id": "P1", "campaign_id": "C1",
    "session_id": "S1", "execution_id": "E1", "data_origin": "REAL_B200",
    "receiver_device_id": None, "sdr_model": "B200", "sdr_serial": "E3R04Z1B2",
    "rx_channel": "RX2", "antenna_port": "RX2", "sample_rate_sps": 4_000_000, "sample_dtype": "cf32_le",
    "byte_order": "little_endian", "sample_count": 1, "channel_count": 1, "center_frequency_hz": 2_402_000_000,
    "frontend_bandwidth_hz": 2_000_000, "effective_bandwidth_hz": 2_000_000, "gain_db": 20.0, "gain_mode": "manual",
    "clock_source": None, "time_source": None, "capture_duration_s": 1.0, "capture_tool": "ble-sdr-capture-v3",
    "iq_path": "iq.cf32", "iq_size_bytes": 1, "iq_sha256": "sha", "acquisition_quality": "PASSED",
    "discontinuities": 0, "replay_status": "FULLY_PROCESSED",
    # Old-shape fields this migration must correct:
    "receiver_identity_id": None, "qualified_acquisition_profile_hash": None,
    "receiver_epoch": None, "receiver_epoch_boundary_reason": None,
}


def _write_capture(captures_dir, capture_id, created_at, *, old_receiver_epoch, old_receiver_device_id):
    data = {
        **_BASE_CAPTURE, "capture_id": capture_id, "created_at": created_at,
        "receiver_device_id": old_receiver_device_id, "receiver_epoch": old_receiver_epoch,
    }
    (captures_dir / f"{capture_id}.json").write_text(json.dumps(data), encoding="utf-8")


def test_migration_unifies_the_same_physical_b200_split_by_legacy_device_id(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    # Reproduces the exact real finding: 2 captures of the SAME physical
    # B200 (sdr_serial=E3R04Z1B2 identical) previously assigned DIFFERENT
    # bare-hash epochs because the OLD logic keyed off receiver_device_id,
    # which held a hashed id for one and the raw serial for the other.
    _write_capture(captures_dir, "CAP-1", "2026-08-01T00:00:00Z", old_receiver_epoch="epoch-AAAA", old_receiver_device_id="sdr-hashed-id-123")
    _write_capture(captures_dir, "CAP-2", "2026-08-01T00:05:00Z", old_receiver_epoch="epoch-BBBB", old_receiver_device_id="E3R04Z1B2")

    changed = migrate_receiver_epochs(tmp_path)
    assert set(changed) == {"CAP-1", "CAP-2"}

    cap1 = json.loads((captures_dir / "CAP-1.json").read_text())
    cap2 = json.loads((captures_dir / "CAP-2.json").read_text())
    assert cap1["receiver_identity_id"] == cap2["receiver_identity_id"]
    assert cap1["receiver_epoch"] == cap2["receiver_epoch"]
    assert cap1["receiver_epoch"] != "epoch-AAAA"
    assert cap2["receiver_epoch"] != "epoch-BBBB"


def test_migration_is_idempotent(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    _write_capture(captures_dir, "CAP-1", "2026-08-01T00:00:00Z", old_receiver_epoch=None, old_receiver_device_id="sdr-hashed-id-123")

    first = migrate_receiver_epochs(tmp_path)
    assert first == ["CAP-1"]
    second = migrate_receiver_epochs(tmp_path)
    assert second == []


def test_migration_logs_a_real_ledger_entry_for_every_real_change(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    _write_capture(captures_dir, "CAP-1", "2026-08-01T00:00:00Z", old_receiver_epoch="epoch-AAAA", old_receiver_device_id="sdr-hashed-id-123")

    migrate_receiver_epochs(tmp_path)
    entries = read_migration_ledger(tmp_path)
    assert len(entries) == 1
    assert entries[0]["artifact_id"] == "CAP-1"
    assert entries[0]["field"] == "receiver_epoch"
    assert entries[0]["old_value"] == "epoch-AAAA"
    assert entries[0]["retroactive"] is False
    assert entries[0]["migration_tool"] == "migrate_v3_receiver_epoch.py"


def test_migration_does_not_change_captures_with_no_real_serial(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    data = {**_BASE_CAPTURE, "capture_id": "CAP-SYNTH", "created_at": "2026-08-01T00:00:00Z", "sdr_serial": None, "receiver_device_id": "synthetic-demo-generator"}
    (captures_dir / "CAP-SYNTH.json").write_text(json.dumps(data), encoding="utf-8")

    changed = migrate_receiver_epochs(tmp_path)
    assert changed == []
    result = json.loads((captures_dir / "CAP-SYNTH.json").read_text())
    assert result["receiver_identity_id"] is None
    assert result["receiver_epoch"] is None
