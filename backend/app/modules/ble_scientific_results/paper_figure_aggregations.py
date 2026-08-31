"""Paper-representation pass (2026-08-17): pure, no-new-science aggregation
helpers reused by BOTH the live Evidence Dashboard and the paper export
pipeline (paper_export.py / figures/paper_figures.py) -- a single source of
truth for numbers that were previously either absent or would otherwise have
been computed twice (once for the dashboard, once for the paper), which is
exactly the duplication this pass exists to remove.

Every function here operates on ALREADY-REAL, already-loaded contract
objects/dicts -- no file I/O, no statistics, no new scientific computation.
"""
from __future__ import annotations

from typing import Any


def domain_group_counts(split: Any, domain: str) -> dict[str, int]:
    """How many real ExampleRecords (burst/packet-level rows of
    SplitManifest.assignments) AND how many independent acquisition groups
    (distinct real captures, distinct real sessions) support a given split
    domain (TRAIN/VALIDATION/TEST). Nothing in the codebase counted distinct
    captures/sessions per domain before this -- `SplitManifest.assignments`
    already carries real `capture_id`/`session_id`/`split` per example
    (contracts/split.py), this only aggregates them. Matters because
    `n_examples` alone can overstate independent evidence: many examples can
    come from very few real acquisitions.

    Naming correction (2026-08-17 investigation): this field was previously
    called `n_windows`, which invited confusion with the UNRELATED
    10-second decision-window aggregation coverage_analysis.py computes
    (see rq1_acquisition_dependence_report.json's own `evaluation_unit`
    field) -- these ARE ExampleRecord counts, renamed to say so
    unambiguously."""
    assignments = [a for a in split.assignments if a.split == domain]
    return {
        "n_examples": len(assignments),
        "n_captures": len({a.capture_id for a in assignments}),
        "n_sessions": len({a.session_id for a in assignments}),
    }


def normalize_confusion_matrix(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, dict[str, float | int]]]:
    """Row-normalizes a real confusion matrix (matrix[true][predicted] ->
    count, exactly SplitEvaluationReport.confusion_matrix's own shape) by
    each true class's real total, expressing each cell as a percentage of
    that class -- so class imbalance in the underlying counts (a majority
    transmitter's row summing to thousands, a minority transmitter's row
    summing to dozens) does not visually dominate the figure. `n` is kept
    alongside `pct` in every cell, never discarded -- this is a display
    transform over already-real counts, not a new statistic; the raw-count
    matrix remains the canonical artifact."""
    normalized: dict[str, dict[str, dict[str, float | int]]] = {}
    for true_label, predicted_counts in matrix.items():
        row_total = sum(predicted_counts.values())
        normalized[true_label] = {
            predicted_label: {
                "pct": (count / row_total * 100.0) if row_total else 0.0,
                "n": count,
            }
            for predicted_label, count in predicted_counts.items()
        }
    return normalized
