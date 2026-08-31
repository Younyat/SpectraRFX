"""The v2 capture-purpose-taxonomy migration must correctly translate real,
already-persisted CaptureRecord/ExampleRecord JSON (old 2-value
capture_purpose, PENDING_REVIEW eligibility) to the new vocabulary, be
idempotent, and never touch a record that was never in the old vocabulary.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.ble_rffi_studio.migrations.migrate_v2_capture_purpose_taxonomy import (
    migrate_captures,
    migrate_examples,
    recompute_target_presence_status,
)


def _write_capture(root: Path, capture_id: str, **fields) -> None:
    captures_dir = root / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "schema_version": "ble-rffi-studio-capture-v1", "project_id": "P1", "campaign_id": "C1",
        "capture_id": capture_id, "session_id": "S1", "execution_id": "E1", "data_origin": "REAL_B200",
        "receiver_device_id": "d", "sdr_model": "b200", "rx_channel": "RX2", "antenna_port": "RX2",
        "sample_rate_sps": 4_000_000, "sample_dtype": "cf32_le", "byte_order": "little_endian",
        "sample_count": 1000, "channel_count": 1, "center_frequency_hz": 2_402_000_000,
        "frontend_bandwidth_hz": 2_000_000, "effective_bandwidth_hz": 2_000_000, "gain_db": 20.0, "gain_mode": "manual",
        "capture_duration_s": 1.0, "capture_tool": "t", "iq_path": "iq.cf32", "iq_size_bytes": 8000, "iq_sha256": "0" * 64,
        "acquisition_quality": "PASSED", "discontinuities": 0, "replay_status": "FULLY_PROCESSED", "created_at": "2026-07-28T00:00:00Z",
    }
    base.update(fields)
    (captures_dir / f"{capture_id}.json").write_text(json.dumps(base), encoding="utf-8")


def _write_examples(root: Path, capture_id: str, rows: list[dict]) -> Path:
    evidence_dir = root / "evidence" / capture_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "examples.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_migrate_captures_translates_target_device_and_sets_no_background_kind(tmp_path):
    _write_capture(tmp_path, "CAP-1", capture_purpose="TARGET_DEVICE", target_state="POWERED_ON", target_reference_id="UNIT-01", dataset_role="POSITIVE_CANDIDATE")

    changed = migrate_captures(tmp_path)

    assert changed == ["CAP-1"]
    data = json.loads((tmp_path / "captures" / "CAP-1.json").read_text(encoding="utf-8"))
    assert data["capture_purpose"] == "TARGET_DEVICE_ON"
    assert data["background_kind"] is None
    assert data["target_presence_status"] is None


def test_migrate_captures_translates_background_environment_with_a_reference_unit_to_target_off(tmp_path):
    _write_capture(tmp_path, "CAP-2", capture_purpose="BACKGROUND_ENVIRONMENT", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED", target_reference_id="UNIT-01", dataset_role="NEGATIVE_CANDIDATE")

    migrate_captures(tmp_path)

    data = json.loads((tmp_path / "captures" / "CAP-2.json").read_text(encoding="utf-8"))
    assert data["capture_purpose"] == "BACKGROUND_TARGET_OFF"
    assert data["background_kind"] == "TARGET_DECLARED_OFF_OR_REMOVED"
    assert data["target_state"] == "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"  # unchanged for this purpose


def test_migrate_captures_translates_background_environment_without_a_reference_unit_to_general(tmp_path):
    _write_capture(tmp_path, "CAP-3", capture_purpose="BACKGROUND_ENVIRONMENT", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED", dataset_role="NEGATIVE_CANDIDATE")

    migrate_captures(tmp_path)

    data = json.loads((tmp_path / "captures" / "CAP-3.json").read_text(encoding="utf-8"))
    assert data["capture_purpose"] == "BACKGROUND_GENERAL"
    assert data["background_kind"] == "GENERAL_AMBIENT"
    assert data["target_state"] is None  # no specific target in question anymore


def test_migrate_captures_is_idempotent_and_skips_already_migrated_or_unset_records(tmp_path):
    _write_capture(tmp_path, "CAP-4", capture_purpose="TARGET_DEVICE_ON", target_reference_id="UNIT-01")
    _write_capture(tmp_path, "CAP-5")  # capture_purpose never set at all

    changed = migrate_captures(tmp_path)

    assert changed == []
    assert json.loads((tmp_path / "captures" / "CAP-4.json").read_text(encoding="utf-8"))["capture_purpose"] == "TARGET_DEVICE_ON"


def test_migrate_examples_translates_purpose_and_eligibility_using_the_owning_captures_reference_unit(tmp_path):
    _write_capture(tmp_path, "CAP-6", capture_purpose="BACKGROUND_ENVIRONMENT", target_reference_id="UNIT-01")
    _write_examples(tmp_path, "CAP-6", [
        {"example_id": "ex-1", "capture_id": "CAP-6", "capture_purpose": "BACKGROUND_ENVIRONMENT", "dataset_eligibility": "PENDING_REVIEW", "physical_unit_id": None},
    ])

    changed = migrate_examples(tmp_path)

    assert changed == ["CAP-6"]
    rows = [json.loads(line) for line in (tmp_path / "evidence" / "CAP-6" / "examples.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["capture_purpose"] == "BACKGROUND_TARGET_OFF"
    assert rows[0]["background_kind"] == "TARGET_DECLARED_OFF_OR_REMOVED"
    assert rows[0]["dataset_eligibility"] == "PENDING_ANALYSIS"


def test_migrate_examples_is_idempotent(tmp_path):
    _write_capture(tmp_path, "CAP-7", capture_purpose="TARGET_DEVICE_ON")
    _write_examples(tmp_path, "CAP-7", [
        {"example_id": "ex-1", "capture_id": "CAP-7", "capture_purpose": "TARGET_DEVICE_ON", "background_kind": None, "dataset_eligibility": "ELIGIBLE", "physical_unit_id": "UNIT-01"},
    ])

    changed = migrate_examples(tmp_path)

    assert changed == []


def test_recompute_target_presence_status_persists_a_real_decision_after_migration(tmp_path):
    _write_capture(tmp_path, "CAP-8", capture_purpose="TARGET_DEVICE_ON", target_reference_id="UNIT-01")
    _write_examples(tmp_path, "CAP-8", [
        {
            "schema_version": "ble-rffi-studio-example-v1", "example_id": "ex-1", "project_id": "P1", "campaign_id": "C1",
            "capture_id": "CAP-8", "execution_id": "E1", "session_id": "S1", "candidate_id": "c1", "packet_id": "p1",
            "source_iq_sha256": "0" * 64, "iq_start_sample": 0, "iq_end_sample": 100,
            "physical_unit_id": "UNIT-01", "logical_transmitter_id": "TX-1", "capture_purpose": "TARGET_DEVICE_ON", "background_kind": None,
            "association_status": "STRONG", "quality_status": "PASSED", "dataset_eligibility": "PENDING_ANALYSIS",
            "channel": 37, "sample_rate_sps": 4_000_000, "center_frequency_hz": 2_402_000_000, "created_at": "2026-07-28T00:00:00Z",
        },
    ])

    changed = recompute_target_presence_status(tmp_path)

    assert changed == ["CAP-8"]
    data = json.loads((tmp_path / "captures" / "CAP-8.json").read_text(encoding="utf-8"))
    assert data["target_presence_status"] == "DETECTED"
