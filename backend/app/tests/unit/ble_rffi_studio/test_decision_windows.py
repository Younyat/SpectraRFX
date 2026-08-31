"""Real decision windows (2026-08-08): the gate
decision_window_records.py explicitly deferred to a later phase ("No
score/threshold/predicted_class/model decision field exists on this record
-- that is Fase 3+ territory... minimum_eligible_bursts is the only knob a
future phase needs to turn into a real gate (window_score =
median(burst_scores)), left as a plain parameter, not implemented.").
Implemented against ble_rffi_studio's own real, frozen bundles -- never a
second training/scoring system.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.evaluation import Evaluator
from app.modules.ble_rffi_studio.export import BundleBuilder
from app.modules.ble_rffi_studio.inference import OfflineInferenceService
from app.modules.ble_rffi_studio.inference.decision_windows import aggregate_window_probabilities, decision_window_coverage, group_examples_into_windows
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import make_example, write_synthetic_capture_iq


def test_group_examples_into_windows_groups_by_capture_and_time_slice():
    # sample_rate=1000 sps, window_duration=1s -> 1000 samples/window.
    examples = [
        make_example(example_index=0, physical_unit_id="U1", session_id="S1", capture_id="CAP-A", iq_start_sample=0, iq_end_sample=10).model_copy(update={"sample_rate_sps": 1000}),
        make_example(example_index=1, physical_unit_id="U1", session_id="S1", capture_id="CAP-A", iq_start_sample=500, iq_end_sample=510, source_iq_sha256="s2").model_copy(update={"sample_rate_sps": 1000}),
        make_example(example_index=2, physical_unit_id="U1", session_id="S1", capture_id="CAP-A", iq_start_sample=1200, iq_end_sample=1210, source_iq_sha256="s3").model_copy(update={"sample_rate_sps": 1000}),
        make_example(example_index=3, physical_unit_id="U1", session_id="S1", capture_id="CAP-B", iq_start_sample=0, iq_end_sample=10, source_iq_sha256="s4").model_copy(update={"sample_rate_sps": 1000}),
    ]
    windows = group_examples_into_windows(examples, window_duration_s=1.0)
    assert set(windows.keys()) == {("CAP-A", 0), ("CAP-A", 1), ("CAP-B", 0)}
    assert len(windows[("CAP-A", 0)]) == 2  # samples 0 and 500 land in window 0
    assert len(windows[("CAP-A", 1)]) == 1  # sample 1200 lands in window 1


def test_aggregate_window_probabilities_is_the_per_class_median_renormalized():
    burst_decisions = [
        {"probabilities": {"A": 0.9, "B": 0.1}},
        {"probabilities": {"A": 0.8, "B": 0.2}},
        {"probabilities": {"A": 0.1, "B": 0.9}},  # one outlier burst
    ]
    aggregated = aggregate_window_probabilities(burst_decisions, ["A", "B"])
    # median(0.9, 0.8, 0.1)=0.8, median(0.1, 0.2, 0.9)=0.2 -> already sums to 1.
    assert aggregated["A"] == pytest.approx(0.8)
    assert aggregated["B"] == pytest.approx(0.2)
    assert sum(aggregated.values()) == pytest.approx(1.0)


@pytest.fixture
def trained_bundle(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    training_run = TrainingRun(
        training_run_id="run-dw", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes, min_identified_precision=0.7)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    bundle_builder.build(
        bundle_id="bundle-dw", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    test_example_ids = {a.example_id for a in split.assignments if a.split == "TEST"}
    test_examples = [examples_by_id[eid] for eid in test_example_ids]
    return tmp_path, capture_iq_paths, test_examples


def test_decision_window_coverage_is_the_real_non_abstained_fraction():
    decisions = [
        {"final_decision": "IDENTIFIED"}, {"final_decision": "UNKNOWN"},
        {"final_decision": "INSUFFICIENT_EVIDENCE"}, {"final_decision": "IDENTIFIED"},
    ]
    assert decision_window_coverage(decisions) == pytest.approx(0.75)


def test_decision_window_coverage_is_one_when_nothing_abstained():
    decisions = [{"final_decision": "IDENTIFIED"}, {"final_decision": "UNKNOWN"}]
    assert decision_window_coverage(decisions) == 1.0


def test_decision_window_coverage_rejects_an_empty_list():
    with pytest.raises(ValueError, match="NEED_AT_LEAST_ONE_WINDOW_DECISION"):
        decision_window_coverage([])


def test_run_decision_windows_produces_one_decision_per_window_not_per_burst(trained_bundle):
    tmp_path, capture_iq_paths, test_examples = trained_bundle
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)

    # A window duration far larger than the whole synthetic capture -> every
    # TEST example for a given capture collapses into exactly one window.
    decisions = inference_service.run_decision_windows(bundle_id="bundle-dw", examples=test_examples, window_duration_s=1_000_000.0)

    n_captures = len({e.capture_id for e in test_examples})
    assert len(decisions) == n_captures  # aggregated, not one row per burst
    for d in decisions:
        assert d["final_decision"] in ("IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE")
        assert d["aggregation_rule"] == "MEDIAN_PROBABILITY_PER_CLASS"
        assert d["burst_count"] >= 1
        assert len(d["burst_example_ids"]) == d["burst_count"]


def test_run_decision_windows_abstains_when_below_the_minimum_eligible_bursts(trained_bundle):
    tmp_path, capture_iq_paths, test_examples = trained_bundle
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)

    # An impossibly high minimum forces every window to abstain.
    decisions = inference_service.run_decision_windows(
        bundle_id="bundle-dw", examples=test_examples, window_duration_s=1_000_000.0, minimum_eligible_bursts=10_000,
    )
    assert decisions
    assert all(d["final_decision"] == "INSUFFICIENT_EVIDENCE" for d in decisions)
    assert all(d["abstention_reason"] is not None and "BELOW_MINIMUM_ELIGIBLE_BURSTS" in d["abstention_reason"] for d in decisions)
    assert all(d["aggregated_probabilities"] is None for d in decisions)


def test_run_decision_windows_with_a_tiny_window_duration_approaches_one_window_per_burst(trained_bundle):
    tmp_path, capture_iq_paths, test_examples = trained_bundle
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)

    # 4 samples/window at 4 Msps -- far smaller than the 800-sample spacing
    # write_synthetic_capture_iq gives consecutive bursts, so each burst
    # should land in its own window.
    decisions = inference_service.run_decision_windows(bundle_id="bundle-dw", examples=test_examples, window_duration_s=1e-6)
    assert len(decisions) == len(test_examples)
    assert all(d["burst_count"] == 1 for d in decisions)


def test_run_decision_windows_skips_a_window_duration_too_small_to_span_one_sample(trained_bundle):
    """window_samples rounds to 0 for a window_duration_s far below one
    sample period -- these examples are excluded, never silently given a
    fabricated window_index=0."""
    tmp_path, capture_iq_paths, test_examples = trained_bundle
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)

    decisions = inference_service.run_decision_windows(bundle_id="bundle-dw", examples=test_examples, window_duration_s=1e-9)
    assert decisions == []
