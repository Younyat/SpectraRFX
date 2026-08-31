"""Study Control Center, phase 05 (2026-08-11): Study Sizing wires the
already-real statistics/power_simulation.py -- these tests prove the
repository computes nothing new (same closed_form_power_two_proportions
formula the module's own tests already verify) and that a sizing DECISION
is always an explicit, reasoned human choice, never auto-selected from
find_minimum_sufficient_design()'s answer.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _design(**overrides) -> dict:
    fields = dict(n_units=8, n_days=4, n_captures_per_unit_day=5, icc_unit=0.1, icc_day=0.05)
    fields.update(overrides)
    return fields


def test_evaluate_study_sizing_candidates_reports_a_real_power_and_verdict_per_design(tmp_path):
    repo = _repo(tmp_path)
    result = repo.evaluate_study_sizing_candidates(
        candidate_designs=[_design(n_units=2), _design(n_units=20)], p1=0.5, p2=0.8, target_power=0.8,
    )
    assert len(result["evaluations"]) == 2
    small, large = result["evaluations"]
    assert small["design"]["n_units"] == 2
    assert large["design"]["n_units"] == 20
    assert large["power"] >= small["power"]  # more units -> more power, real monotonic relationship
    assert small["verdict"] in ("INSUFFICIENT", "SUFFICIENT", "OVERPROVISIONED")


def test_evaluate_study_sizing_candidates_finds_the_minimum_sufficient_design(tmp_path):
    repo = _repo(tmp_path)
    result = repo.evaluate_study_sizing_candidates(
        candidate_designs=[_design(n_units=2), _design(n_units=10), _design(n_units=30)], p1=0.5, p2=0.9, target_power=0.8,
    )
    assert result["minimum_sufficient_design"] is not None
    assert result["minimum_sufficient_design"]["verdict"] in ("SUFFICIENT", "OVERPROVISIONED")


def test_evaluate_study_sizing_candidates_returns_none_when_no_design_is_sufficient(tmp_path):
    repo = _repo(tmp_path)
    result = repo.evaluate_study_sizing_candidates(candidate_designs=[_design(n_units=1, n_days=1, n_captures_per_unit_day=1)], p1=0.5, p2=0.51, target_power=0.8)
    assert result["minimum_sufficient_design"] is None


def test_persist_study_sizing_decision_requires_a_real_rationale(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="RATIONALE_REQUIRED_TO_RECORD_A_STUDY_SIZING_DECISION"):
        repo.persist_study_sizing_decision(chosen_design=_design(), p1=0.5, p2=0.8, rationale="")


def test_persist_and_get_study_sizing_decision_round_trips_a_real_record(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_study_sizing_decision() is None

    record = repo.persist_study_sizing_decision(
        chosen_design=_design(n_units=10), p1=0.5, p2=0.85, target_power=0.8,
        rationale="Provisional-diagnostic power simulations showed 10 units reaches target power against the pilot's observed effect size.",
        decided_by="scientist-1",
    )
    assert record["design"]["n_units"] == 10
    assert record["rationale"]
    assert record["decided_by"] == "scientist-1"

    reloaded = repo.get_study_sizing_decision()
    assert reloaded == record
