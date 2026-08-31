"""RQ1 -- acquisition-dependence diagnostic (2026-08-09). Compares the same
trained model's accuracy across three tiers of evaluation-window relatedness
to TRAIN, to measure how much of an apparent score is "optimism" from
incidental acquisition context rather than real device discrimination:

    BA_window  -- deliberately capture-dependent (SplitBuilder.
                  build_rq1_dependence_diagnostic's held-out examples come
                  from the SAME session/capture as TRAIN).
    BA_capture -- the normal confirmatory VALIDATION accuracy (capture-
                  disjoint, same as every other split in this project).
    BA_future  -- accuracy on a protected future acquisition period, once one
                  exists. NOT_YET_AVAILABLE (never a fabricated number) until
                  a real protected-future SplitEvaluationReport is supplied.

This module never computes predictions itself -- it composes
SplitEvaluationReport objects the caller already produced via
Evaluator.evaluate_split() against the SAME frozen model, and is
NON_CONFIRMATORY by construction (RQ1_ONLY): never used to select a model,
calibrate a threshold, or report a paper result on its own.
"""
from __future__ import annotations

from dataclasses import dataclass

from .evaluator import SplitEvaluationReport

BA_FUTURE_NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"


@dataclass
class Rq1AcquisitionDependenceReport:
    scientific_task: str
    ba_window: float | None
    ba_window_n_comparable: int
    ba_capture: float | None
    ba_capture_n_comparable: int
    ba_future: float | None
    ba_future_status: str  # "EXECUTED" | "NOT_YET_AVAILABLE"
    ba_future_n_comparable: int | None = None
    # delta_dependence = BA_window - BA_capture: how much of the apparent
    # score is optimism from evaluating on capture-dependent windows.
    # delta_future = BA_future - BA_capture: how much the score degrades on
    # a genuinely later, protected acquisition period. None whenever the
    # corresponding BA is unavailable -- never a fabricated difference.
    delta_dependence: float | None = None
    delta_future: float | None = None


def evaluate_rq1_acquisition_dependence(
    *, scientific_task: str, window_report: SplitEvaluationReport, capture_report: SplitEvaluationReport,
    future_report: SplitEvaluationReport | None = None,
) -> Rq1AcquisitionDependenceReport:
    """`window_report` must come from evaluating predictions against the
    RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC split's VALIDATION role (BA_window);
    `capture_report` from the normal CONFIRMATORY split's VALIDATION
    (BA_capture); `future_report`, when supplied, from a real protected
    future-period evaluation (BA_future) -- never fabricated when absent.

    Coherence-audit fix (2026-08-19): "BA" means Balanced Accuracy
    everywhere else in this codebase (RQ2, coverage_analysis, sensitivity
    all read SplitEvaluationReport.balanced_accuracy) -- and for exactly
    the reason SplitEvaluationReport's own docstring gives: plain accuracy
    can look excellent on an imbalanced/session-confounded split while
    hiding that one class is essentially never recalled (real example:
    keyfobdemo 02's TEST recall is ~0.006 on this exact closed-set, invisible
    in raw accuracy). This function alone read `.accuracy` instead of
    `.balanced_accuracy` -- confirmed via an audit that found RQ1's
    capture-disjoint VALIDATION figure (0.749, raw accuracy) silently
    disagreeing with RQ2's PRIMARY branch VALIDATION figure (0.634, real
    balanced_accuracy) despite both reading the exact same predictions.json
    for the exact same training run over the exact same 2203 VALIDATION
    examples (verified by hashing the two real example_id sets -- identical).
    The bootstrap CIs (uncertainty_ci.ba_*_ci) were never affected -- they
    were already computed via bootstrap_balanced_accuracy_ci(), correctly."""
    ba_window, ba_capture = window_report.balanced_accuracy, capture_report.balanced_accuracy
    ba_future = future_report.balanced_accuracy if future_report is not None else None
    return Rq1AcquisitionDependenceReport(
        scientific_task=scientific_task,
        ba_window=ba_window, ba_window_n_comparable=window_report.n_comparable_to_known_classes,
        ba_capture=ba_capture, ba_capture_n_comparable=capture_report.n_comparable_to_known_classes,
        ba_future=ba_future,
        ba_future_status="EXECUTED" if future_report is not None else BA_FUTURE_NOT_YET_AVAILABLE,
        ba_future_n_comparable=future_report.n_comparable_to_known_classes if future_report is not None else None,
        delta_dependence=(ba_window - ba_capture) if ba_window is not None and ba_capture is not None else None,
        delta_future=(ba_future - ba_capture) if ba_future is not None and ba_capture is not None else None,
    )


def rq1_report_to_dict(report: Rq1AcquisitionDependenceReport) -> dict:
    return {
        "scientific_task": report.scientific_task,
        "ba_window": report.ba_window, "ba_window_n_comparable": report.ba_window_n_comparable,
        "ba_capture": report.ba_capture, "ba_capture_n_comparable": report.ba_capture_n_comparable,
        "ba_future": report.ba_future, "ba_future_status": report.ba_future_status,
        "ba_future_n_comparable": report.ba_future_n_comparable,
        "delta_dependence": report.delta_dependence, "delta_future": report.delta_future,
    }
