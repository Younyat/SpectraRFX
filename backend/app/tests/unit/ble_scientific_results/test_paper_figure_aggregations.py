"""Paper-representation pass (2026-08-17): pure aggregation helpers, no I/O,
no new science -- domain_group_counts derives distinct capture/session
counts from real SplitAssignment rows; normalize_confusion_matrix
row-normalizes an already-real confusion matrix.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.ble_scientific_results.paper_figure_aggregations import domain_group_counts, normalize_confusion_matrix


@dataclass
class _Assignment:
    capture_id: str
    session_id: str
    split: str


@dataclass
class _Split:
    assignments: list[_Assignment]


def test_domain_group_counts_counts_distinct_captures_and_sessions_not_just_windows():
    split = _Split(assignments=[
        _Assignment(capture_id="CAP-1", session_id="S1", split="VALIDATION"),
        _Assignment(capture_id="CAP-1", session_id="S1", split="VALIDATION"),  # same capture/session, another window
        _Assignment(capture_id="CAP-2", session_id="S2", split="VALIDATION"),
        _Assignment(capture_id="CAP-3", session_id="S1", split="TRAIN"),  # different domain -- excluded
    ])
    counts = domain_group_counts(split, "VALIDATION")
    assert counts == {"n_examples": 3, "n_captures": 2, "n_sessions": 2}


def test_domain_group_counts_is_all_zero_for_a_domain_with_no_assignments():
    split = _Split(assignments=[_Assignment(capture_id="CAP-1", session_id="S1", split="TRAIN")])
    assert domain_group_counts(split, "TEST") == {"n_examples": 0, "n_captures": 0, "n_sessions": 0}


def test_normalize_confusion_matrix_row_normalizes_and_keeps_n():
    matrix = {
        "A": {"A": 90, "B": 10},
        "B": {"A": 1, "B": 1},
    }
    normalized = normalize_confusion_matrix(matrix)
    assert normalized["A"]["A"] == {"pct": 90.0, "n": 90}
    assert normalized["A"]["B"] == {"pct": 10.0, "n": 10}
    # Class B's row sums to only 2 -- its pct must not be swamped by class A's much larger row.
    assert normalized["B"]["A"] == {"pct": 50.0, "n": 1}
    assert normalized["B"]["B"] == {"pct": 50.0, "n": 1}


def test_normalize_confusion_matrix_handles_a_zero_row_without_dividing_by_zero():
    matrix = {"A": {"A": 0, "B": 0}}
    normalized = normalize_confusion_matrix(matrix)
    assert normalized["A"]["A"] == {"pct": 0.0, "n": 0}
