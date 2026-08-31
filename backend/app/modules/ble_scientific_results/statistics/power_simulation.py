"""Power / minimum-design simulation for the paper's confirmatory design.

Models the design's own hierarchy explicitly -- physical unit -> day ->
capture -- and simulates at CAPTURE level (never treating individual bursts
as independent observations: multiple bursts inside one capture share the
same channel conditions, receiver state, and often the same short
transmission burst-train, so pretending they are independent draws would
silently inflate the effective sample size and overstate power). A capture
is the smallest unit this module ever draws a fresh, independent outcome
for; anything below that (windows, bursts) is the training pipeline's own
concern, not this simulation's.

Two ways to get a power estimate, cross-checked against each other:
  1. `closed_form_power_two_proportions` -- the standard design-effect-
     adjusted normal-approximation power for a two-arm comparison of
     proportions under cluster sampling (Killip et al. 2004; Hox 2010 for
     the nested design effect). Fast, deterministic, independently
     checkable against a textbook.
  2. `simulate_hierarchical_power` -- a genuine Monte Carlo simulation that
     draws unit-level and day-level random effects, then Bernoulli capture
     outcomes nested within them, and empirically measures how often a
     two-proportion z-test on the resulting capture-level data rejects the
     null. In the DEGENERATE case of zero between-unit/between-day
     variance (no clustering), this must converge to the closed-form power
     above -- exactly the cross-check this module's own tests use, since no
     real pilot data exists yet to anchor ICC/effect-size assumptions
     independently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np


# ----------------------------------------------------------------------
# Closed-form, design-effect-adjusted power
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class HierarchicalDesign:
    """Describes ONE ARM of a two-arm comparison (e.g. RESET vs CONTROL, or
    model A vs model B) -- `closed_form_power_two_proportions` and
    `simulate_hierarchical_power` both assume the OTHER arm has the
    identical shape (same n_units/n_days/n_captures_per_unit_day/ICCs),
    just a possibly different outcome rate. total_captures/effective_captures
    are therefore PER-ARM quantities, not a grand total split in half."""
    n_units: int
    n_days: int
    n_captures_per_unit_day: int
    icc_unit: float  # intraclass correlation attributable to between-unit variability
    icc_day: float  # additional intraclass correlation attributable to between-day (within-unit) variability

    def __post_init__(self) -> None:
        if self.n_units < 1 or self.n_days < 1 or self.n_captures_per_unit_day < 1:
            raise ValueError("DESIGN_COUNTS_MUST_BE_POSITIVE")
        if not (0.0 <= self.icc_unit < 1.0) or not (0.0 <= self.icc_day < 1.0):
            raise ValueError("ICC_MUST_BE_IN_[0,1)")

    @property
    def total_captures(self) -> int:
        return self.n_units * self.n_days * self.n_captures_per_unit_day

    @property
    def design_effect(self) -> float:
        """Nested (unit > day > capture) design effect: DEFF = 1 +
        (n_day*n_capture - 1)*icc_unit + (n_capture - 1)*icc_day -- the
        standard multi-level extension (Hox, 2010, ch. 12) of the
        single-level cluster-randomization design effect DEFF = 1 +
        (m-1)*icc used in Killip et al. (2004)."""
        m_unit = self.n_days * self.n_captures_per_unit_day
        return 1.0 + (m_unit - 1) * self.icc_unit + (self.n_captures_per_unit_day - 1) * self.icc_day

    @property
    def effective_captures(self) -> float:
        return self.total_captures / self.design_effect


def closed_form_power_two_proportions(design: HierarchicalDesign, *, p1: float, p2: float, alpha: float = 0.05) -> float:
    """Two-sided two-proportion z-test power. `design` describes ONE arm
    (see HierarchicalDesign's own docstring); its design-effect-adjusted
    effective_captures IS n_per_arm directly -- both arms are assumed to
    share the same shape. Standard normal-approximation formula (e.g.
    Fleiss, Levin & Paik, 2003, ch. 4):

        power = Phi( |p1-p2| / se - z_(1-alpha/2) ),  se = sqrt(p1(1-p1)/n + p2(1-p2)/n)
    """
    if not (0 < p1 < 1) or not (0 < p2 < 1):
        raise ValueError("PROPORTIONS_MUST_BE_IN_(0,1)")
    n_per_arm = design.effective_captures
    if n_per_arm <= 0:
        raise ValueError("EFFECTIVE_SAMPLE_SIZE_MUST_BE_POSITIVE")
    standard_error = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    z_alpha = _normal_quantile(1 - alpha / 2)
    z_effect = abs(p1 - p2) / standard_error
    return _normal_cdf(z_effect - z_alpha)


# ----------------------------------------------------------------------
# Monte Carlo hierarchical simulation
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class PowerSimulationResult:
    design: HierarchicalDesign
    p1: float
    p2: float
    alpha: float
    n_simulations: int
    empirical_power: float
    monte_carlo_standard_error: float


def simulate_hierarchical_power(
    design: HierarchicalDesign, *, p1: float, p2: float, alpha: float = 0.05,
    n_simulations: int = 3000, rng: np.random.Generator | None = None,
) -> PowerSimulationResult:
    """Simulates BOTH arms with the SAME hierarchical structure as `design`
    (same n_units/n_days/n_captures_per_unit_day on each arm), draws
    unit-level and day-level logit-scale random effects sized so their
    implied ICC matches `design.icc_unit`/`icc_day` at the given base rate,
    then Bernoulli capture outcomes -- and runs a two-proportion z-test on
    the resulting pooled capture-level counts each trial. Returns the
    fraction of trials where the null is rejected at `alpha` (two-sided)."""
    if not (0 < p1 < 1) or not (0 < p2 < 1):
        raise ValueError("PROPORTIONS_MUST_BE_IN_(0,1)")
    rng = rng or np.random.default_rng(12345)
    z_alpha = _normal_quantile(1 - alpha / 2)
    n = design.n_units * design.n_days * design.n_captures_per_unit_day

    rejections = 0
    for _ in range(n_simulations):
        successes_1 = _simulate_arm_successes(design, base_rate=p1, rng=rng)
        successes_2 = _simulate_arm_successes(design, base_rate=p2, rng=rng)
        rate_1, rate_2 = successes_1 / n, successes_2 / n
        pooled_rate = (successes_1 + successes_2) / (2 * n)
        se = math.sqrt(pooled_rate * (1 - pooled_rate) * (2.0 / n)) if 0 < pooled_rate < 1 else 0.0
        z = abs(rate_1 - rate_2) / se if se > 0 else 0.0
        if z >= z_alpha:
            rejections += 1

    empirical_power = rejections / n_simulations
    mc_se = math.sqrt(empirical_power * (1 - empirical_power) / n_simulations)
    return PowerSimulationResult(
        design=design, p1=p1, p2=p2, alpha=alpha, n_simulations=n_simulations,
        empirical_power=empirical_power, monte_carlo_standard_error=mc_se,
    )


def _simulate_arm_successes(design: HierarchicalDesign, *, base_rate: float, rng: np.random.Generator) -> int:
    base_logit = math.log(base_rate / (1 - base_rate))
    # Logit-scale random-effect SDs approximating the requested ICC via the
    # standard latent-variable heuristic (pi^2/3 residual variance on the
    # logit scale -- Snijders & Bosker, 2012, sec. 17.2): icc ~= tau^2 / (tau^2 + pi^2/3).
    unit_sd = _icc_to_logit_sd(design.icc_unit)
    day_sd = _icc_to_logit_sd(design.icc_day)
    total = 0
    for _ in range(design.n_units):
        unit_effect = rng.normal(0.0, unit_sd) if unit_sd > 0 else 0.0
        for _ in range(design.n_days):
            day_effect = rng.normal(0.0, day_sd) if day_sd > 0 else 0.0
            logit = base_logit + unit_effect + day_effect
            p = 1.0 / (1.0 + math.exp(-logit))
            total += int(rng.binomial(design.n_captures_per_unit_day, p))
    return total


def _icc_to_logit_sd(icc: float) -> float:
    if icc <= 0:
        return 0.0
    residual_variance = (math.pi**2) / 3.0
    return math.sqrt(icc * residual_variance / (1 - icc))


# ----------------------------------------------------------------------
# Design sufficiency verdicts
# ----------------------------------------------------------------------

Verdict = Literal["SUFFICIENT", "INSUFFICIENT", "OVERPROVISIONED"]


@dataclass(frozen=True)
class DesignEvaluation:
    design: HierarchicalDesign
    power: float
    verdict: Verdict


def evaluate_design_sufficiency(
    design: HierarchicalDesign, *, p1: float, p2: float, alpha: float = 0.05,
    target_power: float = 0.8, overprovision_ceiling: float = 0.97,
) -> DesignEvaluation:
    power = closed_form_power_two_proportions(design, p1=p1, p2=p2, alpha=alpha)
    if power < target_power:
        verdict: Verdict = "INSUFFICIENT"
    elif power > overprovision_ceiling:
        verdict = "OVERPROVISIONED"
    else:
        verdict = "SUFFICIENT"
    return DesignEvaluation(design=design, power=power, verdict=verdict)


def find_minimum_sufficient_design(
    candidate_designs: list[HierarchicalDesign], *, p1: float, p2: float, alpha: float = 0.05, target_power: float = 0.8,
) -> DesignEvaluation | None:
    """Scans candidates (already sorted or not) and returns the one with the
    FEWEST total captures that still reaches target_power -- or None if no
    candidate does. Never mutates or re-derives the paper's own protocol;
    the caller decides what to do with the answer (this module makes no
    claim about changing the frozen design automatically)."""
    sufficient = [
        DesignEvaluation(design=design, power=closed_form_power_two_proportions(design, p1=p1, p2=p2, alpha=alpha), verdict="SUFFICIENT")
        for design in candidate_designs
        if closed_form_power_two_proportions(design, p1=p1, p2=p2, alpha=alpha) >= target_power
    ]
    if not sufficient:
        return None
    return min(sufficient, key=lambda evaluation: evaluation.design.total_captures)


# ----------------------------------------------------------------------
# Normal CDF/quantile (no scipy dependency; consistent with inference.py)
# ----------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_quantile(p: float) -> float:
    from .inference import _normal_quantile as _shared_normal_quantile
    return _shared_normal_quantile(p)
