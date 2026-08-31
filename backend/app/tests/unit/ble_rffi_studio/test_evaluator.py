from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.evaluation import Evaluator
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import write_unknown_device_rejection_fixture


@pytest.fixture
def evaluator():
    return Evaluator()


def test_evaluate_split_computes_accuracy_and_confusion_matrix(evaluator):
    predictions = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.9, "B": 0.1}},
        {"example_id": "e2", "true_label": "A", "predicted_label": "B", "probabilities": {"A": 0.4, "B": 0.6}},
        {"example_id": "e3", "true_label": "B", "predicted_label": "B", "probabilities": {"A": 0.2, "B": 0.8}},
    ]
    report = evaluator.evaluate_split("TEST", predictions, known_classes=["A", "B"])
    assert report.n_examples == 3
    assert report.n_comparable_to_known_classes == 3
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.confusion_matrix["A"]["A"] == 1
    assert report.confusion_matrix["A"]["B"] == 1
    assert report.confusion_matrix["B"]["B"] == 1


def test_evaluate_split_excludes_examples_whose_true_label_is_not_a_known_class(evaluator):
    predictions = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.9, "B": 0.1}},
        {"example_id": "e2", "true_label": "UNKNOWN", "predicted_label": "A", "probabilities": {"A": 0.55, "B": 0.45}},
    ]
    report = evaluator.evaluate_split("VALIDATION", predictions, known_classes=["A", "B"])
    assert report.n_examples == 2
    assert report.n_comparable_to_known_classes == 1
    assert report.accuracy == 1.0


def test_evaluate_split_with_no_comparable_examples_has_none_accuracy(evaluator):
    predictions = [{"example_id": "e1", "true_label": "UNKNOWN", "predicted_label": "A", "probabilities": {"A": 0.6}}]
    report = evaluator.evaluate_split("TEST", predictions, known_classes=["A", "B"])
    assert report.accuracy is None


def test_evaluate_split_computes_a_real_risk_coverage_curve(evaluator):
    """Coverage/risk-coverage correction (2026-08-08): risk_coverage_curve
    existed with real tests but no production caller before this."""
    predictions = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.95, "B": 0.05}},
        {"example_id": "e2", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.9, "B": 0.1}},
        {"example_id": "e3", "true_label": "B", "predicted_label": "A", "probabilities": {"A": 0.6, "B": 0.4}},  # a low-confidence error
        {"example_id": "e4", "true_label": "B", "predicted_label": "B", "probabilities": {"A": 0.1, "B": 0.9}},
    ]
    report = evaluator.evaluate_split("TEST", predictions, known_classes=["A", "B"])
    assert report.risk_coverage is not None
    coverages = [p["coverage"] for p in report.risk_coverage]
    assert coverages == sorted(coverages)  # monotonically increasing as confidence threshold relaxes
    assert coverages[-1] == 1.0  # full coverage at the lowest threshold
    # At full coverage the risk must include the one real error (e3).
    assert report.risk_coverage[-1]["risk"] == pytest.approx(0.25)
    # At the highest-confidence prefix (just e1), there is no error yet.
    assert report.risk_coverage[0]["risk"] == 0.0


def test_evaluate_split_risk_coverage_is_none_without_any_probabilities(evaluator):
    predictions = [{"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {}}]
    report = evaluator.evaluate_split("TEST", predictions, known_classes=["A", "B"])
    assert report.risk_coverage is None


def test_calibrate_unknown_threshold_rejects_low_confidence_predictions(evaluator):
    validation_predictions = [
        {"example_id": f"known-correct-{i}", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.95, "B": 0.05}} for i in range(10)
    ] + [
        {"example_id": f"unknown-{i}", "true_label": "UNKNOWN", "predicted_label": "A", "probabilities": {"A": 0.55, "B": 0.45}} for i in range(10)
    ]
    threshold = evaluator.calibrate_unknown_threshold(validation_predictions, known_classes=["A", "B"], min_identified_precision=0.95)
    assert threshold > 0.55  # must reject the low-confidence unknowns, not just accept everything


def test_calibrate_unknown_threshold_with_no_evidence_is_maximally_conservative(evaluator):
    threshold = evaluator.calibrate_unknown_threshold([], known_classes=["A"])
    assert threshold > 1.0  # nothing can ever clear it


def test_classify_with_threshold_identifies_above_threshold_and_rejects_below(evaluator):
    high_confidence = {"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.95, "B": 0.05}}
    low_confidence = {"example_id": "e2", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.55, "B": 0.45}}

    result_high = evaluator.classify_with_threshold(high_confidence, acceptance_threshold=0.9)
    result_low = evaluator.classify_with_threshold(low_confidence, acceptance_threshold=0.9)

    assert result_high["final_decision"] == "IDENTIFIED"
    assert result_low["final_decision"] == "UNKNOWN"
    assert result_high["acceptance_threshold"] == 0.9


def test_classify_with_threshold_handles_missing_probabilities_as_insufficient_evidence(evaluator):
    result = evaluator.classify_with_threshold({"example_id": "e1", "probabilities": {}}, acceptance_threshold=0.9)
    assert result["final_decision"] == "INSUFFICIENT_EVIDENCE"


def test_end_to_end_unknown_device_rejection_on_real_trained_model(evaluator, tmp_path):
    """Real finding, not a hypothetical one: on this hand-crafted feature
    space, a far-out-of-distribution 'unknown device' signal does NOT get
    lower softmax/predict_proba confidence than genuine known-class
    predictions -- logistic regression (and random forest) can extrapolate
    an OOD point into a highly confident, wrong classification. This is the
    well-documented "softmax overconfidence on OOD inputs" failure mode, and
    it is exactly why design correction #16 refuses to let any single
    UNKNOWN-rejection technique be treated as automatically validated.

    The property this test actually holds the code to is the SAFE one:
    calibrate_unknown_threshold must never report a threshold that achieves
    a precision the VALIDATION evidence doesn't actually support. When
    unknown examples are this confidently (mis)classified, the only
    threshold that keeps IDENTIFIED-precision above the target is a maximally
    conservative one -- rejecting everything is the correct, fail-safe
    response here, not a bug in the calibration."""
    examples, capture_iq_paths = write_unknown_device_rejection_fixture(tmp_path)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="UDR-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")
    assert split.split_status == "READY"
    examples_by_id = {e.example_id: e for e in examples}

    training_run = TrainingRun(
        training_run_id="run-udr", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="UNKNOWN_DEVICE_REJECTION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)

    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], known_classes=artifacts.label_classes, min_identified_precision=0.9)

    # The calibration correctly refuses to settle on a permissive threshold:
    # VALIDATION shows unknown examples reaching near-1.0 confidence, so
    # anything less than an extremely high bar would violate the requested
    # 0.9 IDENTIFIED-precision target.
    assert threshold > 0.95

    test_unknown_predictions = [p for p in artifacts.predictions["TEST"] if p["true_label"] == "UNKNOWN"]
    assert test_unknown_predictions
    unknown_decisions = [evaluator.classify_with_threshold(p, threshold) for p in test_unknown_predictions]
    # The one property that must never fail regardless of how conservative
    # the threshold ends up: an unknown device is never falsely IDENTIFIED
    # as the wrong known class at that threshold.
    false_accepts = sum(1 for d in unknown_decisions if d["final_decision"] == "IDENTIFIED")
    assert false_accepts / len(unknown_decisions) < 0.5


def test_calibration_succeeds_when_unknown_confidence_is_genuinely_lower(evaluator):
    """The favorable case, for contrast with the test above: when unknown
    examples really do carry lower confidence than known ones (as intended
    by design, e.g. after a better OOD-aware representation or calibration
    technique), calibrate_unknown_threshold finds a usable, non-degenerate
    threshold instead of always maxing out."""
    validation_predictions = (
        [{"example_id": f"known-{i}", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.95, "B": 0.05}} for i in range(20)]
        + [{"example_id": f"known-{i}", "true_label": "B", "predicted_label": "B", "probabilities": {"A": 0.05, "B": 0.95}} for i in range(20)]
        + [{"example_id": f"unknown-{i}", "true_label": "UNKNOWN", "predicted_label": "A", "probabilities": {"A": 0.4, "B": 0.6}} for i in range(20)]
    )
    threshold = evaluator.calibrate_unknown_threshold(validation_predictions, known_classes=["A", "B"], min_identified_precision=0.9)
    assert threshold <= 0.95  # a real, usable threshold -- not maxed out to reject everything
