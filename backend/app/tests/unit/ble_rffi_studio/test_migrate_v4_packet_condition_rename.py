"""RQ4 correction (2026-08-09): drops the legacy `packet_variant` key from
real, already-persisted CaptureRecord JSON, renamed to `packet_condition`.
Confirmed safe: the field was always null on every real capture -- this
migration never has real data to lose.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.migrations.migrate_v4_packet_condition_rename import migrate_packet_condition_rename
from app.modules.ble_rffi_studio.migrations.migration_ledger import read_migration_ledger


def test_migration_drops_legacy_packet_variant_key(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    (captures_dir / "CAP-1.json").write_text(json.dumps({"capture_id": "CAP-1", "packet_variant": None, "sdr_model": "B200"}), encoding="utf-8")

    changed = migrate_packet_condition_rename(tmp_path)
    assert changed == ["CAP-1"]

    data = json.loads((captures_dir / "CAP-1.json").read_text())
    assert "packet_variant" not in data
    assert data["packet_condition"] is None


def test_migration_leaves_captures_without_the_legacy_key_untouched(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    (captures_dir / "CAP-2.json").write_text(json.dumps({"capture_id": "CAP-2", "sdr_model": "B200"}), encoding="utf-8")

    changed = migrate_packet_condition_rename(tmp_path)
    assert changed == []


def test_migration_is_idempotent(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    (captures_dir / "CAP-1.json").write_text(json.dumps({"capture_id": "CAP-1", "packet_variant": None}), encoding="utf-8")

    first = migrate_packet_condition_rename(tmp_path)
    assert first == ["CAP-1"]
    second = migrate_packet_condition_rename(tmp_path)
    assert second == []


def test_migration_logs_a_real_ledger_entry(tmp_path):
    captures_dir = tmp_path / "captures"
    captures_dir.mkdir()
    (captures_dir / "CAP-1.json").write_text(json.dumps({"capture_id": "CAP-1", "packet_variant": None}), encoding="utf-8")

    migrate_packet_condition_rename(tmp_path)
    entries = read_migration_ledger(tmp_path)
    assert len(entries) == 1
    assert entries[0]["artifact_id"] == "CAP-1"
    assert entries[0]["field"] == "packet_variant->packet_condition"
    assert entries[0]["retroactive"] is False
    assert entries[0]["migration_tool"] == "migrate_v4_packet_condition_rename.py"
