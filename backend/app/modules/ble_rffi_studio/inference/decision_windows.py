"""Real decision windows (2026-08-08): the missing piece
ble_scientific_results/records/decision_window_records.py explicitly left
for a later phase ("No score/threshold/predicted_class/model decision field
exists on this record -- that is Fase 3+ territory... explicitly out of
scope here. minimum_eligible_bursts is the only knob a future phase needs to
turn into a real gate (window_score = median(burst_scores)), left as a plain
parameter, not implemented.").

This is that gate, implemented against ble_rffi_studio's own real, frozen,
already-trained bundles -- never a second training/scoring system.
group_examples_into_windows() uses the SAME time-window formula as
decision_window_records.py (sample_start // (window_duration_s *
sample_rate_hz)) so a window means the same thing in both places; duplicated
rather than imported to keep this module's only dependency on
ble_scientific_results at zero (matching this codebase's existing
convention of small, intentional constant/formula duplication over
cross-module coupling -- see _BLE_CHANNEL_FREQUENCIES_HZ).
"""
from __future__ import annotations

from typing import Any

import numpy as np

# Coverage/risk-coverage correction (2026-08-08): leaf, dependency-light
# primitive with no production caller before this -- see evaluator.py for
# why a plain module-level import of ble_scientific_results.statistics is
# safe (those modules import nothing ble_rffi_studio-adjacent).
from app.modules.ble_scientific_results.statistics.metrics import coverage

from ..contracts import ExampleRecord

DEFAULT_WINDOW_DURATION_S = 10.0
DEFAULT_MINIMUM_ELIGIBLE_BURSTS = 1
# Declared, frozen aggregation rule -- median is robust to a single outlier
# burst (e.g. one misclassified due to a decode artifact) without needing any
# fitted/learned combination weights. Never changed silently: a different
# rule is a new, separately-named constant, not an edit to this one's
# meaning, matching the same "profile_id is immutable once used" invariant
# preprocessing/base_preprocessing_registry.py already documents.
AGGREGATION_RULE = "MEDIAN_PROBABILITY_PER_CLASS"


def group_examples_into_windows(examples: list[ExampleRecord], window_duration_s: float) -> dict[tuple[str, int], list[ExampleRecord]]:
    windows: dict[tuple[str, int], list[ExampleRecord]] = {}
    for example in examples:
        window_samples = int(round(window_duration_s * example.sample_rate_sps))
        if window_samples <= 0:
            continue
        window_index = example.iq_start_sample // window_samples
        windows.setdefault((example.capture_id, window_index), []).append(example)
    return windows


def aggregate_window_probabilities(burst_decisions: list[dict[str, Any]], label_classes: list[str]) -> dict[str, float]:
    """Per-class median probability across the window's scored bursts,
    renormalized to sum to 1 (the median of several points on a probability
    simplex is not itself guaranteed to lie on the simplex)."""
    import numpy as np

    matrix = np.array([[d["probabilities"].get(cls, 0.0) for cls in label_classes] for d in burst_decisions])
    medians = np.median(matrix, axis=0)
    total = float(medians.sum())
    if total <= 0:
        return {cls: 0.0 for cls in label_classes}
    return {cls: float(value / total) for cls, value in zip(label_classes, medians)}


def decision_window_coverage(window_decisions: list[dict[str, Any]]) -> float:
    """Real selective-classification coverage over a set of
    run_decision_windows() results: the fraction that reached a real
    decision (IDENTIFIED/UNKNOWN) rather than abstaining
    (INSUFFICIENT_EVIDENCE) -- the coverage half of the risk-coverage
    tradeoff (see evaluator.py's SplitEvaluationReport.risk_coverage for the
    risk half, computed over individual burst predictions)."""
    if not window_decisions:
        raise ValueError("NEED_AT_LEAST_ONE_WINDOW_DECISION")
    abstained = sum(1 for d in window_decisions if d["final_decision"] == "INSUFFICIENT_EVIDENCE")
    return coverage(len(window_decisions), abstained)
