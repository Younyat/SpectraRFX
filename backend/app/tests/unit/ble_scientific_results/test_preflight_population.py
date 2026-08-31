from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository

from ._helpers import build_passing_fixture, write_capture, write_examples, write_frozen_dataset, write_quality_report, write_ready_split, make_example


def _new_repository(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    return repository, ble_root


def _freeze(repository, **payload_overrides):
    payload = {"hardware_profile_id": "usrp-b200-e3r04z1b2", "receiver_profile_hash": "rx-hash", "interpretation_matrix_hash": "interp-hash"}
    payload.update(payload_overrides)
    return repository.freeze_protocol(payload)


def test_population_counts_are_reported_distinctly_never_merged(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    contract = _freeze(repository)
    run = repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    counts = report.population_separation.population_counts
    assert set(counts.keys()) == {"same_model_enrolled", "cross_model_ble", "ambient_ble", "target_absent_control"}
    # build_passing_fixture alternates enrolled/ambient examples -- both must show up as distinct, non-zero buckets.
    assert counts["same_model_enrolled"] > 0
    assert counts["ambient_ble"] > 0


def test_declared_population_with_zero_observed_examples_blocks(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    # Protocol declares an intervention arm needs cross_model_ble evidence, but the fixture has none.
    contract = _freeze(repository, device_population={"cross_model_ble": 10})
    run = repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.population_separation.status == "BLOCKED"
    assert any("cross_model_ble" in finding for finding in report.population_separation.findings)


def test_cross_model_examples_are_never_counted_as_same_model(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-POP-DS", "1", "TARGET_VS_BACKGROUND"
    capture = write_capture(ble_root, capture_id="SCI-POP-CAP", session_id="SCI-POP-SESSION", physical_unit_id="UNIT-A")
    examples = [
        make_example(capture=capture, index=0, physical_unit_id="UNIT-A"),  # enrolled
        make_example(capture=capture, index=1, physical_unit_id="UNIT-B"),  # a different registered device -- cross-model, never same-model
        make_example(capture=capture, index=2, physical_unit_id=None, capture_purpose="BACKGROUND_GENERAL"),  # ambient
        make_example(capture=capture, index=3, physical_unit_id=None, capture_purpose="BACKGROUND_TARGET_OFF"),  # declared absence control
    ]
    write_examples(ble_root, capture, examples)
    example_ids = [e.example_id for e in examples]
    dataset = write_frozen_dataset(ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"], captures=[capture.capture_id], example_ids=example_ids, class_distribution={"UNIT-A": 1, "UNKNOWN": 3})
    write_ready_split(ble_root, dataset=dataset, scientific_task=task, example_ids=example_ids)
    write_quality_report(ble_root, dataset=dataset)

    contract = _freeze(repository)
    run = repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    report = repository.run_preflight(run.paper_run_id)

    counts = report.population_separation.population_counts
    assert counts == {"same_model_enrolled": 1, "cross_model_ble": 1, "ambient_ble": 1, "target_absent_control": 1}
