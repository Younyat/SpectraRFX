"""Sensitivity canonical producer (2026-08-12, Scientific Closure pass) --
pure functions, never a new statistic."""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.sensitivity_analysis import (
    enrich_class_exclusion_with_delta_vs_full_set,
    full_set_balanced_accuracy,
)
from app.modules.ble_scientific_results.statistics.sensitivity import ClassExclusionSensitivityResult


def test_full_set_balanced_accuracy_matches_metrics_module_definition():
    predictions = [
        {"true_label": "UNIT-A", "predicted_label": "UNIT-A"},
        {"true_label": "UNIT-A", "predicted_label": "UNIT-B"},
        {"true_label": "UNIT-B", "predicted_label": "UNIT-B"},
    ]
    ba = full_set_balanced_accuracy(predictions, ["UNIT-A", "UNIT-B"])
    assert ba == pytest.approx((0.5 + 1.0) / 2)


def test_full_set_balanced_accuracy_returns_none_with_no_comparable_predictions():
    assert full_set_balanced_accuracy([{"true_label": "UNKNOWN_CLASS", "predicted_label": "X"}], ["UNIT-A"]) is None


def test_enrich_lodo_computes_real_delta_vs_full_set():
    class_exclusion_results = [
        ClassExclusionSensitivityResult(excluded_device_id="UNIT-A", n_comparable=10, accuracy=0.8, balanced_accuracy_value=0.75),
        ClassExclusionSensitivityResult(excluded_device_id="UNIT-B", n_comparable=8, accuracy=0.6, balanced_accuracy_value=0.55),
    ]
    rows = enrich_class_exclusion_with_delta_vs_full_set(class_exclusion_results, full_set_ba=0.7)
    by_unit = {r["omitted_physical_unit"]: r for r in rows}
    assert by_unit["UNIT-A"]["delta_vs_full_set"] == pytest.approx(0.05)
    assert by_unit["UNIT-B"]["delta_vs_full_set"] == pytest.approx(-0.15)
    assert by_unit["UNIT-A"]["coverage"] is None  # honest -- no calibrated-threshold path here


def test_enrich_lodo_never_fabricates_a_delta_when_a_real_estimate_is_missing():
    class_exclusion_results = [ClassExclusionSensitivityResult(excluded_device_id="UNIT-A", n_comparable=0, accuracy=None, balanced_accuracy_value=None)]
    rows = enrich_class_exclusion_with_delta_vs_full_set(class_exclusion_results, full_set_ba=0.7)
    assert rows[0]["delta_vs_full_set"] is None
