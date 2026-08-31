"""Fase 3 end-to-end: synthetic multi-unit/multi-session dataset (real data
gave NOT_FEASIBLE in Fase 2, as expected with only one session) -> frozen
dataset -> READY split -> baseline model actually trained and evaluated.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import LeakageCheckResult, SplitManifest, TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.preprocessing import resolve_preprocessing_profile
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def synthetic_split(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=8)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    return dataset, split, examples_by_id, capture_iq_paths


@pytest.mark.parametrize("model_type", ["logistic_regression", "svm_rbf", "random_forest"])
def test_baseline_trains_and_beats_chance_on_separable_synthetic_data(synthetic_split, model_type):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    assert split.split_status == "READY"

    training_run = TrainingRun(
        training_run_id=f"run-{model_type}", project_id="P1", campaign_id="C1",
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type=model_type,
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1",
        random_seed=42,
    )
    service = TrainingService(capture_iq_paths)
    artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)

    assert artifacts.training_run.status == "COMPLETED"
    assert set(artifacts.metrics.keys()) == {"TRAIN", "VALIDATION", "TEST"}
    # 2 physical units -> chance accuracy is 0.5; the synthetic signal is
    # genuinely separable (distinct CFO per unit) so a real classifier should
    # clear that bar on held-out data.
    assert artifacts.metrics["VALIDATION"]["accuracy"] > 0.6
    assert artifacts.metrics["TEST"]["accuracy"] > 0.6
    assert set(artifacts.label_classes) == {"SYN-UNIT-00", "SYN-UNIT-01"}


def test_paper_eq6_7_profile_produces_real_per_burst_provenance_for_every_example(synthetic_split):
    """Point-3 correction (2026-08-08): training under paper-eq6-7-v1 must
    populate TrainingArtifacts.preprocessing_provenance for every example
    actually preprocessed (TRAIN+VALIDATION+TEST), with real, non-trivial
    (phi_b0, f_b) values -- never empty for a profile that genuinely ran
    this step."""
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    profile = resolve_preprocessing_profile("paper-eq6-7-v1")
    training_run = TrainingRun(
        training_run_id="run-eq67", project_id="P1", campaign_id="C1",
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="paper-eq6-7-v1", representation_profile_id="feature_vector-v1",
        random_seed=42,
    )
    service = TrainingService(capture_iq_paths, profile)
    artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)

    all_example_ids = {a.example_id for a in split.assignments}
    assert set(artifacts.preprocessing_provenance.keys()) == all_example_ids
    for provenance in artifacts.preprocessing_provenance.values():
        assert provenance["compensation_status"] == "APPLIED"
        assert provenance["reference_waveform_version"] == "ble-le1m-preamble-aa-reference-v1"
        assert len(provenance["reference_waveform_hash"]) == 64
        assert provenance["sample_rate_sps"] == 4_000_000.0


def test_base_v1_profile_produces_no_provenance_at_all(synthetic_split):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    training_run = TrainingRun(
        training_run_id="run-base", project_id="P1", campaign_id="C1",
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1",
        random_seed=42,
    )
    service = TrainingService(capture_iq_paths)
    artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
    assert artifacts.preprocessing_provenance == {}


def test_baseline_refuses_to_train_on_a_not_feasible_split(synthetic_split):
    dataset, _, examples_by_id, capture_iq_paths = synthetic_split
    not_feasible = SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        policy="session_disjoint_per_unit", split_status="NOT_FEASIBLE", infeasibility_reason="test",
        leakage_check=LeakageCheckResult(status="NOT_EXECUTED"), created_at="2026-07-26T00:00:00Z",
    )
    training_run = TrainingRun(
        training_run_id="run-bad", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "x", split_manifest_sha256="x",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=42,
    )
    service = TrainingService(capture_iq_paths)
    with pytest.raises(ValueError):
        service.run_baseline(training_run=training_run, split=not_feasible, examples_by_id=examples_by_id)


def test_baseline_refuses_to_train_when_leakage_check_failed(synthetic_split):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    leaking = split.model_copy(update={"leakage_check": LeakageCheckResult(status="FAILED", overlapping_keys={"session_id": ["x"]})})
    training_run = TrainingRun(
        training_run_id="run-leak", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "x", split_manifest_sha256=split.split_manifest_sha256 or "x",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=42,
    )
    service = TrainingService(capture_iq_paths)
    with pytest.raises(ValueError):
        service.run_baseline(training_run=training_run, split=leaking, examples_by_id=examples_by_id)
