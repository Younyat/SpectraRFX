"""Hypothesis-specific power simulations for the paper's confirmatory
analyses (H1 evaluation-dependence, H2 power-cycle, H3 content), replacing
the earlier generic two-proportion design check for design-sufficiency
purposes. That generic tool (power_simulation.py) is still correct as a
low-level primitive and stays in place, but its SUFFICIENT/INSUFFICIENT/
OVERPROVISIONED verdict must never again be read as a design decision by
itself -- every result produced here carries `status =
"PROVISIONAL_DIAGNOSTIC_ONLY"` explicitly, and none of them decide
anything about device counts, campaign duration, or the paper's protocol.
That decision is the user's, informed by these numbers plus real
pilot-estimated variance (see docstrings on each function for what remains
a stated assumption vs. an estimate).

Modeling choice, stated once here to avoid repeating it three times: every
PAIRED contrast (H1's two deltas, H3a) is simulated directly on the
distribution of the per-block difference itself -- mean = the assumed true
effect, SD = the assumed between-block variability of that difference. This
is the standard, sufficient level of abstraction for paired-test power
(Cohen's d_z formulation): the paired test's power depends only on that
distribution, not on how its variance decomposes into unit/day/window
components, so no separate unit-effect/day-effect Monte Carlo layer is
needed for a paired contrast.

H2 (post physical-inventory correction) is a WITHIN-DEVICE randomized
crossover -- the enrolled devices are five heterogeneous transmitters
(different hardware models), so there is no admissible between-device
RESET-vs-CONTROL split to begin with; every device supplies its own
RESET days and its own CONTINUOUS_POWER days, and acts as its own
control. Every H2 trial runs the real stratified-by-device permutation
test (statistics/inference.py::stratified_crossover_permutation_test),
Monte Carlo at realistic day counts (the joint permutation space across
5+ devices is intractably large to enumerate exactly), not a proxy.

Significance testing inside the OUTER Monte Carlo power loop uses a paired
t-test (H1, H3a) as a fast, standard asymptotic proxy for the paired
sign-flip randomization test (statistics/inference.py::
exact_randomization_test) -- valid by the CLT at the block counts this
design can reach, and dramatically cheaper than re-running an exact/Monte
Carlo permutation test inside every one of a few thousand simulated
trials. The REAL confirmatory analysis on real data must use
exact_randomization_test (H1/H3a) or stratified_crossover_permutation_test
(H2) directly, not any proxy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .inference import _t_quantile, non_inferiority_test, stratified_crossover_permutation_test

STATUS_PROVISIONAL_DIAGNOSTIC_ONLY = "PROVISIONAL_DIAGNOSTIC_ONLY"


def _paired_t_rejects(differences: Sequence[float], *, alpha: float) -> bool:
    n = len(differences)
    if n < 2:
        return False
    mean = sum(differences) / n
    variance = sum((value - mean) ** 2 for value in differences) / (n - 1)
    if variance <= 0:
        return mean != 0
    standard_error = math.sqrt(variance / n)
    t_statistic = mean / standard_error
    critical = _t_quantile(1 - alpha / 2, df=n - 1)
    return abs(t_statistic) >= critical


def _paired_ci_half_width(differences: Sequence[float], *, alpha: float) -> float:
    n = len(differences)
    if n < 2:
        return float("nan")
    mean = sum(differences) / n
    variance = sum((value - mean) ** 2 for value in differences) / (n - 1)
    standard_error = math.sqrt(variance / n)
    return _t_quantile(1 - alpha / 2, df=n - 1) * standard_error


# ----------------------------------------------------------------------
# H1 -- evaluation-level dependence (window vs capture vs future)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class H1Result:
    status: str
    power_dependence_by_units: dict[int, float]
    power_dependence_by_days: dict[int, float]
    power_dependence_by_valid_blocks: dict[int, float]
    power_future_by_valid_blocks: dict[int, float]
    expected_interval_width_dependence: float
    expected_interval_width_future: float
    probability_of_insufficient_evidence_dependence: float
    probability_of_insufficient_evidence_future: float
    sensitivity_to_variance: dict[str, dict[str, float]]


def _h1_trial_power(
    *, n_blocks: int, effect_size: float, between_block_sd: float, block_survival_rate: float,
    alpha: float, n_simulations: int, rng: np.random.Generator,
) -> tuple[float, float]:
    """Returns (power, mean_ci_half_width) for one (effect, sd, n_blocks)
    combination, dropping a random fraction of blocks each trial to model
    "pérdida ocasional de pares" -- a block lost to missing metadata,
    overflow, or a failed decode never becomes a silently-imputed zero."""
    rejections = 0
    half_widths = []
    for _ in range(n_simulations):
        surviving = int(rng.binomial(n_blocks, block_survival_rate)) if block_survival_rate < 1.0 else n_blocks
        surviving = min(max(surviving, 2), n_blocks)
        differences = rng.normal(effect_size, between_block_sd, surviving)
        if _paired_t_rejects(differences, alpha=alpha):
            rejections += 1
        half_widths.append(_paired_ci_half_width(differences, alpha=alpha))
    power = rejections / n_simulations
    mean_half_width = float(np.nanmean(half_widths))
    return power, mean_half_width


def simulate_h1_dependence(
    *, n_units: int = 5, n_days: int = 20, alpha: float = 0.05, n_simulations: int = 2000,
    window_bias: float = 0.03, transport_gap: float = 0.05,
    dependence_between_block_sd: float = 0.07, future_between_block_sd: float = 0.08,
    block_survival_rate: float = 0.9, units_sweep: Sequence[int] = (2, 3, 5, 8, 10),
    days_sweep: Sequence[int] = (5, 10, 20, 30, 40), block_count_sweep: Sequence[int] = (10, 20, 40, 60, 100),
    rng: np.random.Generator | None = None,
) -> H1Result:
    """H1: does evaluating at the window level vs. the capture level give a
    systematically different balanced accuracy (delta_dependence =
    BA_window - BA_capture, expected mean -window_bias), and does
    performance transport to future/held-out data (delta_future =
    BA_capture - BA_future, expected mean +transport_gap)? Both are PAIRED
    per (unit, day) block -- see module docstring for why unit/day random
    effects cancel out of a within-block difference and do not need their
    own simulation layer here."""
    rng = rng or np.random.default_rng(20260806)
    n_blocks_declared = n_units * n_days

    power_dependence_by_units = {}
    for units in units_sweep:
        power, _ = _h1_trial_power(n_blocks=units * n_days, effect_size=-window_bias, between_block_sd=dependence_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
        power_dependence_by_units[units] = power

    power_dependence_by_days = {}
    for days in days_sweep:
        power, _ = _h1_trial_power(n_blocks=n_units * days, effect_size=-window_bias, between_block_sd=dependence_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
        power_dependence_by_days[days] = power

    power_dependence_by_valid_blocks = {}
    power_future_by_valid_blocks = {}
    for blocks in block_count_sweep:
        power_d, _ = _h1_trial_power(n_blocks=blocks, effect_size=-window_bias, between_block_sd=dependence_between_block_sd, block_survival_rate=1.0, alpha=alpha, n_simulations=n_simulations, rng=rng)
        power_dependence_by_valid_blocks[blocks] = power_d
        power_f, _ = _h1_trial_power(n_blocks=blocks, effect_size=transport_gap, between_block_sd=future_between_block_sd, block_survival_rate=1.0, alpha=alpha, n_simulations=n_simulations, rng=rng)
        power_future_by_valid_blocks[blocks] = power_f

    power_dep_declared, width_dep = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=-window_bias, between_block_sd=dependence_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
    power_fut_declared, width_fut = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=transport_gap, between_block_sd=future_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)

    sensitivity: dict[str, dict[str, float]] = {}
    for label, multiplier in (("low_variance", 0.6), ("pilot_estimated_variance", 1.0), ("high_variance", 1.6)):
        power_d, _ = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=-window_bias, between_block_sd=dependence_between_block_sd * multiplier, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
        power_f, _ = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=transport_gap, between_block_sd=future_between_block_sd * multiplier, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
        sensitivity[label] = {"power_dependence": power_d, "power_future": power_f}

    return H1Result(
        status=STATUS_PROVISIONAL_DIAGNOSTIC_ONLY,
        power_dependence_by_units=power_dependence_by_units, power_dependence_by_days=power_dependence_by_days,
        power_dependence_by_valid_blocks=power_dependence_by_valid_blocks, power_future_by_valid_blocks=power_future_by_valid_blocks,
        expected_interval_width_dependence=2 * width_dep, expected_interval_width_future=2 * width_fut,
        probability_of_insufficient_evidence_dependence=1 - power_dep_declared, probability_of_insufficient_evidence_future=1 - power_fut_declared,
        sensitivity_to_variance=sensitivity,
    )


# ----------------------------------------------------------------------
# H2 -- power cycle, WITHIN-DEVICE randomized crossover (post inventory
# correction: the enrolled devices are five heterogeneous transmitters --
# CC2541 SensorTag, Shelly Plug, two "keyfobdemo" units, one CC2650
# SensorTag -- so a between-device RESET-vs-CONTROL split would compare
# different hardware models as if they were interchangeable. Every device
# now acts as its own control: each device-day is independently and
# randomly assigned RESET or CONTINUOUS_POWER, balanced per device across
# the campaign.
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class H2Result:
    status: str
    power_by_devices: dict[int, float]
    power_by_days_per_device: dict[int, float]
    power_by_valid_blocks: dict[int, float]
    expected_interval_width: float
    probability_of_insufficient_evidence: float
    sensitivity_to_variance: dict[str, float]


def _h2_crossover_trial(
    *, device_ids: Sequence[str], n_days_per_device: int, effect_size: float, between_device_sd: float,
    within_device_day_sd: float, pair_loss_rate: float, alpha: float, rng: np.random.Generator,
) -> tuple[bool | None, float]:
    """One simulated qualification-style crossover campaign: EVERY device in
    `device_ids` gets its own randomized, balanced sequence of RESET/
    CONTINUOUS_POWER days (never a between-device split), a device-specific
    true effect drawn from Normal(effect_size, between_device_sd) (devices
    may respond differently -- this is the ONLY place device heterogeneity
    enters, since the crossover design otherwise compares each device only
    against itself), and per-day noise. A day's pre/post pair can be
    missing entirely at `pair_loss_rate` (never imputed). Returns
    (rejected, observed_delta_cycle) using the real stratified-by-device
    permutation test; `rejected` is None when fewer than 2 devices retain
    both arms after pair loss (a degenerate draw, never counted as a
    rejection or a non-rejection)."""
    n_devices = len(device_ids)
    if n_days_per_device % 2 != 0:
        raise ValueError("N_DAYS_PER_DEVICE_MUST_BE_EVEN_FOR_A_BALANCED_CROSSOVER")
    n_reset_days = n_days_per_device // 2

    device_day_values: dict[str, list[float]] = {}
    device_day_is_reset: dict[str, list[bool]] = {}
    for device_id in device_ids:
        device_true_effect = rng.normal(effect_size, between_device_sd)
        labels = [True] * n_reset_days + [False] * (n_days_per_device - n_reset_days)
        rng.shuffle(labels)  # the frozen calendar's own randomized, balanced order
        values, surviving_labels = [], []
        for is_reset in labels:
            if rng.random() < pair_loss_rate:
                continue  # the whole pre/post pair for this device-day is missing
            arm_effect = device_true_effect if is_reset else 0.0
            values.append(arm_effect + rng.normal(0.0, within_device_day_sd))
            surviving_labels.append(is_reset)
        if values and any(surviving_labels) and not all(surviving_labels):
            device_day_values[device_id] = values
            device_day_is_reset[device_id] = surviving_labels

    if len(device_day_values) < 2:
        return None, float("nan")  # too few devices retained both arms -- degenerate, not a rejection
    # n_monte_carlo=500 here (vs. stratified_crossover_permutation_test's own
    # default of 20000) is a deliberate speed/precision trade-off SPECIFIC to
    # this inner loop: a reject/no-reject decision at alpha=0.05 only needs
    # ~0.01 p-value resolution, and this call runs inside an outer Monte
    # Carlo power loop of its own (thousands of times). The real
    # confirmatory analysis on real data must call
    # stratified_crossover_permutation_test directly, with its own default
    # (or higher) n_monte_carlo, never this reduced value.
    result = stratified_crossover_permutation_test(device_day_values, device_day_is_reset, n_monte_carlo=500, rng=rng)
    return result.p_value < alpha, result.observed_statistic


def simulate_h2_power_cycle(
    *, device_ids: Sequence[str] = ("CC2541SensorTag", "SHELLY-PLUG-01", "keyfobdemo 01", "keyfobdemo 02", "CC2650-UNIT-01"),
    n_days_per_device: int = 20, alpha: float = 0.05, n_simulations: int = 800,
    effect_size: float = 0.08, between_device_sd: float = 0.05, within_device_day_sd: float = 0.04,
    pair_loss_rate: float = 0.05, devices_sweep: Sequence[int] = (2, 3, 5, 8, 10),
    days_sweep: Sequence[int] = (2, 6, 10, 20, 40), rng: np.random.Generator | None = None,
) -> H2Result:
    """H2: within-device randomized crossover (each of the 5 enrolled,
    heterogeneous devices acts as its own control). `devices_sweep` is
    informational only -- with 5 REAL enrolled devices there is no
    physical population to enlarge; the sweep shows how the tool's power
    would behave with a different device COUNT, never a claim that more
    devices are available. Interpretation of the resulting effect is
    "average reset-associated displacement across the enrolled devices
    under the randomized crossover protocol", never "effect in the CC2650
    population" or any other device-family population."""
    rng = rng or np.random.default_rng(20260806)

    def _power_for(devices: Sequence[str], days: int) -> tuple[float, float]:
        rejections, counted, observed_values = 0, 0, []
        for _ in range(n_simulations):
            rejected, observed = _h2_crossover_trial(
                device_ids=devices, n_days_per_device=days, effect_size=effect_size, between_device_sd=between_device_sd,
                within_device_day_sd=within_device_day_sd, pair_loss_rate=pair_loss_rate, alpha=alpha, rng=rng,
            )
            if rejected is None:
                continue
            counted += 1
            observed_values.append(observed)
            if rejected:
                rejections += 1
        power = rejections / counted if counted else float("nan")
        width = float(np.std(observed_values, ddof=1)) if len(observed_values) > 1 else float("nan")
        return power, width

    synthetic_device_ids = [f"DEVICE-{i}" for i in range(max(devices_sweep))]
    power_by_devices = {n: _power_for(synthetic_device_ids[:n], n_days_per_device)[0] for n in devices_sweep}
    power_by_days_per_device = {days: _power_for(device_ids, days)[0] for days in days_sweep}
    power_by_valid_blocks = {days * len(device_ids): _power_for(device_ids, days)[0] for days in days_sweep}
    power_declared, width_declared = _power_for(device_ids, n_days_per_device)

    sensitivity = {}
    for label, multiplier in (("low_variance", 0.6), ("pilot_estimated_variance", 1.0), ("high_variance", 1.6)):
        power, _ = _h2_sensitivity_power(
            device_ids=device_ids, n_days_per_device=n_days_per_device, effect_size=effect_size,
            between_device_sd=between_device_sd * multiplier, within_device_day_sd=within_device_day_sd * multiplier,
            pair_loss_rate=pair_loss_rate, alpha=alpha, n_simulations=n_simulations, rng=rng,
        )
        sensitivity[label] = power

    return H2Result(
        status=STATUS_PROVISIONAL_DIAGNOSTIC_ONLY,
        power_by_devices=power_by_devices, power_by_days_per_device=power_by_days_per_device, power_by_valid_blocks=power_by_valid_blocks,
        expected_interval_width=width_declared, probability_of_insufficient_evidence=1 - power_declared if not math.isnan(power_declared) else float("nan"),
        sensitivity_to_variance=sensitivity,
    )


def _h2_sensitivity_power(*, device_ids, n_days_per_device, effect_size, between_device_sd, within_device_day_sd, pair_loss_rate, alpha, n_simulations, rng) -> tuple[float, float]:
    rejections, counted = 0, 0
    for _ in range(n_simulations):
        rejected, _observed = _h2_crossover_trial(
            device_ids=device_ids, n_days_per_device=n_days_per_device, effect_size=effect_size, between_device_sd=between_device_sd,
            within_device_day_sd=within_device_day_sd, pair_loss_rate=pair_loss_rate, alpha=alpha, rng=rng,
        )
        if rejected is None:
            continue
        counted += 1
        if rejected:
            rejections += 1
    power = rejections / counted if counted else float("nan")
    return power, float("nan")


# ----------------------------------------------------------------------
# H3 -- content (packet variant) blocks: unit x content-day x packet-variant
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class H3Result:
    status: str
    h3a_power_by_units: dict[int, float]
    h3a_power_by_days: dict[int, float]
    h3a_power_by_valid_blocks: dict[int, float]
    h3a_expected_interval_width: float
    h3a_probability_of_insufficient_evidence: float
    h3b_non_inferior_probability_by_valid_blocks: dict[int, float]
    h3b_expected_ci_low: float
    sensitivity_to_variance: dict[str, dict[str, float]]


def simulate_h3_content(
    *, n_units: int = 5, n_content_days: int = 4, alpha: float = 0.05, n_simulations: int = 2000,
    h3a_effect_size: float = 0.06, h3a_between_block_sd: float = 0.07,
    h3b_true_difference: float = -0.01, h3b_between_block_sd: float = 0.05, h3b_margin: float = 0.05,
    block_survival_rate: float = 0.9, units_sweep: Sequence[int] = (2, 3, 5, 8, 10),
    days_sweep: Sequence[int] = (2, 4, 6, 10), block_count_sweep: Sequence[int] = (8, 16, 30, 50, 80),
    rng: np.random.Generator | None = None,
) -> H3Result:
    """Blocks are (physical unit x content-day x packet-variant) triples.
    H3a: a paired superiority/content-loss test (does the modified content
    variant measurably change the outcome vs. the original?) -- same
    paired-difference framework as H1. H3b: a ONE-SIDED non-inferiority
    test (does removing/altering the pre-PDU content stay within the
    frozen margin of the original?) -- reuses non_inferiority_test's real
    margin-based CI logic directly, not a proxy."""
    rng = rng or np.random.default_rng(20260806)
    n_blocks_declared = n_units * n_content_days

    h3a_power_by_units = {units: _h1_trial_power(n_blocks=units * n_content_days, effect_size=h3a_effect_size, between_block_sd=h3a_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)[0] for units in units_sweep}
    h3a_power_by_days = {days: _h1_trial_power(n_blocks=n_units * days, effect_size=h3a_effect_size, between_block_sd=h3a_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)[0] for days in days_sweep}
    h3a_power_by_valid_blocks = {blocks: _h1_trial_power(n_blocks=blocks, effect_size=h3a_effect_size, between_block_sd=h3a_between_block_sd, block_survival_rate=1.0, alpha=alpha, n_simulations=n_simulations, rng=rng)[0] for blocks in block_count_sweep}
    h3a_power_declared, h3a_width_declared = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=h3a_effect_size, between_block_sd=h3a_between_block_sd, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)

    def _h3b_non_inferior_probability(n_blocks: int) -> tuple[float, float]:
        successes = 0
        ci_lows = []
        for _ in range(n_simulations):
            differences = rng.normal(h3b_true_difference, h3b_between_block_sd, n_blocks)
            result = non_inferiority_test(list(differences), margin=h3b_margin, confidence_level=1 - alpha)
            ci_lows.append(result.ci_low)
            if result.non_inferior:
                successes += 1
        return successes / n_simulations, float(np.mean(ci_lows))

    h3b_by_blocks = {blocks: _h3b_non_inferior_probability(blocks)[0] for blocks in block_count_sweep}
    h3b_prob_declared, h3b_mean_ci_low = _h3b_non_inferior_probability(n_blocks_declared)

    sensitivity: dict[str, dict[str, float]] = {}
    for label, multiplier in (("low_variance", 0.6), ("pilot_estimated_variance", 1.0), ("high_variance", 1.6)):
        power_a, _ = _h1_trial_power(n_blocks=n_blocks_declared, effect_size=h3a_effect_size, between_block_sd=h3a_between_block_sd * multiplier, block_survival_rate=block_survival_rate, alpha=alpha, n_simulations=n_simulations, rng=rng)
        prob_b, _ = _h3b_non_inferior_probability_scaled(rng=rng, n_blocks=n_blocks_declared, true_difference=h3b_true_difference, between_block_sd=h3b_between_block_sd * multiplier, margin=h3b_margin, alpha=alpha, n_simulations=n_simulations)
        sensitivity[label] = {"h3a_power": power_a, "h3b_non_inferior_probability": prob_b}

    return H3Result(
        status=STATUS_PROVISIONAL_DIAGNOSTIC_ONLY,
        h3a_power_by_units=h3a_power_by_units, h3a_power_by_days=h3a_power_by_days, h3a_power_by_valid_blocks=h3a_power_by_valid_blocks,
        h3a_expected_interval_width=2 * h3a_width_declared, h3a_probability_of_insufficient_evidence=1 - h3a_power_declared,
        h3b_non_inferior_probability_by_valid_blocks=h3b_by_blocks, h3b_expected_ci_low=h3b_mean_ci_low,
        sensitivity_to_variance=sensitivity,
    )


def _h3b_non_inferior_probability_scaled(*, rng, n_blocks, true_difference, between_block_sd, margin, alpha, n_simulations) -> tuple[float, float]:
    successes = 0
    ci_lows = []
    for _ in range(n_simulations):
        differences = rng.normal(true_difference, between_block_sd, n_blocks)
        result = non_inferiority_test(list(differences), margin=margin, confidence_level=1 - alpha)
        ci_lows.append(result.ci_low)
        if result.non_inferior:
            successes += 1
    return successes / n_simulations, float(np.mean(ci_lows))
