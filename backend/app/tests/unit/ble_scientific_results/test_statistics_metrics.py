"""Known-value regression tests for statistics/metrics.py -- every expected
number here is hand-derived from the metric's own textbook definition, not
copied from the implementation."""
from __future__ import annotations

import math

import pytest

from app.modules.ble_scientific_results.statistics.metrics import balanced_accuracy, cllr, coverage, eer, far_frr, worst_case_error


def test_balanced_accuracy_matches_hand_computed_macro_recall():
    y_true = [0, 0, 1, 1, 1]
    y_pred = [0, 1, 1, 1, 0]
    # class 0: support=2, correct=1 (index 0) -> recall 0.5
    # class 1: support=3, correct=2 (indices 2,3) -> recall 2/3
    expected = (0.5 + 2 / 3) / 2
    assert balanced_accuracy(y_true, y_pred) == pytest.approx(expected)


def test_balanced_accuracy_perfect_predictions_is_one():
    assert balanced_accuracy([0, 1, 2, 0, 1, 2], [0, 1, 2, 0, 1, 2]) == pytest.approx(1.0)


def test_balanced_accuracy_excludes_zero_support_label():
    # label 2 never occurs in y_true -- must not silently count as recall 0.
    result = balanced_accuracy([0, 0, 1, 1], [0, 1, 1, 1], labels=[0, 1, 2])
    assert result == pytest.approx((0.5 + 1.0) / 2)


def test_far_frr_hand_computed_example():
    y_true_is_target = [True, True, False, False, False]
    accepted = [True, False, True, False, False]
    result = far_frr(y_true_is_target, accepted)
    assert result.frr == pytest.approx(0.5)  # 1 false reject / 2 target trials
    assert result.far == pytest.approx(1 / 3)  # 1 false accept / 3 non-target trials
    assert result.n_target == 2
    assert result.n_nontarget == 3


def test_far_frr_all_correct_is_zero():
    result = far_frr([True, True, False, False], [True, True, False, False])
    assert result.far == 0.0
    assert result.frr == 0.0


def test_worst_case_error_is_the_max_not_the_average():
    assert worst_case_error(0.1, 0.4) == pytest.approx(0.4)
    assert worst_case_error(0.4, 0.1) == pytest.approx(0.4)


def test_coverage_hand_computed():
    assert coverage(total=10, abstained=3) == pytest.approx(0.7)
    assert coverage(total=10, abstained=0) == pytest.approx(1.0)
    assert coverage(total=10, abstained=10) == pytest.approx(0.0)


def test_coverage_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        coverage(total=0, abstained=0)
    with pytest.raises(ValueError):
        coverage(total=10, abstained=11)


def test_eer_hand_computed_crossing():
    thresholds = [0, 1, 2, 3]
    far_values = [1.0, 0.6, 0.2, 0.0]
    frr_values = [0.0, 0.3, 0.7, 1.0]
    result = eer(thresholds, far_values, frr_values)
    assert result.eer == pytest.approx(0.45)
    assert result.threshold == pytest.approx(1.375)


def test_eer_exact_crossing_point():
    thresholds = [0, 1, 2]
    far_values = [1.0, 0.5, 0.0]
    frr_values = [0.0, 0.5, 1.0]
    result = eer(thresholds, far_values, frr_values)
    assert result.eer == pytest.approx(0.5)
    assert result.threshold == pytest.approx(1.0)


def test_eer_raises_when_curves_never_cross():
    with pytest.raises(ValueError):
        eer([0, 1, 2], [1.0, 0.9, 0.8], [0.0, 0.05, 0.1])


def test_cllr_of_uninformative_llr_is_exactly_one():
    # A system that outputs LLR=0 (LR=1) for every trial carries zero
    # information -- the well-known reference value is Cllr = 1.0
    # (Brummer & du Preez 2006).
    result = cllr([0.0, 0.0, 0.0], [0.0, 0.0])
    assert result == pytest.approx(1.0, abs=1e-9)


def test_cllr_of_perfectly_calibrated_extreme_llrs_approaches_zero():
    result = cllr([50.0, 50.0], [-50.0, -50.0])
    assert result == pytest.approx(0.0, abs=1e-9)


def test_cllr_symmetry_between_target_and_nontarget_terms():
    # Swapping the roles (negate every LLR and swap target/nontarget) must
    # leave Cllr unchanged -- a direct consequence of the formula's symmetry.
    a = cllr([1.0, 2.0, -0.5], [-1.0, 0.3])
    b = cllr([1.0, -0.3], [-1.0, -2.0, 0.5])
    assert a == pytest.approx(b)
