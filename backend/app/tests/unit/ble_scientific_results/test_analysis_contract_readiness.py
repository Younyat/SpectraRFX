"""Phase 09: Analysis Contract Readiness (2026-08-11). Not a generic JSON
editor -- get_analysis_contract_readiness() reports, per field, whether the
value is DERIVED (a real, already-frozen artifact or constant) or a genuine
SCIENTIST_DECISION (recorded only via record_scientist_decision, never
auto-decided). status is restricted to
COMPLETE/INCOMPLETE/SCIENTIST_DECISION_REQUIRED.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _field(readiness, field_id):
    return next(f for f in readiness["fields"] if f["field_id"] == field_id)


def _gate(readiness, gate_id):
    return next(g for g in readiness["readiness_gates"] if g["gate_id"] == gate_id)


def test_derived_fields_report_real_frozen_constants_on_an_empty_repository(tmp_path):
    repo = _repo(tmp_path)
    readiness = repo.get_analysis_contract_readiness()

    seeds = _field(readiness, "stochastic_seeds")
    assert seeds["kind"] == "DERIVED"
    assert seeds["status"] == "COMPLETE"
    assert seeds["value"] == [42, 137, 2024]

    window = _field(readiness, "decision_window_duration_s")
    assert window["value"] == 10.0
    assert window["status"] == "COMPLETE"

    aggregation = _field(readiness, "score_aggregation_rule")
    assert aggregation["value"] == "MEDIAN_PROBABILITY_PER_CLASS"


def test_derived_threshold_fields_are_incomplete_until_association_policy_is_frozen(tmp_path):
    repo = _repo(tmp_path)
    readiness = repo.get_analysis_contract_readiness()
    procedure = _field(readiness, "threshold_selection_procedure")
    threshold = _field(readiness, "operating_threshold_ms")
    assert procedure["status"] == "INCOMPLETE"
    assert procedure["value"] is None
    assert threshold["status"] == "INCOMPLETE"


def test_scientist_decision_fields_require_a_recorded_decision_never_auto_decided(tmp_path):
    repo = _repo(tmp_path)
    readiness = repo.get_analysis_contract_readiness()
    margin = _field(readiness, "non_inferiority_margin")
    assert margin["kind"] == "SCIENTIST_DECISION"
    assert margin["status"] == "SCIENTIST_DECISION_REQUIRED"
    assert margin["value"] is None


def test_record_scientist_decision_requires_a_real_rationale(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="RATIONALE_REQUIRED_TO_RECORD_A_SCIENTIST_DECISION"):
        repo.record_scientist_decision(
            field_id="non_inferiority_margin", selected_value=0.05, rationale="", evidence_used="pilot data",
        )


def test_record_scientist_decision_refuses_unknown_field_id(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="UNKNOWN_SCIENTIST_DECISION_FIELD"):
        repo.record_scientist_decision(
            field_id="not_a_real_field", selected_value=1, rationale="because", evidence_used="pilot data",
        )


def test_record_scientist_decision_refuses_evidence_that_cites_protected_future(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="SCIENTIST_DECISION_MUST_NOT_CITE_PROTECTED_FUTURE_TEST_AS_EVIDENCE"):
        repo.record_scientist_decision(
            field_id="non_inferiority_margin", selected_value=0.05, rationale="because",
            evidence_used="observed effect in the FUTURE holdout",
        )


def test_recorded_scientist_decision_flows_into_readiness_as_complete_with_rationale(tmp_path):
    repo = _repo(tmp_path)
    repo.record_scientist_decision(
        field_id="non_inferiority_margin", selected_value=0.05,
        rationale="Pre-registered margin based on qualification-pilot variance.",
        evidence_used="campaign_qualification_preflight_report.json", decided_by="scientist-1",
        protocol_version_candidate=1,
    )
    readiness = repo.get_analysis_contract_readiness()
    margin = _field(readiness, "non_inferiority_margin")
    assert margin["status"] == "COMPLETE"
    assert margin["value"] == 0.05
    assert margin["rationale"]


def test_a_later_decision_for_the_same_field_supersedes_the_earlier_one(tmp_path):
    repo = _repo(tmp_path)
    repo.record_scientist_decision(field_id="alpha", selected_value=0.1, rationale="first pass", evidence_used="")
    repo.record_scientist_decision(field_id="alpha", selected_value=0.05, rationale="revised after review", evidence_used="")
    readiness = repo.get_analysis_contract_readiness()
    alpha = _field(readiness, "alpha")
    assert alpha["value"] == 0.05
    assert alpha["rationale"] == "revised after review"
    assert len(repo.list_scientist_decisions(field_id="alpha")) == 2


def test_protocol_freeze_readiness_is_blocked_with_a_real_missing_list_on_an_empty_repository(tmp_path):
    repo = _repo(tmp_path)
    readiness = repo.get_analysis_contract_readiness()
    assert readiness["protocol_freeze_readiness"]["status"] == "BLOCKED"
    missing = readiness["protocol_freeze_readiness"]["missing"]
    assert "non_inferiority_margin" in missing
    assert "qualification_state" in missing
    assert "protected_future_untouched" not in missing  # untouched by default -- this gate IS satisfied


def test_readiness_gates_reflect_real_repository_state(tmp_path):
    repo = _repo(tmp_path)
    readiness = repo.get_analysis_contract_readiness()
    assert _gate(readiness, "protected_future_untouched")["status"] == "COMPLETE"
    assert _gate(readiness, "qualification_state")["status"] == "INCOMPLETE"
    assert _gate(readiness, "rq2_primary_selection")["status"] == "INCOMPLETE"
