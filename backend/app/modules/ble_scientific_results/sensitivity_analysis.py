"""Sensitivity canonical producer (2026-08-12, Scientific Closure pass).
Consolidates the three real sensitivity mechanisms this study already
defines -- enrolled-population class-exclusion metric sensitivity
(statistics/sensitivity.py, wired since 2026-08-09; renamed 2026-08-22
from its original, overstated "leave-one-device-out" name -- the model is
never retrained without the excluded class, only the aggregate metric is
recomputed post-hoc), offset-retaining preprocessing
(StudioRepository.train_offset_retaining_sensitivity, closed this pass),
and RQ2's seed variability (already computed and persisted on the RQ2
canonical report -- REUSED here, never recomputed) -- into one report that
explicitly separates PRIMARY from every SENSITIVITY variant, so a
sensitivity estimate is never mistaken for the confirmatory result. No new
model selection, no new threshold choice, never opens FUTURE.
"""
from __future__ import annotations

from typing import Any, Sequence

from .statistics.metrics import balanced_accuracy as _balanced_accuracy
from .statistics.sensitivity import ClassExclusionSensitivityResult


def full_set_balanced_accuracy(predictions: list[dict[str, Any]], known_classes: Sequence[str]) -> float | None:
    """The SAME balanced_accuracy() definition every other confirmatory
    metric in this package uses, computed with NO class excluded -- the
    real baseline enrolled_population_class_exclusion_sensitivity's own
    delta_vs_full_set is measured against."""
    comparable = [p for p in predictions if p["true_label"] in known_classes]
    if not comparable:
        return None
    try:
        return _balanced_accuracy([p["true_label"] for p in comparable], [p["predicted_label"] for p in comparable], labels=list(known_classes))
    except ValueError:
        return None


def enrich_class_exclusion_with_delta_vs_full_set(
    class_exclusion_results: list[ClassExclusionSensitivityResult], *, full_set_ba: float | None,
) -> list[dict[str, Any]]:
    """Real per-omitted-unit delta vs the full-set estimate -- a plain
    diff of two already-computed balanced_accuracy values, never a new
    statistic. `coverage` is honestly None:
    enrolled_population_class_exclusion_sensitivity() operates on
    Evaluator.evaluate_split()-shaped predictions, which never apply the
    calibrated acceptance_threshold/abstention rule (that only happens in
    the decision-window inference path -- see coverage_analysis.py)."""
    rows = []
    for result in class_exclusion_results:
        delta = None
        if full_set_ba is not None and result.balanced_accuracy_value is not None:
            delta = result.balanced_accuracy_value - full_set_ba
        rows.append({
            "omitted_physical_unit": result.excluded_device_id, "estimate": result.balanced_accuracy_value,
            "accuracy": result.accuracy, "n_comparable": result.n_comparable, "coverage": None,
            "delta_vs_full_set": delta,
        })
    return rows
