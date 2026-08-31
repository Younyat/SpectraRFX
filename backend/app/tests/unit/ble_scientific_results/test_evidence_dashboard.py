"""Real, in-platform paper-support dashboard (2026-08-16):
get_evidence_dashboard_summary() computes NO new science -- it only
cross-references already-real getters (list_runs()/get_rq1_..._report()/
get_rq2_..._report()/get_latest_scientist_decisions()/
PhysicalDeviceRegistry.list_physical_units()), same convention as
get_experiment_health_summary(). These tests exercise that cross-reference,
not any underlying statistic.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.registry.physical_device_registry import PhysicalDeviceRegistry
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

from ._helpers import write_capture


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_run(repo, *, paper_run_id: str, dataset_id: str, scientific_task: str) -> None:
    run_dir = repo.root / paper_run_id
    (run_dir / "06_statistics").mkdir(parents=True, exist_ok=True)
    run_payload = {
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": paper_run_id,
        "campaign_id": "TEST-CAMPAIGN", "protocol_id": "PROTO-1", "protocol_version": 1,
        "dataset_id": dataset_id, "dataset_version": "v1", "scientific_task": scientific_task,
        "analysis_code_commit": "deadbeef", "analysis_environment_hash": "envhash",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }
    (run_dir / "run.json").write_text(json.dumps(run_payload), encoding="utf-8")


def _write_rq1_report(repo, *, paper_run_id: str, ba_window: float, ba_capture: float) -> None:
    payload = {
        "schema_version": "ble-scientific-results-rq1-acquisition-dependence-v1",
        "ba_window": ba_window, "ba_capture": ba_capture, "delta_dependence": ba_window - ba_capture,
        "ba_future": None, "ba_future_status": "NOT_YET_AVAILABLE",
        "confusion_matrix_capture": {"UNIT-A": {"UNIT-A": 9, "UNIT-B": 1}, "UNIT-B": {"UNIT-A": 0, "UNIT-B": 10}},
        "generated_at": "2026-08-01T00:00:00Z",
    }
    (repo.root / paper_run_id / "06_statistics" / "rq1_acquisition_dependence_report.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_rq2_report(repo, *, paper_run_id: str, primary_training_run_id: str) -> None:
    payload = {
        "schema_version": "ble-scientific-results-rq2-representation-comparison-v1",
        "branches": [
            {"branch": "engineered_rf", "analysis_role": "PRIMARY", "model_type": "random_forest",
             "training_run_id": primary_training_run_id, "balanced_accuracy": 0.9, "macro_f1": 0.85},
            {"branch": "raw_iq", "analysis_role": "UNSELECTED", "model_type": "cnn1d",
             "training_run_id": f"{primary_training_run_id}-cnn1d", "balanced_accuracy": 0.5, "macro_f1": 0.4},
        ],
        "generated_at": "2026-08-01T00:00:00Z",
    }
    (repo.root / paper_run_id / "06_statistics" / "rq2_representation_comparison_report.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_training_run_test_evaluation(repo, *, training_run_id: str) -> None:
    payload = {"TEST": {"accuracy": 0.88, "balanced_accuracy": 0.86, "macro_f1": 0.83, "confusion_matrix": {"UNIT-A": {"UNIT-A": 8, "UNIT-B": 2}, "UNIT-B": {"UNIT-A": 1, "UNIT-B": 9}}}}
    run_dir = repo.ble_root / "training_runs" / training_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evaluation_report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_evidence_dashboard_is_empty_and_honest_on_an_empty_repository(tmp_path):
    repo = _repo(tmp_path)
    summary = repo.get_evidence_dashboard_summary()
    assert summary["schema_version"] == "ble-scientific-results-evidence-dashboard-v1"
    assert summary["closed_set"] is None
    assert summary["per_unit_auxiliary"] == []
    assert summary["rq3"]["sample_size_decision"] is None
    assert summary["rq3"]["campaign_progress"] == {"total_captures": 0, "captures_with_rq3_metadata": 0, "declared_by_unit": {}}
    assert summary["rq4"]["physical_units"] == []
    assert summary["rq4"]["status"] == "DATA_NOT_AVAILABLE"


def test_evidence_dashboard_discriminates_closed_set_from_per_unit_runs_by_scientific_task(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo, paper_run_id="RUN-CLOSED", dataset_id="IDENTITY-XYZ", scientific_task="MULTI_DEVICE_CLASSIFICATION")
    _write_rq1_report(repo, paper_run_id="RUN-CLOSED", ba_window=0.97, ba_capture=0.75)
    _write_rq2_report(repo, paper_run_id="RUN-CLOSED", primary_training_run_id="TRAIN-CLOSED-rf")
    _write_training_run_test_evaluation(repo, training_run_id="TRAIN-CLOSED-rf")

    _write_run(repo, paper_run_id="RUN-UNIT-A", dataset_id="UNIT-A-TVB", scientific_task="TARGET_VS_BACKGROUND")
    _write_rq1_report(repo, paper_run_id="RUN-UNIT-A", ba_window=0.94, ba_capture=0.98)
    _write_rq2_report(repo, paper_run_id="RUN-UNIT-A", primary_training_run_id="TRAIN-UNIT-A-rf")

    summary = repo.get_evidence_dashboard_summary()

    assert summary["closed_set"]["paper_run_id"] == "RUN-CLOSED"
    assert summary["closed_set"]["dataset_id"] == "IDENTITY-XYZ"
    assert summary["closed_set"]["rq1"]["delta_dependence"] == 0.97 - 0.75
    assert summary["closed_set"]["primary_branch"] == "engineered_rf"
    assert summary["closed_set"]["primary_training_run_id"] == "TRAIN-CLOSED-rf"
    assert summary["closed_set"]["primary_test"]["balanced_accuracy"] == 0.86

    assert len(summary["per_unit_auxiliary"]) == 1
    assert summary["per_unit_auxiliary"][0]["paper_run_id"] == "RUN-UNIT-A"
    assert summary["per_unit_auxiliary"][0]["rq1"]["ba_capture"] == 0.98


def test_evidence_dashboard_rq3_progress_counts_real_declared_captures_per_unit(tmp_path):
    repo = _repo(tmp_path)
    cap1 = write_capture(repo.ble_root, capture_id="CAP-1", session_id="S1", physical_unit_id="UNIT-A")
    cap1 = cap1.model_copy(update={"day_id": "2026-08-20", "pre_or_post": "PRE", "intervention_arm": "RESET", "target_reference_id": "UNIT-A"})
    (repo.ble_root / "captures" / "CAP-1.json").write_text(json.dumps(cap1.model_dump(mode="json")), encoding="utf-8")

    cap2 = write_capture(repo.ble_root, capture_id="CAP-2", session_id="S1", physical_unit_id="UNIT-A")
    cap2 = cap2.model_copy(update={"day_id": "2026-08-20", "pre_or_post": "POST", "intervention_arm": "RESET", "target_reference_id": "UNIT-A"})
    (repo.ble_root / "captures" / "CAP-2.json").write_text(json.dumps(cap2.model_dump(mode="json")), encoding="utf-8")

    # A real capture with no RQ3 metadata declared at all -- must not count.
    write_capture(repo.ble_root, capture_id="CAP-3", session_id="S2", physical_unit_id="UNIT-B")

    summary = repo.get_evidence_dashboard_summary()
    progress = summary["rq3"]["campaign_progress"]
    assert progress["total_captures"] == 3
    assert progress["captures_with_rq3_metadata"] == 2
    assert progress["declared_by_unit"]["UNIT-A"] == {"RESET": 2, "CONTROL": 0}


def test_evidence_dashboard_rq3_sample_size_decision_is_surfaced_verbatim(tmp_path):
    repo = _repo(tmp_path)
    repo.record_scientist_decision(
        field_id="rq3_sample_size", selected_value={"total_valid_pairs": 80},
        rationale="PROSPECTIVE_BALANCED_WITHIN_DEVICE_CROSSOVER", evidence_used="test evidence",
    )
    summary = repo.get_evidence_dashboard_summary()
    assert summary["rq3"]["sample_size_decision"]["selected_value"]["total_valid_pairs"] == 80
    assert summary["rq3"]["sample_size_decision"]["rationale"] == "PROSPECTIVE_BALANCED_WITHIN_DEVICE_CROSSOVER"


def test_evidence_dashboard_rq4_status_flips_when_a_unit_is_eligible(tmp_path):
    repo = _repo(tmp_path)
    registry = PhysicalDeviceRegistry(repo.ble_root / "registry")
    registry.register_physical_unit(
        physical_unit_id="UNIT-A", project_id="PROJ", device_family="TEST-FAMILY",
        operator_declaration_id="decl-1", first_registered_at="2026-08-01T00:00:00Z",
    )
    summary = repo.get_evidence_dashboard_summary()
    assert summary["rq4"]["status"] == "DATA_NOT_AVAILABLE"
    assert summary["rq4"]["physical_units"][0]["rq4_eligibility"] == "NOT_ELIGIBLE"

    registry.set_rq4_eligibility("UNIT-A", eligible=True, reason="verified controlled firmware variant")
    summary = repo.get_evidence_dashboard_summary()
    assert summary["rq4"]["status"] == "ELIGIBLE_UNITS_PRESENT"
    assert summary["rq4"]["physical_units"][0]["rq4_eligibility_reason"] == "verified controlled firmware variant"
