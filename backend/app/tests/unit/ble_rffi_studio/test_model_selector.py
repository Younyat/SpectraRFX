"""Protocol-freeze close-out (2026-08-09):
select_primary_rq2_branch_from_validation picks RQ2's primary analysis
branch from real VALIDATION-only composite scores, never TEST.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.training import select_primary_rq2_branch_from_validation


def test_picks_the_branch_with_the_highest_validation_composite_score():
    scores = {"logistic_regression": 0.5, "svm_rbf": 0.6, "random_forest": 0.55, "cnn1d": 0.9, "cnn2d": 0.7, "frozen_morphological_baseline": 0.3}
    branch, rule = select_primary_rq2_branch_from_validation(scores)
    assert branch == "raw_iq"
    assert "VALIDATION" in rule


def test_engineered_rf_branch_uses_its_own_best_model_type():
    # engineered_rf covers 3 model types -- the branch's score is its best
    # member, not an average or an arbitrary pick.
    scores = {"logistic_regression": 0.4, "svm_rbf": 0.8, "random_forest": 0.5, "cnn1d": 0.2, "cnn2d": 0.1, "frozen_morphological_baseline": 0.1}
    branch, _ = select_primary_rq2_branch_from_validation(scores)
    assert branch == "engineered_rf"


def test_ties_break_alphabetically_by_branch_name():
    scores = {"cnn1d": 0.5, "cnn2d": 0.5}
    branch, _ = select_primary_rq2_branch_from_validation(scores)
    assert branch == "raw_iq"  # "raw_iq" < "stft" alphabetically


def test_rejects_empty_input():
    with pytest.raises(ValueError):
        select_primary_rq2_branch_from_validation({})


def test_rejects_input_with_no_known_model_type():
    with pytest.raises(ValueError):
        select_primary_rq2_branch_from_validation({"some_unknown_model_type": 0.9})
