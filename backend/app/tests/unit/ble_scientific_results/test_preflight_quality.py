from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository

from ._helpers import build_passing_fixture, write_quality_report, write_frozen_dataset, write_ready_split, write_capture, write_examples, make_example


def _new_repository(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    return repository, ble_root


def _freeze_and_create_run(repository, *, dataset_id, dataset_version, scientific_task):
    contract = repository.freeze_protocol({"hardware_profile_id": "usrp-b200-e3r04z1b2", "receiver_profile_hash": "rx-hash", "interpretation_matrix_hash": "interp-hash"})
    return repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)


def test_accepted_for_training_passes_quality(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.quality.status == "PASSED"


def test_not_accepted_for_training_blocks_quality(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-QUAL-DS", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-QUAL-CAP", session_id="SCI-QUAL-SESSION", physical_unit_id="UNIT-A")
    examples = [make_example(capture=capture, index=0, physical_unit_id="UNIT-A")]
    write_examples(ble_root, capture, examples)
    example_ids = [e.example_id for e in examples]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 1})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset, gate_decision="NOT_ACCEPTED_FOR_TRAINING")

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    report = repository.run_preflight(run.paper_run_id)

    assert report.quality.status == "BLOCKED"
    assert any("NOT_ACCEPTED_FOR_TRAINING" in finding for finding in report.quality.findings)
    assert report.overall_status == "PREFLIGHT_BLOCKED"


def test_missing_quality_report_blocks_quality(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-QUAL-DS2", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-QUAL-CAP2", session_id="SCI-QUAL-SESSION2", physical_unit_id="UNIT-A")
    examples = [make_example(capture=capture, index=0, physical_unit_id="UNIT-A")]
    write_examples(ble_root, capture, examples)
    example_ids = [e.example_id for e in examples]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 1})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    # Deliberately no write_quality_report() call.

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    report = repository.run_preflight(run.paper_run_id)

    assert report.quality.status == "BLOCKED"
    assert any("never run" in finding for finding in report.quality.findings)
