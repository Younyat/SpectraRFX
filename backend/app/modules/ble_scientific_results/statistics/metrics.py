"""Pure, dependency-light evaluation metrics for the paper's confirmatory
analyses (RQ1-RQ4/S1/S2, see statistics/README-less docstring in
power_simulation.py for the overall ordering). Every function here takes
plain arrays/sequences and returns a plain float or a small dataclass --
none of them touch storage, a paper_run_id, or any live model. Definitions
follow standard biometric/forensic-evaluation literature (documented per
function) so results are independently checkable against a textbook, not
just against this module's own tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def balanced_accuracy(y_true: Sequence[int], y_pred: Sequence[int], labels: Sequence[int] | None = None) -> float:
    """Mean per-class recall (macro-averaged sensitivity) -- the standard
    "balanced accuracy" definition (Brodersen et al. 2010): unlike plain
    accuracy, a class with zero support does not silently drag the score
    toward the majority class. A label with zero TRUE instances is excluded
    from the mean (its recall is undefined, not zero)."""
    if len(y_true) != len(y_pred):
        raise ValueError("LENGTH_MISMATCH")
    resolved_labels = sorted(set(y_true)) if labels is None else list(labels)
    recalls = []
    for label in resolved_labels:
        support = sum(1 for actual in y_true if actual == label)
        if support == 0:
            continue
        correct = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == label and predicted == label)
        recalls.append(correct / support)
    if not recalls:
        raise ValueError("NO_SUPPORTED_LABELS")
    return sum(recalls) / len(recalls)


@dataclass(frozen=True)
class FarFrr:
    far: float
    frr: float
    false_accepts: int
    false_rejects: int
    n_target: int
    n_nontarget: int


def far_frr(y_true_is_target: Sequence[bool], accepted: Sequence[bool]) -> FarFrr:
    """FAR = false accepts / non-target trials; FRR = false rejects / target
    trials -- the standard verification-system pair (ISO/IEC 19795-1).
    `accepted[i]` is the system's ACCEPT/REJECT decision for trial i;
    `y_true_is_target[i]` is whether trial i is genuinely the target."""
    if len(y_true_is_target) != len(accepted):
        raise ValueError("LENGTH_MISMATCH")
    n_target = sum(1 for is_target in y_true_is_target if is_target)
    n_nontarget = len(y_true_is_target) - n_target
    false_rejects = sum(1 for is_target, was_accepted in zip(y_true_is_target, accepted) if is_target and not was_accepted)
    false_accepts = sum(1 for is_target, was_accepted in zip(y_true_is_target, accepted) if not is_target and was_accepted)
    return FarFrr(
        far=(false_accepts / n_nontarget) if n_nontarget else float("nan"),
        frr=(false_rejects / n_target) if n_target else float("nan"),
        false_accepts=false_accepts, false_rejects=false_rejects, n_target=n_target, n_nontarget=n_nontarget,
    )


def coverage(total: int, abstained: int) -> float:
    """Fraction of trials the system actually decided on (did not abstain)
    -- standard selective-classification coverage."""
    if total <= 0:
        raise ValueError("TOTAL_MUST_BE_POSITIVE")
    if abstained < 0 or abstained > total:
        raise ValueError("ABSTAINED_OUT_OF_RANGE")
    return (total - abstained) / total


def worst_case_error(far: float, frr: float) -> float:
    """The symmetric worst-case bound already used to report verification
    performance in this codebase's own docs -- max(FAR, FRR), never their
    average (an average hides a system that is asymmetrically bad on one
    error type)."""
    return max(far, frr)


@dataclass(frozen=True)
class EerResult:
    eer: float
    threshold: float


def eer(thresholds: Sequence[float], far_values: Sequence[float], frr_values: Sequence[float]) -> EerResult:
    """Equal Error Rate: the point on the DET curve where FAR(t) == FRR(t),
    found by linear interpolation between the two points bracketing the
    crossing. `thresholds` must be monotonically increasing, with FAR
    monotonically non-increasing and FRR monotonically non-decreasing (the
    standard DET-curve shape) -- the caller supplies the curve, this
    function only locates the crossing, matching common EER implementations
    (e.g. bob.measure, pyeer)."""
    n = len(thresholds)
    if not (n == len(far_values) == len(frr_values)) or n < 2:
        raise ValueError("NEED_AT_LEAST_TWO_MATCHED_POINTS")
    diffs = [far_values[i] - frr_values[i] for i in range(n)]
    for i in range(n - 1):
        left, right = diffs[i], diffs[i + 1]
        if left == 0:
            return EerResult(eer=(far_values[i] + frr_values[i]) / 2, threshold=thresholds[i])
        if (left > 0) != (right > 0):
            # Linear interpolation of the crossing point between i and i+1.
            span = right - left
            fraction = -left / span if span != 0 else 0.0
            crossing_far = far_values[i] + fraction * (far_values[i + 1] - far_values[i])
            crossing_frr = frr_values[i] + fraction * (frr_values[i + 1] - frr_values[i])
            crossing_threshold = thresholds[i] + fraction * (thresholds[i + 1] - thresholds[i])
            return EerResult(eer=(crossing_far + crossing_frr) / 2, threshold=crossing_threshold)
    if diffs[-1] == 0:
        return EerResult(eer=(far_values[-1] + frr_values[-1]) / 2, threshold=thresholds[-1])
    raise ValueError("FAR_FRR_CURVES_NEVER_CROSS:no equal-error point in the supplied range")


def cllr(target_llrs: Sequence[float], nontarget_llrs: Sequence[float]) -> float:
    """Log-likelihood-ratio cost (Brummer & du Preez, 2006) -- the standard
    calibration-sensitive summary used in forensic/speaker-verification
    evaluation:

        Cllr = 0.5 * ( mean_target[ log2(1 + exp(-llr)) ]
                     + mean_nontarget[ log2(1 + exp(llr)) ] )

    (equivalent to the textbook LR-domain form 0.5*(mean log2(1+1/LR) +
    mean log2(1+LR)), rewritten in the log-domain for numerical stability
    with extreme LLRs). A system outputting LLR=0 (LR=1, "uninformative")
    for every trial has the known reference value Cllr=1.0, used as this
    module's own regression fixture."""
    if not target_llrs or not nontarget_llrs:
        raise ValueError("NEED_AT_LEAST_ONE_TARGET_AND_ONE_NONTARGET_TRIAL")
    log2 = math.log(2.0)

    def _log2_1p_exp(x: float) -> float:
        # log2(1 + exp(x)), stable for large |x| (softplus in base 2).
        if x > 0:
            return (x + math.log1p(math.exp(-x))) / log2
        return math.log1p(math.exp(x)) / log2

    target_term = sum(_log2_1p_exp(-llr) for llr in target_llrs) / len(target_llrs)
    nontarget_term = sum(_log2_1p_exp(llr) for llr in nontarget_llrs) / len(nontarget_llrs)
    return 0.5 * (target_term + nontarget_term)
