"""Fase 4: CNN1D (raw I/Q) and CNN2D (spectrogram) actually training and
converging on the same synthetic multi-unit signal Fase 3's baselines used.
Short epoch counts (this is a correctness/convergence check, not a
performance benchmark) but real backprop, real Adam steps, real held-out
evaluation -- no mocked forward pass.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def synthetic_split(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(
        tmp_path, units=2, sessions_per_unit=3, examples_per_session=16, samples_per_example=800,
        noise_scale=0.15, cfo_step_hz=60_000.0,
    )
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    return dataset, split, examples_by_id, capture_iq_paths


@pytest.mark.parametrize("model_type,representation_profile_id", [("cnn1d", "raw_iq-v1"), ("cnn2d", "spectrogram-v1")])
def test_cnn_trains_and_beats_chance_on_separable_synthetic_data(synthetic_split, model_type, representation_profile_id):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    training_run = TrainingRun(
        training_run_id=f"run-{model_type}", project_id="P1", campaign_id="C1",
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type=model_type,
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id=representation_profile_id,
        random_seed=0,
    )
    service = TrainingService(capture_iq_paths)
    artifacts = service.run_cnn(training_run=training_run, split=split, examples_by_id=examples_by_id, epochs=60)

    assert artifacts.training_run.status == "COMPLETED"
    assert artifacts.metrics["VALIDATION"]["accuracy"] > 0.6
    assert artifacts.metrics["TEST"]["accuracy"] > 0.6
    assert set(artifacts.label_classes) == {"SYN-UNIT-00", "SYN-UNIT-01"}


def test_cnn_refuses_to_train_on_a_not_feasible_split(synthetic_split):
    from app.modules.ble_rffi_studio.contracts import LeakageCheckResult, SplitManifest
    dataset, _, examples_by_id, capture_iq_paths = synthetic_split
    not_feasible = SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        policy="session_disjoint_per_unit", split_status="NOT_FEASIBLE", infeasibility_reason="test",
        leakage_check=LeakageCheckResult(status="NOT_EXECUTED"), created_at="2026-07-26T00:00:00Z",
    )
    training_run = TrainingRun(
        training_run_id="run-bad", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "x", split_manifest_sha256="x",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="cnn1d",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="raw_iq-v1", random_seed=0,
    )
    service = TrainingService(capture_iq_paths)
    with pytest.raises(ValueError):
        service.run_cnn(training_run=training_run, split=not_feasible, examples_by_id=examples_by_id)
