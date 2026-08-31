"""Migration-provenance correction (2026-08-08, point 5): a general,
append-only audit trail for any script that rewrites already-persisted
metadata. Never touches I/Q -- purely a record of what metadata changed,
when, why, and by what tool.
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.migrations.migration_ledger import ledger_path, read_migration_ledger, record_migration


def test_record_migration_appends_a_real_entry_with_all_required_fields(tmp_path):
    record = record_migration(
        tmp_path, migration_version="test-v1", artifact_type="CaptureRecord", artifact_id="CAP-1",
        field="receiver_epoch", old_value="epoch-old", new_value="epoch-new", reason="testing",
        migration_tool="test_migration_ledger.py",
    )
    assert record.migration_id.startswith("mig-")
    assert record.timestamp_utc
    assert record.status == "SUCCESS"
    assert record.retroactive is False

    entries = read_migration_ledger(tmp_path)
    assert len(entries) == 1
    assert entries[0]["artifact_id"] == "CAP-1"
    assert entries[0]["old_value"] == "epoch-old"
    assert entries[0]["new_value"] == "epoch-new"


def test_migration_ledger_is_append_only_across_multiple_calls(tmp_path):
    record_migration(tmp_path, migration_version="v1", artifact_type="CaptureRecord", artifact_id="CAP-1", field="a", old_value=1, new_value=2, reason="r1", migration_tool="t1")
    record_migration(tmp_path, migration_version="v1", artifact_type="CaptureRecord", artifact_id="CAP-2", field="b", old_value=3, new_value=4, reason="r2", migration_tool="t1")
    entries = read_migration_ledger(tmp_path)
    assert len(entries) == 2
    assert [e["artifact_id"] for e in entries] == ["CAP-1", "CAP-2"]


def test_migration_id_is_deterministic_for_the_same_inputs(tmp_path):
    r1 = record_migration(tmp_path, migration_version="v1", artifact_type="X", artifact_id="A", field="f", old_value=1, new_value=2, reason="r", migration_tool="t", timestamp_utc="2026-08-08T00:00:00Z")
    assert r1.migration_id == "mig-" + __import__("hashlib").sha256("v1:X:A:f:2026-08-08T00:00:00Z".encode()).hexdigest()[:32]


def test_retroactive_reconstruction_is_explicitly_flagged(tmp_path):
    record = record_migration(
        tmp_path, migration_version="v0-retroactive", artifact_type="CaptureRecord", artifact_id="CAP-1",
        field="center_frequency_hz", old_value=2476000000, new_value=2402000000,
        reason="P0.5 real bug fix, reconstructed after the fact", migration_tool="retroactive_reconstruction",
        retroactive=True, timestamp_utc="2026-08-08T00:00:00Z",
    )
    assert record.retroactive is True
    entries = read_migration_ledger(tmp_path)
    assert entries[0]["retroactive"] is True


def test_read_migration_ledger_is_empty_for_a_fresh_root(tmp_path):
    assert read_migration_ledger(tmp_path) == []


def test_ledger_path_is_under_provenance_subdirectory(tmp_path):
    assert ledger_path(tmp_path) == tmp_path / "provenance" / "migration_ledger.jsonl"
