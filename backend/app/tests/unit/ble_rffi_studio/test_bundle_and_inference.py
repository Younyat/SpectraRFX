"""Fase 5 end-to-end: train -> evaluate -> calibrate -> export a real bundle
to disk -> reload it in a FRESH OfflineInferenceService (simulating a
completely separate process, as a real offline inference deployment would
be) -> score held-out TEST examples purely from the bundle's own files.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.evaluation import Evaluator
from app.modules.ble_rffi_studio.export import BundleBuilder
from app.modules.ble_rffi_studio.inference import OfflineInferenceService
from app.modules.ble_rffi_studio.preprocessing import resolve_preprocessing_profile
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def trained_artifacts(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    training_run = TrainingRun(
        training_run_id="run-1", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
    return dataset, split, artifacts, examples_by_id, capture_iq_paths


def test_bundle_contains_every_required_file_with_a_real_hash(trained_artifacts, tmp_path):
    from app.modules.ble_rffi_studio.contracts import REQUIRED_BUNDLE_FILES

    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION", "min_identified_precision": 0.9}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-1", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.6},
        model_card_text="# Test model\nSynthetic demonstration only.", code_reference={"module": "ble_rffi_studio"},
        created_at="2026-07-26T00:00:00Z",
    )

    assert set(manifest.artifact_hashes.keys()) == set(REQUIRED_BUNDLE_FILES)
    assert all(len(h) == 64 for h in manifest.artifact_hashes.values())  # real sha256 hex digests
    assert manifest.bundle_sha256 is not None


def test_bundle_is_evaluated_not_auto_approved_when_criteria_are_met(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-1", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.5},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "EVALUATED"  # never APPROVED_FOR_LIVE_PILOT straight out of build()
    assert reasons == []


def test_bundle_is_rejected_when_criteria_are_not_met(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.99}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-2", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 1.1},  # unreachable by construction (accuracy is capped at 1.0)
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "REJECTED"
    assert reasons


def test_approve_for_live_pilot_requires_evaluated_status_first(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.99}
    bundle_builder = BundleBuilder(tmp_path / "bundles")
    rejected_manifest, _ = bundle_builder.build(
        bundle_id="bundle-3", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 1.1},  # unreachable by construction (accuracy is capped at 1.0)
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert rejected_manifest.approval_status == "REJECTED"
    with pytest.raises(ValueError):
        bundle_builder.approve_for_live_pilot(rejected_manifest)


def test_bundle_is_test_not_executed_not_rejected_when_only_gap_is_a_missing_test_evaluation(trained_artifacts, tmp_path):
    # Real report: a non-recommended prepare_and_train() candidate never has
    # its own TEST evaluation (TEST stays reserved for the one selected
    # model) -- exporting it anyway must not read as REJECTED, which implies
    # invalid data or failed training. Every other gate passes here; the
    # ONLY missing piece is TEST, so this must land on the distinct
    # TEST_NOT_EXECUTED status instead.
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {
        name: evaluator.evaluate_split(name, preds, artifacts.label_classes)
        for name, preds in artifacts.predictions.items() if name != "TEST"
    }
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-no-test-eval", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.5},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "TEST_NOT_EXECUTED"
    assert manifest.operational_use == "FORBIDDEN"
    assert any("TEST_NOT_EXECUTED" in reason for reason in reasons)

    # And approval must still refuse it, with a message that points at the
    # real gap (no TEST eval) rather than a generic "not evaluated" error.
    with pytest.raises(ValueError, match="CANNOT_APPROVE_A_BUNDLE_WITH_NO_TEST_EVALUATION"):
        bundle_builder.approve_for_live_pilot(manifest)


def test_offline_inference_reloads_a_fresh_bundle_and_scores_unseen_examples(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes, min_identified_precision=0.7)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, _ = bundle_builder.build(
        bundle_id="bundle-inference", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.5},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )

    test_example_ids = {a.example_id for a in split.assignments if a.split == "TEST"}
    test_examples = [examples_by_id[eid] for eid in test_example_ids]

    # A brand-new service instance, as a real separate offline-inference
    # process would be -- nothing here reuses the in-memory trained model.
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    decisions = inference_service.run(bundle_id="bundle-inference", examples=test_examples)

    assert len(decisions) == len(test_examples)
    assert all(d["final_decision"] in ("IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE") for d in decisions)
    correct = sum(1 for d, e in zip(decisions, test_examples) if d["final_decision"] == "IDENTIFIED" and d["predicted_class"] == e.physical_unit_id)
    assert correct / len(test_examples) > 0.5


def test_bundle_persists_the_resolved_preprocessing_flags_not_just_the_bare_id(trained_artifacts, tmp_path):
    """Preprocessing-registry correction (2026-08-08): preprocessing_config.json
    must be self-sufficient -- the exact flags a bundle was trained with,
    not only a profile_id string a consumer would have to go re-read source
    code to resolve."""
    import json

    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    bundle_builder.build(
        bundle_id="bundle-flags", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    config = json.loads((tmp_path / "bundles" / "bundle-flags" / "preprocessing_config.json").read_text(encoding="utf-8"))
    assert config["base_preprocessing_profile_id"] == "base-v1"
    assert config["resolved_flags"]["cfo_correction"] is False
    assert config["resolved_flags"]["phase_normalization"] is False


def test_bundle_trained_with_a_non_identity_profile_is_scored_with_that_same_profile_at_inference(tmp_path):
    """The real, load-bearing check for the train/inference mismatch this
    session's audit found: run()/run_live() used to always default to
    identity preprocessing regardless of what the bundle was actually
    trained with. A bundle trained with cfo-compensated-v1 must be scored
    with cfo-compensated-v1 at inference time, with the caller changing
    nothing."""
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    dataset = DatasetBuilder(tmp_path / "datasets").freeze(
        DatasetBuilder(tmp_path / "datasets").build_draft(dataset_id="SYN-DS-2", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    )
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    training_run = TrainingRun(
        training_run_id="run-cfo", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="cfo-compensated-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths, resolve_preprocessing_profile("cfo-compensated-v1")).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)

    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    bundle_builder.build(
        bundle_id="bundle-cfo", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )

    test_example_ids = {a.example_id for a in split.assignments if a.split == "TEST"}
    test_examples = [examples_by_id[eid] for eid in test_example_ids]

    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    loaded = inference_service._load_bundle("bundle-cfo")
    assert loaded["base_profile"].profile_id == "cfo-compensated-v1"
    assert loaded["base_profile"].cfo_correction is True

    # And it must actually be usable end to end with no caller-side base_profile.
    decisions = inference_service.run(bundle_id="bundle-cfo", examples=test_examples)
    assert len(decisions) == len(test_examples)


def test_run_with_provenance_binds_a_prediction_to_its_real_bundle_and_source_iq_hashes(trained_artifacts, tmp_path):
    """Inference-provenance correction (2026-08-08): the audit's own
    "provenance chain terminates at the model" finding -- a prediction must
    be bound, in a real artifact, to the exact bundle content hash and
    source IQ hash that produced it."""
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, _ = bundle_builder.build(
        bundle_id="bundle-prov", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    test_examples = [examples_by_id[a.example_id] for a in split.assignments if a.split == "TEST"]

    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    fake_iq_hashes = {e.capture_id: f"sha-{e.capture_id}" for e in test_examples}
    result = inference_service.run_with_provenance(
        bundle_id="bundle-prov", examples=test_examples, inference_run_id="INFER-TEST-1", capture_iq_sha256_by_id=fake_iq_hashes,
    )

    assert result["bundle_id"] == "bundle-prov"
    assert result["bundle_sha256"] == manifest.bundle_sha256
    assert result["prediction_count"] == len(test_examples)
    assert len(result["decisions"]) == len(test_examples)
    assert set(result["source_capture_ids"]) == {e.capture_id for e in test_examples}
    for capture_id in result["source_capture_ids"]:
        assert result["source_iq_sha256_by_capture_id"][capture_id] == fake_iq_hashes[capture_id]
    assert result["created_at"]


def test_run_with_provenance_records_none_for_an_unsupplied_iq_hash_rather_than_fabricating_one(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}
    BundleBuilder(tmp_path / "bundles").build(
        bundle_id="bundle-no-hash", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    test_examples = [examples_by_id[a.example_id] for a in split.assignments if a.split == "TEST"]
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    result = inference_service.run_with_provenance(bundle_id="bundle-no-hash", examples=test_examples, inference_run_id="INFER-TEST-2")
    assert all(value is None for value in result["source_iq_sha256_by_capture_id"].values())


def test_paper_eq6_7_bundle_carries_real_provenance_through_to_inference(tmp_path):
    """Point-3 correction (2026-08-08): TRAIN and inference run the exact
    same apply_base_preprocessing_with_provenance -- a bundle trained under
    paper-eq6-7-v1 must produce real (phi_b0, f_b) provenance at inference
    time too, not just during training."""
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    dataset = DatasetBuilder(tmp_path / "datasets").freeze(
        DatasetBuilder(tmp_path / "datasets").build_draft(dataset_id="SYN-DS-EQ67", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    )
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    training_run = TrainingRun(
        training_run_id="run-eq67-bundle", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="paper-eq6-7-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths, resolve_preprocessing_profile("paper-eq6-7-v1")).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
    assert artifacts.preprocessing_provenance  # real provenance produced at train time

    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}
    BundleBuilder(tmp_path / "bundles").build(
        bundle_id="bundle-eq67", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )

    test_examples = [examples_by_id[a.example_id] for a in split.assignments if a.split == "TEST"]
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    decisions = inference_service.run(bundle_id="bundle-eq67", examples=test_examples)
    assert decisions
    for decision in decisions:
        assert "preprocessing_provenance" in decision
        assert decision["preprocessing_provenance"]["compensation_status"] == "APPLIED"


def test_offline_inference_raises_for_an_unknown_bundle_id(tmp_path):
    inference_service = OfflineInferenceService(tmp_path / "bundles", {})
    with pytest.raises(Exception):
        inference_service.run(bundle_id="does-not-exist", examples=[])


def test_bundle_is_rejected_with_training_data_single_class_when_label_classes_has_only_one_entry(trained_artifacts, tmp_path):
    # Defense in depth: SplitBuilder._finalize()'s own >=2-TRAIN-classes gate
    # should make a real single-class training run unreachable -- this
    # exercises the bundle-level guard directly (the reviewer's explicit
    # demand: a single-class bundle must never be exportable), independent
    # of whether that upstream gate is ever bypassed or changed.
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.9}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-single-class", training_run=artifacts.training_run, model=artifacts.model,
        label_classes=[artifacts.label_classes[0]],  # only one class, as if TRAIN had never had a second one
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.0},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "REJECTED"
    assert any("TRAINING_DATA_SINGLE_CLASS" in reason for reason in reasons)


def test_bundle_is_rejected_with_background_class_missing_for_target_vs_background_without_it(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.9}
    target_vs_background_run = artifacts.training_run.model_copy(update={"scientific_task": "TARGET_VS_BACKGROUND"})

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-no-background", training_run=target_vs_background_run, model=artifacts.model,
        label_classes=["TARGET_DEVICE"],  # declares TARGET_VS_BACKGROUND but never actually had a background class
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.0},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "REJECTED"
    assert any("BACKGROUND_CLASS_MISSING" in reason for reason in reasons)


def test_bundle_is_rejected_with_dataset_counter_mismatch_when_split_references_examples_outside_the_frozen_dataset(trained_artifacts, tmp_path):
    # The reviewer's explicit "los contadores... deben proceder exactamente
    # del DatasetManifest congelado" requirement: a split referencing an
    # example_id the frozen dataset never selected must never export.
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.9}

    tampered_assignment = split.assignments[0].model_copy(update={"example_id": "ex-not-in-frozen-dataset"})
    tampered_split = split.model_copy(update={"assignments": [tampered_assignment, *split.assignments[1:]]})

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-counter-mismatch", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=tampered_split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.0},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "REJECTED"
    assert any("DATASET_COUNTER_MISMATCH" in reason for reason in reasons)
