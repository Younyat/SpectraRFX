"""Paper-representation pass (2026-08-17): new supporting-table builders --
TX composition, partition composition, receiver-epoch table, and the
scientific completeness report. All zero new science: real cross-references
over already-real registry/capture/split/readiness artifacts.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.registry.physical_device_registry import PhysicalDeviceRegistry
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

from ._helpers import write_capture


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def test_build_tx_composition_table_aggregates_real_captures_per_registered_unit(tmp_path):
    repo = _repo(tmp_path)
    registry = PhysicalDeviceRegistry(repo.ble_root / "registry")
    registry.register_physical_unit(
        physical_unit_id="UNIT-A", project_id="PROJ", device_family="TEST-FAMILY", manufacturer="ACME",
        operator_declaration_id="decl-1", first_registered_at="2026-08-01T00:00:00Z",
    )

    cap1 = write_capture(repo.ble_root, capture_id="CAP-1", session_id="S1", physical_unit_id="UNIT-A")
    cap1 = cap1.model_copy(update={"target_reference_id": "UNIT-A", "day_id": "2026-08-01", "center_frequency_hz": 2_402_000_000})
    (repo.ble_root / "captures" / "CAP-1.json").write_text(json.dumps(cap1.model_dump(mode="json")), encoding="utf-8")

    cap2 = write_capture(repo.ble_root, capture_id="CAP-2", session_id="S2", physical_unit_id="UNIT-A")
    cap2 = cap2.model_copy(update={"target_reference_id": "UNIT-A", "day_id": "2026-08-03", "center_frequency_hz": 2_426_000_000})
    (repo.ble_root / "captures" / "CAP-2.json").write_text(json.dumps(cap2.model_dump(mode="json")), encoding="utf-8")

    rows = repo.build_tx_composition_table()
    assert len(rows) == 1
    row = rows[0]
    assert row["physical_unit_id"] == "UNIT-A"
    assert row["device_family"] == "TEST-FAMILY"
    assert row["real_capture_count"] == 2
    assert row["channels"] == [37, 38]
    assert row["day_range"] == {"first": "2026-08-01", "last": "2026-08-03"}


def test_build_partition_composition_table_counts_windows_captures_sessions_per_domain(tmp_path):
    repo = _repo(tmp_path)
    path = repo.ble_root / "splits" / "DS-1__v1__TARGET_VS_BACKGROUND.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": "DS-1", "dataset_version": "v1",
        "scientific_task": "TARGET_VS_BACKGROUND", "policy": "test", "split_status": "READY",
        "assignments": [
            {"example_id": "e1", "physical_unit_id": "A", "capture_id": "CAP-1", "session_id": "S1", "split": "TRAIN", "split_reason": "t"},
            {"example_id": "e2", "physical_unit_id": "A", "capture_id": "CAP-1", "session_id": "S1", "split": "TRAIN", "split_reason": "t"},
            {"example_id": "e3", "physical_unit_id": "A", "capture_id": "CAP-2", "session_id": "S2", "split": "VALIDATION", "split_reason": "t"},
        ],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-17T00:00:00Z", "split_manifest_sha256": "hash",
    }), encoding="utf-8")

    table = repo.build_partition_composition_table("DS-1", "v1", "TARGET_VS_BACKGROUND")
    assert table["split_status"] == "READY"
    assert table["leakage_check_status"] == "PASSED"
    assert table["domains"]["TRAIN"] == {"n_examples": 2, "n_captures": 1, "n_sessions": 1}
    assert table["domains"]["VALIDATION"] == {"n_examples": 1, "n_captures": 1, "n_sessions": 1}
    assert table["domains"]["TEST"] == {"n_examples": 0, "n_captures": 0, "n_sessions": 0}


def test_build_receiver_epoch_table_groups_real_captures_by_epoch(tmp_path):
    repo = _repo(tmp_path)
    cap1 = write_capture(repo.ble_root, capture_id="CAP-1", session_id="S1", physical_unit_id="UNIT-A")
    cap1 = cap1.model_copy(update={
        "target_reference_id": "UNIT-A", "day_id": "2026-08-01", "center_frequency_hz": 2_402_000_000,
        "receiver_epoch": "IDENTITY-1-session-001", "receiver_epoch_boundary_reason": "FIRST_CAPTURE_FOR_IDENTITY",
    })
    (repo.ble_root / "captures" / "CAP-1.json").write_text(json.dumps(cap1.model_dump(mode="json")), encoding="utf-8")

    cap2 = write_capture(repo.ble_root, capture_id="CAP-2", session_id="S2", physical_unit_id="UNIT-B")
    cap2 = cap2.model_copy(update={
        "target_reference_id": "UNIT-B", "day_id": "2026-08-01", "center_frequency_hz": 2_402_000_000,
        "receiver_epoch": "IDENTITY-1-session-001", "receiver_epoch_boundary_reason": "FIRST_CAPTURE_FOR_IDENTITY",
    })
    (repo.ble_root / "captures" / "CAP-2.json").write_text(json.dumps(cap2.model_dump(mode="json")), encoding="utf-8")

    rows = repo.build_receiver_epoch_table()
    assert len(rows) == 1
    row = rows[0]
    assert row["receiver_epoch"] == "IDENTITY-1-session-001"
    assert row["boundary_reason"] == "FIRST_CAPTURE_FOR_IDENTITY"
    assert row["n_captures"] == 2
    assert row["physical_units"] == ["UNIT-A", "UNIT-B"]
    assert row["channels"] == [37]


def test_get_scientific_completeness_report_uses_the_users_exact_vocabulary(tmp_path):
    repo = _repo(tmp_path)
    report = repo.get_scientific_completeness_report()
    statuses = {item["status"] for item in report["items"]}
    # Every status must be one of the user's exact 5 requested values.
    assert statuses <= {"AVAILABLE", "PENDING_REAL_ACQUISITION", "BLOCKED", "NOT_ELIGIBLE", "PROTECTED"}
    by_item = {item["item"]: item for item in report["items"]}
    assert by_item["rq1_protected_future"]["status"] == "PROTECTED"
    assert by_item["strong_native_sdr_association"]["status"] == "BLOCKED"
    assert by_item["rq4_packet_content_dependence"]["status"] == "NOT_ELIGIBLE"  # 0 registered units -- honestly not eligible, not fabricated AVAILABLE
    assert by_item["confirmatory_protocol_freeze"]["status"] == "BLOCKED"
    assert by_item["confirmatory_protocol_freeze"]["missing_evidence"]  # real missing fields, never an empty list on an empty repo
