"""Fase 1 closure item 10: real holdout group mechanism. No real 20-day
campaign data exists yet -- these tests prove the MECHANISM (freeze,
gate FUTURE_TEST reads through the chained access log, never gate TRAIN/
VALIDATION) is real and exercisable, not that real groups exist."""
from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository


def test_freeze_and_list_holdout_groups(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    train = repository.freeze_holdout_groups(dataset_id="DS-1", dataset_version="1", group="TRAIN", physical_unit_ids=["UNIT-A"])
    validation = repository.freeze_holdout_groups(dataset_id="DS-1", dataset_version="1", group="VALIDATION", physical_unit_ids=["UNIT-B"])
    future_test = repository.freeze_holdout_groups(dataset_id="DS-1", dataset_version="1", group="FUTURE_TEST", physical_unit_ids=["UNIT-C"])

    groups = repository.list_holdout_groups("DS-1", "1")
    assert {g.group for g in groups} == {"TRAIN", "VALIDATION", "FUTURE_TEST"}
    assert all(g.group_manifest_sha256 for g in groups)
    assert train.assignment_id != validation.assignment_id != future_test.assignment_id


def test_reading_future_test_is_logged_through_the_chain(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    repository.freeze_holdout_groups(dataset_id="DS-2", dataset_version="1", group="FUTURE_TEST", physical_unit_ids=["UNIT-C"])

    assert repository.list_holdout_access_log() == []
    result = repository.read_group("DS-2", "1", "FUTURE_TEST", actor="researcher1", process="pytest", reason="unit test read")
    assert result is not None
    assert result.group == "FUTURE_TEST"

    entries = repository.list_holdout_access_log()
    assert len(entries) == 1
    assert entries[0].access_type == "READ_GROUP"
    assert entries[0].resource_id == "DS-2__1__FUTURE_TEST"


def test_reading_train_or_validation_is_never_logged(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    repository.freeze_holdout_groups(dataset_id="DS-3", dataset_version="1", group="TRAIN", physical_unit_ids=["UNIT-A"])
    repository.freeze_holdout_groups(dataset_id="DS-3", dataset_version="1", group="VALIDATION", physical_unit_ids=["UNIT-B"])

    repository.read_group("DS-3", "1", "TRAIN", actor="researcher1", process="pytest", reason="preprocessing")
    repository.read_group("DS-3", "1", "VALIDATION", actor="researcher1", process="pytest", reason="threshold selection")

    # Real, honest limitation: only read_group() for FUTURE_TEST logs
    # anything. Calling list_holdout_groups() directly (bypassing
    # read_group) is NOT detected by the chain -- this is the exact
    # limitation documented in contracts/holdout.py's own module docstring.
    assert repository.list_holdout_access_log() == []


def test_paper_campaign_completeness_reports_missing_groups_by_name(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    ble_root = tmp_path / "ble_rffi_studio"
    from ._helpers import build_passing_fixture

    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    run = repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert any("groups_and_holdouts" in finding and "TRAIN" in finding for finding in report.paper_campaign_completeness.findings)

    # Freeze all three groups -- the finding must disappear even though
    # PAPER_CAMPAIGN_PREFLIGHT_PASSED is still unreachable for other reasons
    # (days/pre_post/etc. remain NOT_DOCUMENTED for this synthetic fixture).
    for group in ("TRAIN", "VALIDATION", "FUTURE_TEST"):
        repository.freeze_holdout_groups(dataset_id=dataset_id, dataset_version=dataset_version, group=group)
    report_after = repository.run_preflight(run.paper_run_id)
    assert not any("groups_and_holdouts" in finding for finding in report_after.paper_campaign_completeness.findings)
