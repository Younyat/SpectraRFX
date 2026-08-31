"""Protocol-freeze close-out (2026-08-09): the explicit
execute_protocol_freeze() ceremony -- deliberately separate from the
flexible freeze_protocol() mechanism (test_protocol_freeze.py), which real
code (guided_validation, association calibration) already calls repeatedly
without this extra readiness gate.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.api import ScientificResultsRepository


def _base_payload(**overrides) -> dict:
    payload = dict(
        protocol_id="PAPER-PROTO-FREEZE", hardware_profile_id="usrp-b200-e3r04z1b2", receiver_profile_hash="rx-profile-hash",
        interpretation_matrix_hash="interp-hash-v1",
    )
    payload.update(overrides)
    return payload


def _confirmatory_ready_payload(**overrides) -> dict:
    payload = _base_payload(
        rq2_primary_branch="raw_iq", rq2_branch_selection_rule="highest VALIDATION composite_score",
        rq3_primary_analysis="raw_iq", rq4_primary_analysis="raw_iq",
        rq3_reset_control_definition="PRE -> RESET -> POST vs PRE -> CONTINUOUS_POWER -> POST",
        rq4_representation_definitions={"FULL_BURST": "original window", "ADVA_EXCLUDED": "AdvA spliced out", "PRE_PDU": "preamble+AA only"},
        decision_window_duration_s=10.0, minimum_eligible_bursts=1, score_aggregation_rule="MEDIAN_PROBABILITY_PER_CLASS",
        threshold_selection_procedure="VALIDATION-only max-precision-floor scan",
        non_inferiority_margin=0.05, non_inferiority_direction="HIGHER_IS_BETTER", alpha=0.05,
        confirmatory_hypotheses=["H_RQ4_full_burst_vs_pre_pdu"], holm_family=["H_RQ4_full_burst_vs_pre_pdu"],
        decision_rule="reject H0 iff Holm-adjusted p <= alpha and non-inferiority CI excludes the margin",
        future_test_access_policy_ref="ScientificResultsRepository.read_group/HoldoutAccessLogEntry chain",
    )
    payload.update(overrides)
    return payload


def test_freeze_protocol_computes_a_real_contract_sha256(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_base_payload())
    assert contract.contract_sha256
    reloaded = repository.get_protocol(contract.protocol_id)
    assert reloaded.contract_sha256 == contract.contract_sha256


def test_execute_protocol_freeze_rejects_missing_confirmatory_fields(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_base_payload())
    missing = repository.missing_confirmatory_readiness_fields(contract)
    assert "rq2_primary_branch" in missing
    assert "non_inferiority_margin" in missing

    with pytest.raises(ValueError) as excinfo:
        repository.execute_protocol_freeze(contract.protocol_id)
    assert "PROTOCOL_FREEZE_MISSING_REQUIRED_FIELDS" in str(excinfo.value)


def test_execute_protocol_freeze_succeeds_when_confirmatory_ready(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_confirmatory_ready_payload())
    assert repository.missing_confirmatory_readiness_fields(contract) == []

    entry = repository.execute_protocol_freeze(contract.protocol_id)
    assert entry["protocol_id"] == contract.protocol_id
    assert entry["contract_sha256"] == contract.contract_sha256

    ledger = repository.list_protocol_freezes()
    assert len(ledger) == 1


def test_execute_protocol_freeze_refuses_silent_refreeze_without_a_reason(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract = repository.freeze_protocol(_confirmatory_ready_payload())
    repository.execute_protocol_freeze(contract.protocol_id)

    with pytest.raises(ValueError) as excinfo:
        repository.execute_protocol_freeze(contract.protocol_id)
    assert "PROTOCOL_VERSION_CONFLICT" in str(excinfo.value)


def test_execute_protocol_freeze_allows_a_new_version_with_an_explicit_reason(tmp_path):
    repository = ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")
    contract_v1 = repository.freeze_protocol(_confirmatory_ready_payload())
    repository.execute_protocol_freeze(contract_v1.protocol_id)

    contract_v2 = repository.freeze_protocol(_confirmatory_ready_payload(non_inferiority_margin=0.08))
    assert contract_v2.protocol_version == 2

    entry = repository.execute_protocol_freeze(contract_v2.protocol_id, new_version_reason="Recalibrated non-inferiority margin after pilot review")
    assert entry["protocol_version"] == 2
    assert entry["is_new_version_of"] == 1

    ledger = repository.list_protocol_freezes()
    assert len(ledger) == 2
    # The first freeze's own ledger entry is untouched.
    assert ledger[0]["protocol_version"] == 1
