"""Known-value regression tests for statistics/power_simulation.py. The
closed-form power is checked against an INDEPENDENTLY re-derived formula
(written fresh here, not imported from the module), and the Monte Carlo
simulator is cross-checked against that same closed form in the
zero-clustering limit -- the two must agree since a design with icc=0
degenerates to a plain two-proportion comparison."""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.modules.ble_scientific_results.statistics.power_simulation import (
    HierarchicalDesign,
    closed_form_power_two_proportions,
    evaluate_design_sufficiency,
    find_minimum_sufficient_design,
    simulate_hierarchical_power,
)

_Z_975 = 1.9599639845400545  # standard normal 97.5th percentile, a well-known constant


def _reference_power_two_proportions(p1: float, p2: float, n_per_arm: float, alpha: float = 0.05) -> float:
    se = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    z_alpha = _Z_975 if alpha == 0.05 else NotImplemented
    z_effect = abs(p1 - p2) / se
    return 0.5 * (1 + math.erf((z_effect - z_alpha) / math.sqrt(2)))


def test_design_effect_hand_computed_with_clustering():
    design = HierarchicalDesign(n_units=5, n_days=20, n_captures_per_unit_day=1, icc_unit=0.1, icc_day=0.0)
    # m_unit = n_days*n_captures = 20; DEFF = 1 + (20-1)*0.1 = 2.9
    assert design.design_effect == pytest.approx(2.9)
    assert design.total_captures == 100
    assert design.effective_captures == pytest.approx(100 / 2.9)


def test_design_effect_is_one_with_zero_icc():
    design = HierarchicalDesign(n_units=5, n_days=20, n_captures_per_unit_day=3, icc_unit=0.0, icc_day=0.0)
    assert design.design_effect == pytest.approx(1.0)
    assert design.effective_captures == pytest.approx(design.total_captures)


def test_design_rejects_invalid_counts_and_icc():
    with pytest.raises(ValueError):
        HierarchicalDesign(n_units=0, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    with pytest.raises(ValueError):
        HierarchicalDesign(n_units=1, n_days=1, n_captures_per_unit_day=1, icc_unit=1.0, icc_day=0.0)


def test_closed_form_power_matches_independent_reference_formula():
    # design describes ONE arm -- n_per_arm equals its own effective_captures
    # directly (both arms assumed to share the same shape), not half of it.
    design = HierarchicalDesign(n_units=100, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    power = closed_form_power_two_proportions(design, p1=0.5, p2=0.7, alpha=0.05)
    expected = _reference_power_two_proportions(0.5, 0.7, n_per_arm=100, alpha=0.05)
    assert power == pytest.approx(expected, abs=1e-9)


def test_closed_form_power_increases_with_effect_size():
    design = HierarchicalDesign(n_units=100, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    small_effect = closed_form_power_two_proportions(design, p1=0.5, p2=0.55, alpha=0.05)
    large_effect = closed_form_power_two_proportions(design, p1=0.5, p2=0.9, alpha=0.05)
    assert large_effect > small_effect


def test_clustering_reduces_power_relative_to_no_clustering():
    no_clustering = HierarchicalDesign(n_units=100, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    with_clustering = HierarchicalDesign(n_units=20, n_days=1, n_captures_per_unit_day=5, icc_unit=0.3, icc_day=0.0)
    # Same total_captures (100), but the clustered design has fewer effective captures.
    assert with_clustering.total_captures == no_clustering.total_captures
    assert with_clustering.effective_captures < no_clustering.effective_captures
    power_no_clustering = closed_form_power_two_proportions(no_clustering, p1=0.5, p2=0.7)
    power_with_clustering = closed_form_power_two_proportions(with_clustering, p1=0.5, p2=0.7)
    assert power_with_clustering < power_no_clustering


def test_monte_carlo_simulation_matches_closed_form_with_zero_icc():
    design = HierarchicalDesign(n_units=60, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    closed_form = closed_form_power_two_proportions(design, p1=0.5, p2=0.75, alpha=0.05)
    simulated = simulate_hierarchical_power(design, p1=0.5, p2=0.75, alpha=0.05, n_simulations=4000, rng=np.random.default_rng(42))
    # Agreement within a wide but principled band: 4 Monte Carlo standard
    # errors plus a small slack for the z-test's normal approximation.
    tolerance = 4 * simulated.monte_carlo_standard_error + 0.02
    assert abs(simulated.empirical_power - closed_form) < tolerance


def test_evaluate_design_sufficiency_verdicts():
    tiny = HierarchicalDesign(n_units=2, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    huge = HierarchicalDesign(n_units=1000, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
    moderate = HierarchicalDesign(n_units=100, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)

    assert evaluate_design_sufficiency(tiny, p1=0.5, p2=0.55).verdict == "INSUFFICIENT"
    assert evaluate_design_sufficiency(huge, p1=0.5, p2=0.9).verdict == "OVERPROVISIONED"
    result = evaluate_design_sufficiency(moderate, p1=0.5, p2=0.7)
    assert result.verdict == "SUFFICIENT"
    assert 0.8 <= result.power <= 0.97


def test_find_minimum_sufficient_design_returns_the_smallest_that_reaches_target_power():
    candidates = [
        HierarchicalDesign(n_units=u, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0)
        for u in (10, 50, 100, 150, 200, 300)
    ]
    result = find_minimum_sufficient_design(candidates, p1=0.5, p2=0.7, target_power=0.8)
    assert result is not None
    assert result.design.n_units == 100
    assert result.power >= 0.8


def test_find_minimum_sufficient_design_returns_none_when_no_candidate_suffices():
    candidates = [HierarchicalDesign(n_units=u, n_days=1, n_captures_per_unit_day=1, icc_unit=0.0, icc_day=0.0) for u in (5, 10)]
    assert find_minimum_sufficient_design(candidates, p1=0.5, p2=0.55, target_power=0.8) is None
