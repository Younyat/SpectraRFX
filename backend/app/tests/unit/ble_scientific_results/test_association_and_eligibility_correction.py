"""Dedicated regression tests for the post-Fase-2 correction: association
semantics (user point 2), eligibility/diagnostic separation (point 3), and
deviation reclassification (point 4)."""
from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository

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


def _freeze_and_create_run(repository, *, dataset_id, dataset_version, scientific_task):
    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    return repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)


def test_physical_unit_id_alone_never_promotes_to_target_associated_packet(tmp_path):
    """The exact real case that triggered this correction: an example whose
    physical_unit_id resolved via PHYSICAL_ISOLATION_DECLARED (Evidence
    Stage), but whose ledger row shows association_status=NONE /
    TIME_DELTA_ABOVE_THRESHOLD. This must NEVER produce
    TARGET_ASSOCIATED_PACKET, regardless of physical_unit_id."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-ASSOC-DS", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-ASSOC-CAP", session_id="SCI-ASSOC-SESSION", physical_unit_id="UNIT-A")
    example = make_example(capture=capture, index=0, physical_unit_id="UNIT-A", association_status="NONE")
    write_examples(ble_root, capture, [example])

    candidate = make_candidate(index=0, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID")
    # Real-shaped rejection: association failed (NONE / TIME_DELTA_ABOVE_THRESHOLD),
    # yet physical_unit_id is resolved on the example via PHYSICAL_ISOLATION_DECLARED.
    ledger_row = make_ledger_row(candidate_id=candidate["candidate_id"], association_strength="NONE", association_rejection_reason="TIME_DELTA_ABOVE_THRESHOLD", time_delta_ms=None, target_address_match=False)
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=[candidate], ledger_rows=[ledger_row])

    example_ids = [example.example_id]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 1})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    bursts = repository.list_burst_records(run.paper_run_id)
    assert len(bursts) == 1
    burst = bursts[0]
    assert burst["burst_class"] == "SOURCE_CONTEXT_ONLY"
    assert burst["source_identity_origin"] == "OPERATOR_CONTEXT_DECLARED"
    assert burst["burst_class"] != "TARGET_ASSOCIATED_PACKET"
    # packet_eligible (CRC valid) is independent of label_eligible.
    assert burst["packet_eligible"] is True
    assert burst["label_eligible"] is True  # OPERATOR_CONTEXT_DECLARED still counts as SOME identity source
    assert "NO_TARGET_ASSOCIATION" not in burst["blocking_reason_codes"]


def test_time_delta_above_threshold_blocks_target_associated_even_with_strong_flag(tmp_path):
    """A ledger row that (hypothetically) reports association_strength=STRONG
    but with time_delta_ms over the 250ms threshold must still be rejected
    by the frozen criterion -- association_strength alone is not sufficient."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-ASSOC-DS2", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-ASSOC-CAP2", session_id="SCI-ASSOC-SESSION2", physical_unit_id="UNIT-A")
    example = make_example(capture=capture, index=0, physical_unit_id=None)
    write_examples(ble_root, capture, [example])

    candidate = make_candidate(index=0, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID")
    ledger_row = make_ledger_row(candidate_id=candidate["candidate_id"], association_strength="STRONG", time_delta_ms=999.0)
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=[candidate], ledger_rows=[ledger_row])

    example_ids = [example.example_id]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 0})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    burst = repository.list_burst_records(run.paper_run_id)[0]
    assert burst["burst_class"] != "TARGET_ASSOCIATED_PACKET"
    assert burst["source_identity_origin"] == "NONE"
    assert burst["label_eligible"] is False
    assert burst["training_eligible"] is False
    assert "NO_TARGET_ASSOCIATION" in burst["blocking_reason_codes"]


def test_diagnostic_flag_never_blocks_a_packet_eligible_burst(tmp_path):
    """A burst can carry diagnostic_flags (e.g. STRONG association but
    failing the full criterion) while still being packet_eligible=True --
    diagnostics never silently become blocking."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-DIAG-DS", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-DIAG-CAP", session_id="SCI-DIAG-SESSION", physical_unit_id="UNIT-A")
    example = make_example(capture=capture, index=0, physical_unit_id=None)
    write_examples(ble_root, capture, [example])

    candidate = make_candidate(index=0, capture_id=capture.capture_id, processing_status="PROCESSED", crc_status="VALID")
    ledger_row = make_ledger_row(candidate_id=candidate["candidate_id"], association_strength="STRONG", association_rejection_reason="ADDRESS_MISMATCH")
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=[candidate], ledger_rows=[ledger_row])

    example_ids = [example.example_id]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 0})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    burst = repository.list_burst_records(run.paper_run_id)[0]
    assert burst["packet_eligible"] is True
    assert burst["diagnostic_flags"]  # STRONG_BUT_FAILED_FULL_CRITERION and/or ASSOCIATION_ADDRESS_MISMATCH
    assert "NO_CRC_VALID_PACKET" not in burst["blocking_reason_codes"]


def test_ambiguous_association_is_no_longer_a_campaign_deviation(tmp_path):
    """The core Fase-2 problem: 419 routine per-burst AMBIGUOUS_ASSOCIATION
    rows were previously reported as generic campaign deviations. They must
    no longer appear in campaign_deviations at all -- only as
    diagnostic_flags on the burst itself."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-DEV-DS", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-DEV-CAP", session_id="SCI-DEV-SESSION", physical_unit_id="UNIT-A")
    examples = [make_example(capture=capture, index=i, physical_unit_id=None) for i in range(3)]
    write_examples(ble_root, capture, examples)

    candidates = [make_candidate(index=i, capture_id=capture.capture_id) for i in range(3)]
    ledger_rows = [make_ledger_row(candidate_id=c["candidate_id"], association_strength="NONE", association_rejection_reason="MULTIPLE_NATIVE_CALLBACKS") for c in candidates]
    write_replay_artifacts(ble_root, capture_id=capture.capture_id, candidates=candidates, ledger_rows=ledger_rows)

    example_ids = [e.example_id for e in examples]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 0})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    deviations = repository.list_deviation_records(run.paper_run_id, limit=100)
    assert not any(d["deviation_type"] == "AMBIGUOUS_ASSOCIATION" for d in deviations)
    assert not any(d["classification"] == "CANDIDATE_EXCLUSION" and "AMBIGUOUS" in d["deviation_type"] for d in deviations)

    bursts = repository.list_burst_records(run.paper_run_id)
    assert all(any("MULTIPLE_NATIVE_CALLBACKS" in flag for flag in b["diagnostic_flags"]) for b in bursts)


def test_every_deviation_has_a_classification(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    from ._helpers import build_passing_fixture

    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    repository.build_records(run.paper_run_id)

    deviations = repository.list_deviation_records(run.paper_run_id, limit=100)
    assert deviations
    assert all(d["classification"] in ("CANDIDATE_EXCLUSION", "CAPTURE_EXCLUSION", "PROTOCOL_DEVIATION") for d in deviations)


def test_runner_rejections_become_protocol_deviations_linked_to_the_attempt(tmp_path):
    """The runner integration (user point 2 of the post-correction request):
    a PaperCampaignRunner rejection persisted to
    <ble_root>/paper_campaign/schedules/<schedule_id>/rejections.jsonl must
    surface as a real, blocking PROTOCOL_DEVIATION carrying protocol_id/
    planned_capture_id/operator_id/detected_at -- without this module ever
    importing PaperCampaignRunner itself (one-way dependency)."""
    import json as _json

    repository, ble_root = _new_repository(tmp_path)
    from ._helpers import build_passing_fixture

    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    rejections_dir = ble_root / "paper_campaign" / "schedules" / "SCHED-X"
    rejections_dir.mkdir(parents=True)
    rejection = {
        "schedule_id": "SCHED-X", "protocol_id": run.protocol_id, "planned_capture_id": "planned-7",
        "reason": "WRONG_CHANNEL,WRONG_UNIT", "attempted": {"channel": 99, "physical_unit_id": "UNIT-B"},
        "operator_id": "OP-7", "rejected_at": "2026-08-05T00:00:00Z",
    }
    (rejections_dir / "rejections.jsonl").write_text(_json.dumps(rejection) + "\n", encoding="utf-8")

    repository.build_records(run.paper_run_id, schedule_id="SCHED-X")
    deviations = repository.list_deviation_records(run.paper_run_id, limit=100)

    runner_deviations = [d for d in deviations if d["planned_capture_id"] == "planned-7"]
    assert {d["deviation_type"] for d in runner_deviations} == {"WRONG_CHANNEL", "WRONG_UNIT"}
    for deviation in runner_deviations:
        assert deviation["classification"] == "PROTOCOL_DEVIATION"
        assert deviation["blocking"] is True
        assert deviation["protocol_id"] == run.protocol_id
        assert deviation["operator_id"] == "OP-7"
        assert deviation["detected_at"] == "2026-08-05T00:00:00Z"


def test_build_records_without_schedule_id_ignores_any_rejection_log(tmp_path):
    """schedule_id is optional -- a run built without it must never read
    rejections.jsonl at all, so existing (pre-runner) campaigns are
    unaffected."""
    import json as _json

    repository, ble_root = _new_repository(tmp_path)
    from ._helpers import build_passing_fixture

    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    rejections_dir = ble_root / "paper_campaign" / "schedules" / "SCHED-UNUSED"
    rejections_dir.mkdir(parents=True)
    (rejections_dir / "rejections.jsonl").write_text(_json.dumps({"schedule_id": "SCHED-UNUSED", "reason": "WRONG_CHANNEL", "planned_capture_id": "p1"}) + "\n", encoding="utf-8")

    repository.build_records(run.paper_run_id)
    deviations = repository.list_deviation_records(run.paper_run_id, limit=100)
    assert not any(d["deviation_type"] == "WRONG_CHANNEL" for d in deviations)
