"""Protocol-freeze close-out (2026-08-09): confirms every one of the 11
paper-required statistical methods is reachable through a single real,
callable entrypoint -- run_confirmatory_statistical_plan() -- either
EXECUTED with a real result when real data is supplied, or honestly
SKIPPED_NO_DATA (never a fabricated number) when it isn't.
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.evaluation import Evaluator
from app.modules.ble_scientific_results.statistics.confirmatory_analysis_runner import (
    confirmatory_statistical_plan_to_dict,
    run_confirmatory_statistical_plan,
)


def test_every_method_is_skipped_no_data_with_no_input_and_nothing_is_fabricated():
    report = run_confirmatory_statistical_plan()
    for field_name in report.__dataclass_fields__:
        result = getattr(report, field_name)
        assert result.status == "SKIPPED_NO_DATA", field_name
        assert result.value is None
        assert result.detail

    as_dict = confirmatory_statistical_plan_to_dict(report)
    assert all(entry["status"] == "SKIPPED_NO_DATA" for entry in as_dict.values())


def test_supplying_real_split_evaluation_report_executes_balanced_accuracy_macro_f1_and_risk_coverage():
    evaluator = Evaluator()
    predictions = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "probabilities": {"A": 0.9, "B": 0.1}},
        {"example_id": "e2", "true_label": "B", "predicted_label": "B", "probabilities": {"A": 0.2, "B": 0.8}},
    ]
    split_report = evaluator.evaluate_split("VALIDATION", predictions, ["A", "B"])

    report = run_confirmatory_statistical_plan(split_evaluation_report=split_report)
    assert report.balanced_accuracy.status == "EXECUTED"
    assert report.balanced_accuracy.value == split_report.balanced_accuracy
    assert report.macro_f1_and_classwise_recall.status == "EXECUTED"
    assert report.risk_coverage.status == "EXECUTED"


def test_supplying_real_rq3_pairs_executes_the_permutation_test_and_feeds_holm():
    device_day_values = {"D1": [0.9, 0.5], "D2": [0.8, 0.4]}
    device_day_is_reset = {"D1": [True, False], "D2": [True, False]}

    report = run_confirmatory_statistical_plan(rq3_device_day_values=device_day_values, rq3_device_day_is_reset=device_day_is_reset)
    assert report.rq3_within_device_permutation_test.status == "EXECUTED"
    assert 0.0 <= report.rq3_within_device_permutation_test.value.p_value <= 1.0
    assert report.holm_correction.status == "EXECUTED"


def test_supplying_real_rq4_paired_scores_executes_the_paired_comparison():
    report = run_confirmatory_statistical_plan(rq4_scores_a=[0.9, 0.85, 0.92], rq4_scores_b=[0.8, 0.78, 0.81])
    assert report.rq4_paired_comparison.status == "EXECUTED"
    assert report.rq4_paired_comparison.value["contrast"].n_pairs == 3
    assert report.holm_correction.status == "EXECUTED"


def test_supplying_real_non_inferiority_inputs_executes_it():
    report = run_confirmatory_statistical_plan(non_inferiority_differences=[0.01, -0.02, 0.0, 0.01, -0.01], non_inferiority_margin=0.1)
    assert report.non_inferiority.status == "EXECUTED"
    assert report.non_inferiority.value.margin == 0.1


def test_supplying_real_predictions_and_device_map_executes_enrolled_population_class_exclusion_sensitivity():
    predictions = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A"},
        {"example_id": "e2", "true_label": "B", "predicted_label": "B"},
    ]
    report = run_confirmatory_statistical_plan(predictions=predictions, device_id_by_example_id={"e1": "D1", "e2": "D2"}, known_classes=["A", "B"])
    assert report.enrolled_population_class_exclusion_sensitivity.status == "EXECUTED"
    assert len(report.enrolled_population_class_exclusion_sensitivity.value) == 2


def test_confirmatory_statistical_plan_to_dict_serializes_dataclass_values():
    report = run_confirmatory_statistical_plan(non_inferiority_differences=[0.01, 0.02, -0.01, 0.0, 0.01], non_inferiority_margin=0.05)
    as_dict = confirmatory_statistical_plan_to_dict(report)
    assert as_dict["non_inferiority"]["status"] == "EXECUTED"
    assert isinstance(as_dict["non_inferiority"]["value"], dict)
    assert "margin" in as_dict["non_inferiority"]["value"]
