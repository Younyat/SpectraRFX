"""Tests for the hypothesis-specific power simulations (H1/H2/H3). Every
result must carry status=PROVISIONAL_DIAGNOSTIC_ONLY -- this suite also
locks in the real, load-bearing finding that H2's EXACT permutation test
with only 5 units split 2-vs-3 can never reach significance at alpha=0.05
(minimum achievable exact p-value is 1/C(5,2)=0.1), a genuine design
constraint independent of any variance/effect-size assumption."""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.ble_scientific_results.statistics.hypothesis_power import (
    STATUS_PROVISIONAL_DIAGNOSTIC_ONLY,
    simulate_h1_dependence,
    simulate_h2_power_cycle,
    simulate_h3_content,
)

_FAST_SIM = dict(n_simulations=300, rng=np.random.default_rng(1))


def test_h1_status_is_always_provisional_diagnostic_only():
    result = simulate_h1_dependence(n_units=5, n_days=20, units_sweep=(2, 5), days_sweep=(5, 20), block_count_sweep=(10, 50), **_FAST_SIM)
    assert result.status == STATUS_PROVISIONAL_DIAGNOSTIC_ONLY


def test_h1_power_increases_with_more_units_and_more_days():
    result = simulate_h1_dependence(n_units=5, n_days=20, window_bias=0.05, dependence_between_block_sd=0.08, units_sweep=(2, 5, 10), days_sweep=(5, 20, 40), block_count_sweep=(10, 50), **_FAST_SIM)
    units_powers = [result.power_dependence_by_units[u] for u in (2, 5, 10)]
    assert units_powers == sorted(units_powers)
    days_powers = [result.power_dependence_by_days[d] for d in (5, 20, 40)]
    assert days_powers == sorted(days_powers)


def test_h1_zero_effect_gives_power_near_alpha():
    # No systematic window/capture or transportability gap -- the paired
    # t-test's rejection rate under a true null should sit near alpha.
    result = simulate_h1_dependence(
        n_units=20, n_days=20, window_bias=0.0, transport_gap=0.0, alpha=0.05,
        units_sweep=(20,), days_sweep=(20,), block_count_sweep=(200,),
        n_simulations=3000, rng=np.random.default_rng(2),
    )
    assert result.power_dependence_by_valid_blocks[200] == pytest.approx(0.05, abs=0.03)
    assert result.power_future_by_valid_blocks[200] == pytest.approx(0.05, abs=0.03)


def test_h1_interval_widths_are_positive():
    result = simulate_h1_dependence(n_units=5, n_days=20, units_sweep=(5,), days_sweep=(20,), block_count_sweep=(20,), **_FAST_SIM)
    assert result.expected_interval_width_dependence > 0
    assert result.expected_interval_width_future > 0


_H2_DEVICE_IDS = ("D1", "D2", "D3")


def test_h2_status_is_always_provisional_diagnostic_only():
    result = simulate_h2_power_cycle(
        device_ids=_H2_DEVICE_IDS, n_days_per_device=4, devices_sweep=(3,), days_sweep=(4,),
        n_simulations=30, rng=np.random.default_rng(3),
    )
    assert result.status == STATUS_PROVISIONAL_DIAGNOSTIC_ONLY


def test_h2_crossover_power_is_near_zero_with_no_true_effect():
    result = simulate_h2_power_cycle(
        device_ids=_H2_DEVICE_IDS, n_days_per_device=4, alpha=0.05, effect_size=0.0,
        between_device_sd=0.01, within_device_day_sd=0.02, pair_loss_rate=0.0,
        devices_sweep=(3,), days_sweep=(4,), n_simulations=40, rng=np.random.default_rng(3),
    )
    assert result.power_by_days_per_device[4] < 0.2


def test_h2_crossover_power_is_high_with_a_large_effect_and_low_noise():
    result = simulate_h2_power_cycle(
        device_ids=_H2_DEVICE_IDS, n_days_per_device=4, alpha=0.05, effect_size=1.0,
        between_device_sd=0.001, within_device_day_sd=0.001, pair_loss_rate=0.0,
        devices_sweep=(3,), days_sweep=(4,), n_simulations=40, rng=np.random.default_rng(4),
    )
    assert result.power_by_days_per_device[4] > 0.9
    assert result.probability_of_insufficient_evidence < 0.1


def test_h2_crossover_rejects_odd_days_per_device():
    with pytest.raises(ValueError):
        simulate_h2_power_cycle(
            device_ids=_H2_DEVICE_IDS, n_days_per_device=3, devices_sweep=(3,), days_sweep=(3,),
            n_simulations=5, rng=np.random.default_rng(5),
        )


def test_h3_status_is_always_provisional_diagnostic_only():
    result = simulate_h3_content(n_units=5, n_content_days=4, units_sweep=(5,), days_sweep=(4,), block_count_sweep=(20,), **_FAST_SIM)
    assert result.status == STATUS_PROVISIONAL_DIAGNOSTIC_ONLY


def test_h3a_power_increases_with_more_blocks():
    result = simulate_h3_content(n_units=5, n_content_days=4, h3a_effect_size=0.05, h3a_between_block_sd=0.07, units_sweep=(2, 5, 10), days_sweep=(4,), block_count_sweep=(10, 40), **_FAST_SIM)
    units_powers = [result.h3a_power_by_units[u] for u in (2, 5, 10)]
    assert units_powers == sorted(units_powers)


def test_h3b_non_inferiority_probability_is_high_when_truly_equivalent_with_generous_margin():
    result = simulate_h3_content(
        n_units=5, n_content_days=4, h3b_true_difference=0.0, h3b_between_block_sd=0.02, h3b_margin=0.1,
        units_sweep=(5,), days_sweep=(4,), block_count_sweep=(20,), **_FAST_SIM,
    )
    assert result.h3b_non_inferior_probability_by_valid_blocks[20] > 0.9


def test_h3b_non_inferiority_probability_is_low_when_the_true_gap_exceeds_the_margin():
    result = simulate_h3_content(
        n_units=5, n_content_days=4, h3b_true_difference=-0.2, h3b_between_block_sd=0.03, h3b_margin=0.05,
        units_sweep=(5,), days_sweep=(4,), block_count_sweep=(20,), **_FAST_SIM,
    )
    assert result.h3b_non_inferior_probability_by_valid_blocks[20] < 0.1
