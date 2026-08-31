from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.evaluation import Evaluator, evaluate_rq1_acquisition_dependence, rq1_report_to_dict


def _predictions(*, n_correct: int, n_wrong: int) -> list[dict]:
    preds = []
    for i in range(n_correct):
        preds.append({"example_id": f"c{i}", "true_label": "A", "predicted_label": "A"})
    for i in range(n_wrong):
        preds.append({"example_id": f"w{i}", "true_label": "A", "predicted_label": "B"})
    return preds


def test_rq1_report_shows_ba_window_lower_than_ba_capture_is_not_assumed_only_computed():
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    # BA_window: near-perfect (optimistic, same-capture windows).
    window_report = evaluator.evaluate_split("VALIDATION", _predictions(n_correct=9, n_wrong=1) + [{"example_id": "bx", "true_label": "B", "predicted_label": "B"}], known_classes)
    # BA_capture: worse (real, capture-disjoint evaluation).
    capture_report = evaluator.evaluate_split("VALIDATION", _predictions(n_correct=5, n_wrong=5) + [{"example_id": "by", "true_label": "B", "predicted_label": "B"}], known_classes)

    report = evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=window_report, capture_report=capture_report)

    assert report.ba_window is not None and report.ba_capture is not None
    assert report.ba_window > report.ba_capture
    assert report.ba_future is None
    assert report.ba_future_status == "NOT_YET_AVAILABLE"
    assert report.delta_dependence == pytest.approx(report.ba_window - report.ba_capture)
    assert report.delta_future is None


def test_rq1_report_uses_balanced_accuracy_not_raw_accuracy():
    # Coherence-audit regression guard (2026-08-19): a real bug had
    # evaluate_rq1_acquisition_dependence() read .accuracy instead of
    # .balanced_accuracy, so "BA" (Balanced Accuracy) silently reported raw
    # accuracy instead -- undetectable by the OTHER tests in this file
    # because their synthetic fixtures don't make the two definitions
    # disagree. This fixture is deliberately imbalanced so they MUST
    # disagree (majority class recall=1.0 hides the minority class's
    # recall=0.0 in raw accuracy, exactly the real keyfobdemo 02 case this
    # bug hid in production).
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    # 9 of 10 A's correct, the only B misclassified as A: accuracy=9/10=0.9,
    # but recall_A=0.9, recall_B=0.0 -> balanced_accuracy=0.45. The two
    # must differ for this test to actually exercise the fix.
    predictions = _predictions(n_correct=9, n_wrong=1) + [{"example_id": "b0", "true_label": "B", "predicted_label": "A"}]
    report_eval = evaluator.evaluate_split("VALIDATION", predictions, known_classes)
    assert report_eval.accuracy != pytest.approx(report_eval.balanced_accuracy)  # fixture sanity check

    report = evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=report_eval, capture_report=report_eval, future_report=report_eval)
    assert report.ba_window == pytest.approx(report_eval.balanced_accuracy)
    assert report.ba_capture == pytest.approx(report_eval.balanced_accuracy)
    assert report.ba_future == pytest.approx(report_eval.balanced_accuracy)
    assert report.ba_window != pytest.approx(report_eval.accuracy)


def test_rq1_report_never_fabricates_ba_future_when_absent():
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    predictions = _predictions(n_correct=3, n_wrong=0) + [{"example_id": "b0", "true_label": "B", "predicted_label": "B"}]
    report_a = evaluator.evaluate_split("VALIDATION", predictions, known_classes)
    report_b = evaluator.evaluate_split("VALIDATION", predictions, known_classes)

    report = evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=report_a, capture_report=report_b, future_report=None)
    as_dict = rq1_report_to_dict(report)
    assert as_dict["ba_future"] is None
    assert as_dict["ba_future_status"] == "NOT_YET_AVAILABLE"
    assert as_dict["ba_future_n_comparable"] is None


def test_rq1_report_uses_a_real_future_report_when_supplied():
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    predictions = _predictions(n_correct=2, n_wrong=0) + [{"example_id": "b0", "true_label": "B", "predicted_label": "B"}]
    same_report = evaluator.evaluate_split("VALIDATION", predictions, known_classes)
    future_report = evaluator.evaluate_split("FUTURE_TEST", predictions, known_classes)

    report = evaluate_rq1_acquisition_dependence(
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=same_report, capture_report=same_report, future_report=future_report,
    )
    assert report.ba_future == future_report.balanced_accuracy
    assert report.ba_future_status == "EXECUTED"
    assert report.ba_future_n_comparable == future_report.n_comparable_to_known_classes
    assert report.delta_future == pytest.approx(report.ba_future - report.ba_capture)
