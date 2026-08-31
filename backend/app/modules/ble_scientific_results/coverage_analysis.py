"""Coverage / abstention canonical producer (2026-08-12, Scientific
Closure pass) -- Coverage audit finding: the real decision records
(OfflineInferenceService.run_decision_windows(), the SAME frozen primary-
branch/preprocessing/decision-window-rule/calibrated-threshold pipeline
RQ3 already drives) already carry everything needed to compute coverage
overall and by evaluation_domain/branch/physical_unit, but nothing
aggregated them -- this module is exactly that aggregation, real reporting,
no new methodology:

- "decided" reuses the EXACT SAME abstention definition
  `scientific_results_repository.run_confirmatory_statistical_plan`'s own
  `coverage()` call already uses: abstained iff
  `final_decision == "INSUFFICIENT_EVIDENCE"` (UNKNOWN counts as decided --
  a real classification decision, just not the target class).
- `coverage()` itself is `statistics/metrics.py`'s existing, already-tested
  function -- never a second definition, never a different threshold
  family "to make a prettier curve".
- `abstention_reason` is read verbatim from `run_decision_windows()`'s own
  output (real, machine-readable, e.g.
  "BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2") -- reported as `NOT_AVAILABLE` only
  when the source genuinely never populated one, never inferred
  retrospectively.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .statistics.metrics import coverage as _coverage


@dataclass(frozen=True)
class CoverageRow:
    decided: bool
    correct: bool | None = None
    evaluation_domain: str | None = None
    branch: str | None = None
    physical_unit_id: str | None = None
    abstention_reason: str | None = None
    # Closed-set decision-window BA/confusion/risk-coverage (2026-08-17):
    # the SAME real per-window prediction already computed by
    # run_decision_windows() -- carried here (not just distilled into
    # `correct`) so evaluate_window_level() can feed it straight into the
    # existing Evaluator.evaluate_split(), never a second metric
    # definition.
    predicted_class: str | None = None
    aggregated_probabilities: dict[str, float] | None = None
    # Methodological-audit fix (2026-08-22, item 2): the raw
    # run_decision_windows() final_decision string ("IDENTIFIED" /
    # "UNKNOWN" / "INSUFFICIENT_EVIDENCE"), carried verbatim. `decided` and
    # `correct` above intentionally conflate IDENTIFIED-and-right into a
    # single "correct" bit (by design, for their own existing consumers --
    # see this module's top docstring) -- that conflation loses whether an
    # UNKNOWN (threshold-rejected) window's own argmax would have been
    # right or wrong, which operational_coverage_breakdown() below needs.
    # This field is the one place that real distinction survives.
    final_decision: str | None = None


def coverage_row_from_decision_window(
    window: dict[str, Any], *, evaluation_domain: str | None = None, branch: str | None = None,
) -> CoverageRow:
    """Real, single-source-of-truth mapping from a real
    run_decision_windows() output row to a CoverageRow. `correct` is set
    only when the window carries BOTH a real predicted_class and a real
    physical_unit_id ground truth -- never inferred when either is
    missing."""
    decided = window.get("final_decision") != "INSUFFICIENT_EVIDENCE"
    physical_unit_id = window.get("physical_unit_id")
    correct = None
    if decided and physical_unit_id is not None:
        correct = window.get("final_decision") == "IDENTIFIED" and window.get("predicted_class") == physical_unit_id
    return CoverageRow(
        decided=decided, correct=correct, evaluation_domain=evaluation_domain, branch=branch,
        physical_unit_id=physical_unit_id, abstention_reason=window.get("abstention_reason"),
        predicted_class=window.get("predicted_class"), aggregated_probabilities=window.get("aggregated_probabilities"),
        final_decision=window.get("final_decision"),
    )


def operational_coverage_breakdown(rows: list[CoverageRow]) -> dict[str, Any]:
    """Methodological-audit fix (2026-08-22, item 2): a real, additive
    breakdown that separates what `evaluate_window_level()`'s BA/accuracy
    (and the existing `decided`/`coverage()` bucket, both of which treat
    UNKNOWN as a "decided, just wrong-class" outcome by design -- see this
    module's own top docstring) conflate together: a window the calibrated
    acceptance_threshold actually REJECTED (final_decision=="UNKNOWN") is
    an abstention from the operator's point of view, not a decision. This
    function never changes `decided`/`coverage_row_from_decision_window`'s
    existing meaning (real other consumers, e.g. RQ3's coverage() calls,
    keep exactly their current behavior) -- it is a second, explicit view
    computed from the SAME real `rows`, never a second data source.

    Argmax-correctness here is computed directly from
    `predicted_class == physical_unit_id`, independent of `final_decision`
    -- NEVER from the `correct` field above, which is only True when a row
    is BOTH IDENTIFIED and right, so it cannot by itself tell an UNKNOWN
    row's underlying argmax was correct (needed for `n_correct_rejected`)
    from one whose argmax was also wrong (`n_errors_rejected`).

    `argmax_accuracy_ignoring_threshold` reproduces exactly what
    evaluate_window_level()'s own BA/confusion-matrix already measure
    (every admissible window, IDENTIFIED or UNKNOWN, scored by its argmax
    class) -- kept here too so a reader never has to reconcile two
    differently-scoped reports by hand. `accuracy_among_identified` is the
    operationally meaningful complement: accuracy only among windows the
    system actually committed to a decision for."""
    admissible = [r for r in rows if r.final_decision != "INSUFFICIENT_EVIDENCE"]
    insufficient_evidence = [r for r in rows if r.final_decision == "INSUFFICIENT_EVIDENCE"]
    identified = [r for r in admissible if r.final_decision == "IDENTIFIED"]
    unknown = [r for r in admissible if r.final_decision == "UNKNOWN"]

    def _is_argmax_correct(row: CoverageRow) -> bool | None:
        if row.physical_unit_id is None or row.predicted_class is None:
            return None
        return row.predicted_class == row.physical_unit_id

    def _n_correct_with_gt(subset: list[CoverageRow]) -> tuple[int, int]:
        """(n_correct, n_with_ground_truth) -- never divides by a count
        that includes rows with no real ground truth to judge against."""
        verdicts = [_is_argmax_correct(r) for r in subset]
        known = [v for v in verdicts if v is not None]
        return sum(1 for v in known if v), len(known)

    n_admissible_correct, n_admissible_with_gt = _n_correct_with_gt(admissible)
    n_identified_correct, n_identified_with_gt = _n_correct_with_gt(identified)
    correct_rejected = [r for r in unknown if _is_argmax_correct(r) is True]
    errors_rejected = [r for r in unknown if _is_argmax_correct(r) is False]
    errors_accepted = [r for r in identified if _is_argmax_correct(r) is False]

    return {
        "total_admissible_windows": len(admissible),
        "n_identified": len(identified),
        "n_unknown_below_threshold": len(unknown),
        "n_insufficient_evidence": len(insufficient_evidence),
        "operational_coverage": (len(identified) / len(admissible)) if admissible else None,
        "argmax_accuracy_ignoring_threshold": (n_admissible_correct / n_admissible_with_gt) if n_admissible_with_gt else None,
        "accuracy_among_identified": (n_identified_correct / n_identified_with_gt) if n_identified_with_gt else None,
        "n_correct_rejected": len(correct_rejected),
        "n_errors_rejected": len(errors_rejected),
        "n_errors_accepted": len(errors_accepted),
    }


def evaluate_window_level(rows: list[CoverageRow], *, evaluator: Any, known_classes: list[str], domain_label: str) -> Any:
    """Closed-set decision-window BA/confusion-matrix/risk-coverage
    (2026-08-17): reuses Evaluator.evaluate_split() UNCHANGED -- the exact
    same function RQ1/RQ2 use for per-example evaluation -- just fed real
    10-second decision-window predictions instead. Only DECIDED rows with
    both a real physical_unit_id (ground truth) and predicted_class enter
    the computation, mirroring evaluate_split()'s own "comparable" filter;
    abstained/undecided windows are accounted for separately by the
    coverage bucket (`_bucket()`), never silently dropped from the overall
    counts, just excluded from this specific BA/confusion view. Returns
    None when nothing is comparable, matching Evaluator's own convention."""
    predictions = [
        {"example_id": r.physical_unit_id, "true_label": r.physical_unit_id, "predicted_label": r.predicted_class, "probabilities": r.aggregated_probabilities}
        for r in rows
        if r.decided and r.physical_unit_id is not None and r.predicted_class is not None
    ]
    if not predictions:
        return None
    return evaluator.evaluate_split(domain_label, predictions, known_classes)


def _bucket(rows: list[CoverageRow]) -> dict[str, Any] | None:
    total = len(rows)
    if total == 0:
        return None
    abstained = sum(1 for r in rows if not r.decided)
    decided_rows = [r for r in rows if r.decided]
    comparable = [r for r in decided_rows if r.correct is not None]
    errors_among_decided = sum(1 for r in comparable if not r.correct) if comparable else None
    risk_among_decided = (errors_among_decided / len(comparable)) if comparable else None
    return {
        "eligible_windows": total, "decided_windows": len(decided_rows), "abstained_windows": abstained,
        "coverage": _coverage(total, abstained), "errors_among_decided": errors_among_decided,
        "risk_among_decided": risk_among_decided,
    }


def compute_coverage_summary(rows: list[CoverageRow]) -> dict[str, Any]:
    """Real, general aggregation over already-real CoverageRows -- groups
    by whichever dimensions (evaluation_domain/branch/physical_unit) are
    actually present on the rows, never fabricates a bucket for a
    dimension nothing supplied."""
    overall = _bucket(rows)
    domains = sorted({r.evaluation_domain for r in rows if r.evaluation_domain is not None})
    branches = sorted({r.branch for r in rows if r.branch is not None})
    units = sorted({r.physical_unit_id for r in rows if r.physical_unit_id is not None})
    by_domain = {domain: _bucket([r for r in rows if r.evaluation_domain == domain]) for domain in domains}
    by_branch = {branch: _bucket([r for r in rows if r.branch == branch]) for branch in branches}
    by_unit = {unit: _bucket([r for r in rows if r.physical_unit_id == unit]) for unit in units}

    abstained_rows = [r for r in rows if not r.decided]
    abstention_reason_counts: Any
    if abstained_rows and any(r.abstention_reason is not None for r in abstained_rows):
        counts: dict[str, int] = {}
        for row in abstained_rows:
            key = row.abstention_reason or "NOT_AVAILABLE"
            counts[key] = counts.get(key, 0) + 1
        abstention_reason_counts = counts
    else:
        abstention_reason_counts = "NOT_AVAILABLE"

    return {
        "overall": overall, "by_evaluation_domain": by_domain, "by_branch": by_branch,
        "by_physical_unit": by_unit, "abstention_reason_counts": abstention_reason_counts,
    }
