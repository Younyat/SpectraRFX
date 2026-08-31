"""RQ2's 4th branch (2026-08-08): a simple, frozen morphological/coarse
time-frequency nearest-centroid reference baseline -- the branch the audit
found genuinely missing alongside the three already-implemented ones.
Deliberately NOT E0 (a region/activity detector, not a device-fingerprinting
baseline) -- see frozen_reference_baseline.py and
morphological_coarse_tf_representation.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.preprocessing.representation_profiles import morphological_coarse_tf_representation
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService
from app.modules.ble_rffi_studio.training.frozen_reference_baseline import FrozenReferenceBaselineTrainer

from ._helpers import write_synthetic_capture_iq

SAMPLE_RATE = 4_000_000.0


def test_morphological_representation_is_l2_normalized():
    rng = np.random.default_rng(0)
    window = (rng.standard_normal(500) + 1j * rng.standard_normal(500)).astype(np.complex64) * 5.0
    vector = morphological_coarse_tf_representation(window, SAMPLE_RATE)
    assert vector.ndim == 1
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-6)


def test_morphological_representation_is_gain_invariant():
    """The whole point of L2-normalizing a linear (not dB) magnitude
    spectrum: two windows with identical shape but different amplitude must
    map to (nearly) the same vector."""
    rng = np.random.default_rng(1)
    window = (rng.standard_normal(500) + 1j * rng.standard_normal(500)).astype(np.complex64)
    quiet = morphological_coarse_tf_representation(window * 0.1, SAMPLE_RATE)
    loud = morphological_coarse_tf_representation(window * 10.0, SAMPLE_RATE)
    np.testing.assert_allclose(quiet, loud, atol=1e-5)


def test_frozen_trainer_never_iterates_centroid_is_exact_train_mean():
    X_train = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]])
    y_train = ["A", "A", "B", "B"]
    trainer = FrozenReferenceBaselineTrainer()
    model = trainer.build("frozen_morphological_baseline", random_seed=0)
    trainer.fit(model, X_train, y_train)
    assert trainer.classes(model) == ["A", "B"]
    np.testing.assert_array_equal(model.centroids, np.array([[1.0, 0.0], [0.0, 1.0]]))


def test_frozen_trainer_predict_proba_favors_the_nearest_centroid():
    X_train = np.array([[1.0, 0.0], [0.0, 1.0]])
    y_train = ["A", "B"]
    trainer = FrozenReferenceBaselineTrainer()
    model = trainer.build("frozen_morphological_baseline", random_seed=0)
    trainer.fit(model, X_train, y_train)

    proba = trainer.predict_proba(model, np.array([[0.9, 0.1]]))
    classes = trainer.classes(model)
    assert classes[np.argmax(proba[0])] == "A"
    assert proba[0].sum() == pytest.approx(1.0)


def test_frozen_trainer_rejects_an_unsupported_model_type():
    with pytest.raises(ValueError, match="UNSUPPORTED_FROZEN_REFERENCE_MODEL_TYPE"):
        FrozenReferenceBaselineTrainer().build("random_forest", random_seed=0)


@pytest.fixture
def synthetic_split(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=8)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    return dataset, split, examples_by_id, capture_iq_paths


def test_run_frozen_reference_baseline_trains_and_beats_chance_on_separable_synthetic_data(synthetic_split):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    assert split.split_status == "READY"

    training_run = TrainingRun(
        training_run_id="run-frozen", project_id="P1", campaign_id="C1",
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="frozen_morphological_baseline",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1",
        representation_profile_id="morphological_coarse_tf-v1", random_seed=42,
    )
    service = TrainingService(capture_iq_paths)
    artifacts = service.run_frozen_reference_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)

    assert artifacts.training_run.status == "COMPLETED"
    assert artifacts.scaler is None  # deliberately unscaled -- see run_frozen_reference_baseline docstring
    # 2 physical units, distinct CFO per unit -> a CFO shift moves which
    # coarse frequency bin carries energy, so even this simple frozen
    # baseline should clear chance (0.5) on held-out data.
    assert artifacts.metrics["VALIDATION"]["accuracy"] > 0.6
    assert artifacts.metrics["TEST"]["accuracy"] > 0.6


def test_run_frozen_reference_baseline_refuses_a_non_ready_split(synthetic_split):
    dataset, split, examples_by_id, capture_iq_paths = synthetic_split
    not_ready = split.model_copy(update={"split_status": "NOT_FEASIBLE"})
    training_run = TrainingRun(
        training_run_id="run-bad", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="frozen_morphological_baseline",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1",
        representation_profile_id="morphological_coarse_tf-v1", random_seed=42,
    )
    with pytest.raises(ValueError, match="CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY"):
        TrainingService(capture_iq_paths).run_frozen_reference_baseline(training_run=training_run, split=not_ready, examples_by_id=examples_by_id)
