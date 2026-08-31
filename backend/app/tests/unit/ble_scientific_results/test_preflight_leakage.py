from __future__ import annotations

from app.modules.ble_scientific_results.api import ScientificResultsRepository

from ._helpers import build_passing_fixture, write_frozen_dataset, write_not_feasible_split, write_quality_report


def _new_repository(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    return repository, ble_root


def _freeze_and_create_run(repository, *, dataset_id, dataset_version, scientific_task):
    contract = repository.freeze_protocol({
        "hardware_profile_id": "usrp-b200-e3r04z1b2", "receiver_profile_hash": "rx-hash", "interpretation_matrix_hash": "interp-hash",
    })
    return repository.create_run(
        protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="CAMPAIGN-1",
        dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task,
    )


def test_ready_leakage_passed_split_passes_preflight(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.leakage.status == "PASSED"
    # Tier 1 (dataset-structural) passes; tier 2 (paper-campaign) is always
    # BLOCKED against this fixture (no day/pre-post/intervention/content-
    # variant metadata exists anywhere yet), so overall caps at tier 1.
    assert report.overall_status == "DATASET_STRUCTURAL_PREFLIGHT_PASSED"


def test_not_feasible_split_blocks_preflight_with_leakage_finding(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = "SCI-LEAK-DS", "1", "TARGET_VS_BACKGROUND"
    dataset = write_frozen_dataset(
        ble_root, dataset_id=dataset_id, dataset_version=dataset_version, physical_units=["UNIT-A"],
        captures=[], example_ids=[], class_distribution={"UNIT-A": 0, "UNKNOWN": 0},
    )
    write_not_feasible_split(ble_root, dataset=dataset, scientific_task=task)
    write_quality_report(ble_root, dataset=dataset)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.leakage.status == "BLOCKED"
    assert any("NOT_FEASIBLE" in finding or "leakage" in finding.lower() for finding in report.leakage.findings)
    assert report.overall_status == "PREFLIGHT_BLOCKED"
