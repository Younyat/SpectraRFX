from __future__ import annotations

import json

from app.modules.ble_scientific_results.api import ScientificResultsRepository

from ._helpers import build_passing_fixture


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


def test_clean_fixture_passes_integrity(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.integrity.status == "PASSED"
    assert report.integrity.checked_capture_count == 1


def test_tampered_dataset_manifest_hash_blocks_integrity(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)

    # Simulate a corrupted/tampered dataset file: someone changed the
    # composition after freezing without going through DatasetBuilder, so
    # the stored hash no longer matches the content.
    dataset_path = ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload["class_distribution"]["UNKNOWN"] += 1000
    dataset_path.write_text(json.dumps(payload), encoding="utf-8")

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    report = repository.run_preflight(run.paper_run_id)

    assert report.integrity.status == "BLOCKED"
    assert any("hash mismatch" in finding for finding in report.integrity.findings)
    assert report.overall_status == "PREFLIGHT_BLOCKED"


def test_missing_iq_file_blocks_integrity(tmp_path):
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)

    legacy_capture_root = ble_root.parent / "ble" / "iq_captures"
    for path in legacy_capture_root.glob("**/*.cf32"):
        path.unlink()

    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)
    report = repository.run_preflight(run.paper_run_id)

    assert report.integrity.status == "BLOCKED"
    assert any("does not exist on disk" in finding for finding in report.integrity.findings)
