"""I.2 (records), I.3 (accounting), I.4 (immutability): builds canonical
records against a synthetic fixture that DOES have real candidate_manifest/
packet_association_ledger artifacts (unlike build_passing_fixture, which
has no replay directory at all), then exercises campaign accounting and
quality summary on top of them.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api import ScientificResultsRepository
from app.modules.ble_scientific_results.contracts import AssociationPolicy

from ._helpers import (
    make_candidate,
    make_ledger_row,
    make_example,
    write_capture,
    write_examples,
    write_frozen_dataset,
    write_quality_report,
    write_ready_split,
    write_replay_artifacts,
)


def _new_repository(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    return ScientificResultsRepository(tmp_path / "sci_results", ble_root), ble_root


def _freeze_and_create_run(repository, *, dataset_id, dataset_version, scientific_task, channels=None):
    payload = {"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"}
    if channels:
        payload["channels"] = channels
    contract = repository.freeze_protocol(payload)
    return repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)


def _build_fixture_with_replay(ble_root, *, dataset_id="SCI-REC-DS", dataset_version="1", scientific_task="TARGET_VS_BACKGROUND"):
    """One capture with 3 candidates: one PROCESSED+CRC_VALID+STRONG
    association (-> TARGET_ASSOCIATED_PACKET), one PROCESSED+CRC_VALID with
    no ledger row (-> CRC_VALID_PACKET), one not PROCESSED (-> RF_ACTIVITY)."""
    capture = write_capture(ble_root, capture_id="SCI-REC-CAP-01", session_id="SCI-REC-SESSION-01", physical_unit_id="UNIT-A")
    examples = [
        make_example(capture=capture, index=0, physical_unit_id="UNIT-A", association_status="STRONG"),
        make_example(capture=capture, index=1, physical_unit_id=None),
        make_example(capture=capture, index=2, physical_unit_id=None),
    ]
    write_examples(ble_root, capture, examples)

    candidates = [
        make_candidate(index=0, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID"),
        make_candidate(index=1, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID"),
        make_candidate(index=2, capture_id=capture.capture_id, processing_status="FAILED_DECODE", crc_status="NOT_APPLICABLE"),
    ]
    # Ledger row only for candidate 0 (matches example[0]'s candidate_id so it resolves physical_unit_id).
    ledger = [make_ledger_row(candidate_id=candidates[0]["candidate_id"], association_strength="STRONG")]
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=candidates, ledger_rows=ledger)

    example_ids = [e.example_id for e in examples]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 1, "UNKNOWN": 2})
    write_ready_split(ble_root, dataset=dataset, scientific_task=scientific_task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)
    return dataset_id, dataset_version, scientific_task, capture.capture_id, [c["candidate_id"] for c in candidates]


def _frozen_test_policy(*, threshold_ms: float = 250.0) -> AssociationPolicy:
    """A minimal, directly-constructed AssociationPolicy for tests that
    need TARGET_ASSOCIATED_PACKET enabled -- real policies come only from
    calibration/association_calibration.py::select_association_threshold,
    but a fixture-level frozen object is all the gate itself checks for."""
    fields = dict(
        policy_id="test-policy-1", threshold_ms=threshold_ms, threshold_grid=[threshold_ms], selection_rule="test fixture",
        calibration_campaign_id="TEST-CAL-1", devices_used=["UNIT-A"], captures_used=["SCI-REC-CAP-01"],
        callback_batching_policy="per-capture", duplicate_policy="first-decoded-wins", field_match_policy="address+PDU-type",
        ambiguity_policy="test fixture", target_absence_result={}, frozen_at="2026-08-06T00:00:00Z",
    )
    unhashed = AssociationPolicy(**fields, policy_hash="")
    return AssociationPolicy(**fields, policy_hash=unhashed.content_hash(exclude={"policy_hash"}))


def test_build_records_classifies_bursts_correctly(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, candidate_ids = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    result = repository.build_records(run.paper_run_id, association_policy=_frozen_test_policy())
    assert result.capture_record_count == 1
    assert result.burst_record_count == 3
    # Real 10s time windows (default window_duration_s=10, sample_rate=
    # 4_000_000): all 3 candidates in this fixture sit within a few
    # thousand samples of each other, well inside one 40M-sample window --
    # so they collapse into exactly 1 real decision window, not 3 (the
    # corrected behavior; Fase 2 first shipped 1 candidate = 1 window).
    assert result.decision_window_record_count == 1
    assert result.captures_without_replay == []

    bursts = repository.list_burst_records(run.paper_run_id, limit=10)
    classes = {b["candidate_group_id"]: b["burst_class"] for b in bursts}
    assert classes[candidate_ids[0]] == "TARGET_ASSOCIATED_PACKET"
    assert classes[candidate_ids[1]] == "CRC_VALID_PACKET"
    assert classes[candidate_ids[2]] == "SOURCE_CONTEXT_ONLY"

    windows = repository.list_window_records(run.paper_run_id, limit=10)
    assert len(windows) == 1
    assert windows[0]["candidate_count"] == 3
    assert windows[0]["window_status"] == "ACTIVE_ELIGIBLE"


def test_target_associated_packet_is_disabled_without_a_frozen_association_policy(tmp_path):
    """STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN: the exact same
    fixture that produces TARGET_ASSOCIATED_PACKET when a real policy is
    supplied must NEVER produce it by default -- there is no hardcoded
    fallback threshold anymore."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, candidate_ids = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    repository.build_records(run.paper_run_id)  # no association_policy passed

    bursts = repository.list_burst_records(run.paper_run_id, limit=10)
    classes = {b["candidate_group_id"]: b["burst_class"] for b in bursts}
    assert "TARGET_ASSOCIATED_PACKET" not in classes.values()
    assert classes[candidate_ids[0]] == "SOURCE_CONTEXT_ONLY"
    flagged = next(b for b in bursts if b["candidate_group_id"] == candidate_ids[0])
    assert "STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN" in flagged["diagnostic_flags"]


def test_burst_resolves_to_existing_capture_and_ids_are_unique(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    captures = repository.list_capture_records(run.paper_run_id)
    bursts = repository.list_burst_records(run.paper_run_id)
    capture_ids = {c["capture_id"] for c in captures}
    assert all(b["capture_id"] in capture_ids for b in bursts)
    burst_ids = [b["burst_id"] for b in bursts]
    assert len(burst_ids) == len(set(burst_ids))


def test_null_is_never_confused_with_zero(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    capture = repository.get_capture_record(run.paper_run_id, capture_id)
    # overflow_count/discontinuity_count ARE genuinely 0 (real source_acquisition_quality says so).
    assert capture["overflow_count"] == 0
    assert capture["discontinuity_count"] == 0
    # snr_db has NO source anywhere -- must be None, never fabricated as 0.
    assert capture["snr_db"] is None
    assert "snr_db" in capture["not_documented_fields"]


def test_source_manifest_ids_are_traceable(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    capture = repository.get_capture_record(run.paper_run_id, capture_id)
    assert capture_id in capture["source_manifest_ids"]
    bursts = repository.list_burst_records(run.paper_run_id)
    for burst in bursts:
        assert burst["source_artifact_ids"]


def test_campaign_accounting_reflects_real_channel_declared_vs_observed(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task, channels=[37, 38])
    repository.build_records(run.paper_run_id, association_policy=_frozen_test_policy())

    accounting = repository.build_campaign_accounting(run.paper_run_id)
    counters = accounting["counters"]
    assert counters["observed_captures"] == 1
    assert counters["captures_with_target_association"] == 1
    assert counters["planned_channel_blocks"] == 2
    assert counters["complete_channel_blocks"] == 1  # only channel 37 is actually observed in the fixture


def test_quality_summary_computes_real_association_rates(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    summary = repository.build_quality_summary(run.paper_run_id)
    association = summary["association_summary"][0]
    assert association["burst_count"] == 3
    assert association["crc_valid_rate"] == 2 / 3  # 2 of 3 candidates are CRC VALID
    assert association["association_coverage"] == 1 / 3  # only 1 has a ledger row


def test_figures_are_written_deterministically(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)
    repository.build_campaign_accounting(run.paper_run_id)
    repository.build_quality_summary(run.paper_run_id)

    written = repository.build_campaign_figures(run.paper_run_id)
    assert len(written) == 16  # 8 figures x (svg, png)
    for path_str in written:
        from pathlib import Path
        assert Path(path_str).stat().st_size > 0


# ---------------------------------------------------------------------
# I.4: immutability -- building records never touches ble_rffi_studio.
# ---------------------------------------------------------------------

def test_build_records_never_modifies_ble_rffi_studio_or_iq(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    def snapshot_mtimes(root):
        return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}

    ble_root_mtimes_before = snapshot_mtimes(ble_root)
    legacy_root_mtimes_before = snapshot_mtimes(ble_root.parent / "ble" / "iq_captures")

    repository.build_records(run.paper_run_id)
    repository.build_campaign_accounting(run.paper_run_id)
    repository.build_quality_summary(run.paper_run_id)
    repository.build_campaign_figures(run.paper_run_id)

    assert snapshot_mtimes(ble_root) == ble_root_mtimes_before
    assert snapshot_mtimes(ble_root.parent / "ble" / "iq_captures") == legacy_root_mtimes_before


def test_repeated_build_produces_identical_content_hashes(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    first = repository.build_records(run.paper_run_id)
    first_captures = repository.list_capture_records(run.paper_run_id)
    second = repository.build_records(run.paper_run_id)
    second_captures = repository.list_capture_records(run.paper_run_id)

    assert first.capture_record_count == second.capture_record_count
    assert json.dumps(first_captures, sort_keys=True) == json.dumps(second_captures, sort_keys=True)


def test_changing_an_input_produces_a_detectably_different_output(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, _ = _build_fixture_with_replay(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)
    before = repository.get_capture_record(run.paper_run_id, capture_id)

    # Mutate the real capture's acquisition_quality directly, then rebuild.
    capture_path = ble_root / "captures" / f"{capture_id}.json"
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    payload["acquisition_quality"] = "INCOMPLETE"
    capture_path.write_text(json.dumps(payload), encoding="utf-8")

    repository.build_records(run.paper_run_id)
    after = repository.get_capture_record(run.paper_run_id, capture_id)
    assert before["capture_quality"] != after["capture_quality"]
