"""Protocol-freeze close-out, point 3 (2026-08-10): CONFIRMATORY_FUTURE is a
distinct role from VALIDATION_DRY_RUN (run_confirmatory_statistical_plan)
and must reject execution unless every real gate passes: a real protocol
freeze exists, contract_sha256 is present, the dataset has a real
FUTURE_TEST holdout role, the bundle is confirmatory_eligible, and the
contract/version/hash match. Only the success-path test here actually
proceeds -- and it does so against synthetic fixture data, never a real
campaign (none exists yet); this proves the gate mechanism, not a real
confirmatory result.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.api import ScientificResultsRepository


def _confirmatory_ready_payload(**overrides) -> dict:
    payload = dict(
        protocol_id="PROTO-FUTURE-GATE", hardware_profile_id="usrp-b200-e3r04z1b2", receiver_profile_hash="rx-profile-hash",
        interpretation_matrix_hash="interp-hash-v1",
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


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def test_rejects_when_no_real_protocol_freeze_was_ever_executed(tmp_path):
    repo = _repo(tmp_path)
    repo.freeze_protocol(_confirmatory_ready_payload())  # freeze_protocol alone is NOT execute_protocol_freeze
    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-1", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=True,
        )
    assert "NO_REAL_PROTOCOL_FREEZE_EXECUTED" in str(excinfo.value)


def test_rejects_when_dataset_has_no_future_test_holdout_role(tmp_path):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    # No freeze_holdout_groups(group="FUTURE_TEST") call for this dataset.
    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-2", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=True,
        )
    assert "DATASET_HAS_NO_FUTURE_TEST_HOLDOUT_ROLE" in str(excinfo.value)


def test_rejects_when_bundle_is_not_confirmatory_eligible(tmp_path):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    repo.freeze_holdout_groups(dataset_id="DS1", dataset_version="1.0.0", group="FUTURE_TEST")

    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-3", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=False,
        )
    assert "BUNDLE_NOT_CONFIRMATORY_ELIGIBLE" in str(excinfo.value)


def test_rejects_on_a_declared_contract_sha256_mismatch(tmp_path):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    repo.freeze_holdout_groups(dataset_id="DS1", dataset_version="1.0.0", group="FUTURE_TEST")

    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-4", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=True, declared_contract_sha256="not-the-real-hash",
        )
    assert "CONTRACT_HASH_MISMATCH" in str(excinfo.value)


def test_missing_contract_sha256_is_rejected_via_dependency_injection(tmp_path, monkeypatch):
    # freeze_protocol() always computes a real contract_sha256 (see
    # test_protocol_freeze_ceremony.py) -- there is no legitimate way to
    # produce a frozen contract without one. This test confirms the future
    # gate's own defense-in-depth check by forcing get_protocol() to return
    # a contract with the field cleared, proving the gate re-checks it
    # independently rather than trusting execute_protocol_freeze blindly.
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    repo.freeze_holdout_groups(dataset_id="DS1", dataset_version="1.0.0", group="FUTURE_TEST")

    original_get_protocol = repo.get_protocol
    monkeypatch.setattr(repo, "get_protocol", lambda pid, version=None: original_get_protocol(pid, version).model_copy(update={"contract_sha256": ""}))

    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-SHA-GAP", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=True,
        )
    assert "MISSING_CONTRACT_SHA256" in str(excinfo.value)


def test_all_gates_pass_executes_and_logs_the_only_real_future_test_read(tmp_path):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    repo.freeze_holdout_groups(dataset_id="DS1", dataset_version="1.0.0", group="FUTURE_TEST")

    assert repo.list_holdout_access_log() == []
    result = repo.run_confirmatory_future_analysis(
        paper_run_id="RUN-5", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
        bundle_confirmatory_eligible=True, declared_contract_sha256=contract.contract_sha256,
        non_inferiority_differences=[0.01, -0.02, 0.0, 0.01, -0.01], non_inferiority_margin=0.1,
    )
    assert result["non_inferiority"]["status"] == "EXECUTED"

    access_log = repo.list_holdout_access_log()
    assert len(access_log) == 1
    assert "FUTURE_TEST" in access_log[0].access_path

    persisted_path = tmp_path / "sci_results" / "RUN-5" / "06_statistics" / "confirmatory_future_analysis_report.json"
    assert persisted_path.is_file()


def test_protocol_version_mismatch_between_ledger_and_loaded_contract_is_rejected(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)
    repo.freeze_holdout_groups(dataset_id="DS1", dataset_version="1.0.0", group="FUTURE_TEST")

    # Force a second, non-confirmatory-ready protocol_version to exist so
    # get_protocol(protocol_id, latest_freeze.protocol_version) still
    # resolves the FROZEN version correctly -- then corrupt the in-memory
    # ledger entry's declared protocol_version to simulate a stale/mismatched
    # reference and confirm the gate catches it.
    real_freezes = repo.list_protocol_freezes()
    assert real_freezes[-1]["protocol_version"] == contract.protocol_version

    original_get_protocol = repo.get_protocol

    def _mismatched_get_protocol(protocol_id, version=None):
        result = original_get_protocol(protocol_id, version)
        return result.model_copy(update={"protocol_version": result.protocol_version + 1})

    monkeypatch.setattr(repo, "get_protocol", _mismatched_get_protocol)
    with pytest.raises(repo.ProtocolFreezeGateError) as excinfo:
        repo.run_confirmatory_future_analysis(
            paper_run_id="RUN-6", protocol_id="PROTO-FUTURE-GATE", dataset_id="DS1", dataset_version="1.0.0",
            bundle_confirmatory_eligible=True,
        )
    assert "PROTOCOL_VERSION_MISMATCH" in str(excinfo.value)
