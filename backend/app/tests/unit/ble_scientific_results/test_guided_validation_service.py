"""End-to-end integration test for GuidedBleScientificValidationService
against a synthetic but schema-real filesystem (same contract classes and
on-disk layout real ble_rffi_studio data uses) -- verifies the orchestrator
actually wires build_records()/select_association_policy()/the calibration
reconstruction helpers together correctly, not just that each piece works
in isolation."""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.ble_scientific_results.api import ScientificResultsRepository
from app.modules.ble_scientific_results.guided_validation import GuidedBleScientificValidationService

from ._helpers import (
    make_candidate,
    make_example,
    make_ledger_row,
    write_capture,
    write_examples,
    write_frozen_dataset,
    write_quality_report,
    write_ready_split,
    write_replay_artifacts,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _patch_capture_json(ble_root: Path, capture_id: str, **fields) -> None:
    path = ble_root / "captures" / f"{capture_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_capture_manifest(legacy_capture_root: Path, capture_id: str, *, physical_unit_id: str, channel: int = 37) -> None:
    _write_json(legacy_capture_root / capture_id / "capture_manifest.json", {
        "data_sha256": f"sha-{capture_id}", "data_path": f"{capture_id}.cf32", "ble_channel": channel,
        "sample_rate_sps": 4_000_000, "created_at_utc": "2026-08-01T00:00:00Z",
        "experimental_metadata": {"physical_unit_id": physical_unit_id},
    })


def _register_physical_unit(ble_root: Path, unit_id: str) -> None:
    _write_json(ble_root / "registry" / "physical_units" / f"{unit_id}.json", {
        "physical_unit_id": unit_id, "project_id": "SCI-RESULTS-TEST-PROJECT", "device_family": "TEST",
        "status": "ACTIVE", "operator_declaration_id": "decl-1", "first_registered_at": "2026-08-01T00:00:00Z",
    })


def _register_address_binding(ble_root: Path, *, binding_id: str, unit_id: str, address: str) -> None:
    _write_json(ble_root / "registry" / "address_bindings" / f"{binding_id}.json", {
        "binding_id": binding_id, "project_id": "SCI-RESULTS-TEST-PROJECT", "address": address, "address_type": "public",
        "bound_physical_unit_id": unit_id, "binding_status": "BOUND", "binding_evidence": [],
        "first_seen": "2026-08-01T00:00:00Z", "last_seen": "2026-08-01T00:00:00Z", "history": [],
    })


def test_guided_validation_end_to_end_with_no_matched_target_and_a_valid_negative_control(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    legacy_capture_root = ble_root.parent / "ble" / "iq_captures"
    native_scan_root = ble_root.parent / "ble" / "native" / "scans"

    device_id = "DEV-1"
    _register_physical_unit(ble_root, device_id)
    _register_address_binding(ble_root, binding_id="bind-1", unit_id=device_id, address="AA:BB:CC:DD:EE:FF")

    # --- one real-shaped positive capture: CRC-valid packet, but no
    # address-matched association (address_match_status=MISMATCH) ---
    capture = write_capture(ble_root, capture_id="CAP-POS-1", session_id="SESSION-1", physical_unit_id=device_id)
    _patch_capture_json(ble_root, "CAP-POS-1", target_reference_id=device_id, capture_purpose="TARGET_DEVICE_ON")
    _write_capture_manifest(legacy_capture_root, "CAP-POS-1", physical_unit_id=device_id)
    example = make_example(capture=capture, index=0, physical_unit_id=device_id)
    write_examples(ble_root, capture, [example])
    candidate = make_candidate(index=0, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID")
    ledger_row = make_ledger_row(candidate_id=candidate["candidate_id"], association_strength="WEAK", time_delta_ms=180.0)
    ledger_row["address_match_status"] = "MISMATCH"
    ledger_row["temporal_match_status"] = "MATCHED"
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=[candidate], ledger_rows=[ledger_row])
    _write_jsonl(native_scan_root / "SESSION-1" / "advertisements.jsonl", [
        {"address": "11:22:33:44:55:66", "native_observation_id": "native-1", "timestamp_callback_utc": "2026-08-01T00:00:00.100Z"},
    ])

    example_ids = [example.example_id]
    dataset = write_frozen_dataset(
        ble_root, dataset_id=f"{device_id}-AUTO-TVB", dataset_version="1", physical_units=[device_id],
        captures=[capture.capture_id], example_ids=example_ids, class_distribution={device_id: 1, "UNKNOWN": 0},
    )
    write_ready_split(ble_root, dataset=dataset, scientific_task="TARGET_VS_BACKGROUND", example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    # --- one target-absence control candidate: BACKGROUND_TARGET_OFF, real
    # native scan running, DEV-1's address never seen ---
    absence_capture = write_capture(ble_root, capture_id="CAP-ABSENCE-1", session_id="SESSION-ABSENCE-1", physical_unit_id=None)
    _patch_capture_json(ble_root, "CAP-ABSENCE-1", capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED")
    _write_jsonl(native_scan_root / "SESSION-ABSENCE-1" / "advertisements.jsonl", [
        {"address": "99:88:77:66:55:44", "native_observation_id": "native-2", "timestamp_callback_utc": "2026-08-01T01:00:00.000Z"},
    ])

    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    service = GuidedBleScientificValidationService(repository)

    progress_calls = []
    summary = service.run(progress=lambda stage, fraction, message: progress_calls.append(stage))

    assert progress_calls  # progress hook was actually invoked
    assert summary.device_summary.keys() == {device_id}
    assert summary.device_summary[device_id]["capture_count"] == 1
    assert summary.device_summary[device_id]["crc_valid_packet_count"] == 1
    assert summary.device_summary[device_id]["strong_association_count"] == 0
    assert summary.capture_totals["total_captures"] == 1
    assert summary.capture_totals["association_calibration_eligible"] == 1

    assert summary.association_summary["matched_target_count"] == 0
    assert summary.association_summary["by_status"].get("MISMATCH") == 1

    assert summary.target_absence_summary["has_valid_control"] is True

    # No MATCHED events exist -> policy selection must fail closed, never
    # fabricate a policy from zero-coverage data.
    assert summary.association_policy_summary["status"] == "NO_THRESHOLD_SATISFIES_CRITERIA"

    # Paper-representation pass (2026-08-17): the real per-threshold sweep
    # must be structured, not only inside `detail`'s free text -- this is
    # the actual source-association calibration summary the paper needs.
    assert summary.association_policy_summary["evaluated_at"]
    assert summary.association_policy_summary["threshold_grid"]
    assert summary.association_policy_summary["coverage_by_threshold_ms"]
    assert summary.association_policy_summary["acceptance_criterion"]

    # And it must be real, persisted-to-disk, and readable back via the
    # repository's own latest-attempt getter -- not just an in-memory
    # return value.
    latest = repository.get_latest_association_calibration_summary()
    assert latest is not None
    assert latest["status"] == "NO_THRESHOLD_SATISFIES_CRITERIA"
    assert latest["coverage_by_threshold_ms"] == summary.association_policy_summary["coverage_by_threshold_ms"]

    stage_by_id = {stage.stage_id: stage for stage in summary.stages}
    assert stage_by_id["source_association"].status == "BLOCKED"
    assert stage_by_id["negative_control"].status == "PASSED"
    assert stage_by_id["association_policy"].status == "BLOCKED"

    capability_by_name = {flag.capability: flag.supported for flag in summary.capability_flags}
    assert capability_by_name["RF capture"] is True
    assert capability_by_name["BLE packet recovery"] is True
    assert capability_by_name["Physical-source association"] is False

    assert "no native target observation was matched" in summary.simplified_conclusion
    assert summary.next_required_action == "Run Live Timing Diagnostic"

    # Persistence: real files written under scientific_reports/ble/guided_validation/<run_id>/
    run_dir = repository.root / "guided_validation" / summary.run_id
    assert (run_dir / "guided_validation_summary.json").is_file()
    assert (run_dir / "calibration_records.csv").is_file()
    assert (run_dir / "artifact_index.json").is_file()


def test_guided_validation_with_no_enrolled_devices_is_blocked(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    service = GuidedBleScientificValidationService(repository)

    summary = service.run()
    assert summary.device_summary == {}
    assert summary.overall_status == "BLOCKED"
    stage_by_id = {stage.stage_id: stage for stage in summary.stages}
    assert stage_by_id["available_data"].status == "BLOCKED"
