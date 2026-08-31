"""Fase 1 closure item A.4: create_run() must snapshot its inputs, not just
reference them by path -- a run's analysis must survive the original
ble_rffi_studio manifests being edited or deleted afterward."""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api import ScientificResultsRepository

from ._helpers import build_passing_fixture


def _freeze_and_create_run(repository, *, dataset_id, dataset_version, scientific_task):
    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    return repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)


def test_create_run_snapshots_dataset_split_quality_and_capture_manifests(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    snapshot_dir = tmp_path / "sci_results" / run.paper_run_id / "01_inputs" / "input_snapshot"
    assert (snapshot_dir / "dataset_manifest.json").is_file()
    assert (snapshot_dir / "split_manifest.json").is_file()
    assert (snapshot_dir / "quality_manifest.json").is_file()
    assert (snapshot_dir / "captures" / "SCI-TEST-CAP-01.json").is_file()
    assert (snapshot_dir / "evidence" / "SCI-TEST-CAP-01" / "examples.jsonl").is_file()

    index = json.loads((snapshot_dir / "input_artifact_index.json").read_text(encoding="utf-8"))
    artifact_types = {entry["artifact_type"] for entry in index["entries"]}
    assert {"dataset_manifest", "split_manifest", "quality_manifest", "capture_manifest", "evidence_manifest", "iq_reference"} <= artifact_types

    iq_entries = [entry for entry in index["entries"] if entry["artifact_type"] == "iq_reference"]
    assert len(iq_entries) == 1
    # Real I/Q is referenced, never copied.
    assert iq_entries[0]["snapshot_path"] is None
    assert iq_entries[0]["sha256"]
    assert iq_entries[0]["size_bytes"] > 0


def test_run_survives_deletion_of_original_ble_rffi_studio_dataset_manifest(tmp_path):
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    # Delete the ORIGINAL dataset manifest -- the run's own snapshot copy
    # must remain intact and readable.
    (ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json").unlink()

    snapshot_path = tmp_path / "sci_results" / run.paper_run_id / "01_inputs" / "input_snapshot" / "dataset_manifest.json"
    assert snapshot_path.is_file()
    snapshot_content = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_content["dataset_id"] == dataset_id
