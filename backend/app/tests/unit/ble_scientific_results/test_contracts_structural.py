"""Fase 1 structural tests: AnalysisContract's immutability and hashing
guarantees. Mirrors ble_rffi_studio's own test_contracts_structural.py
(same frozen/content_hash discipline, reused via inheritance from
StudioContract, so it needs the same kind of proof here)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ble_scientific_results.contracts import AnalysisContract, HoldoutAccessLogEntry, ScientificPreflightReport


def _minimal_contract(**overrides) -> AnalysisContract:
    fields = dict(
        protocol_id="PROTO-1", protocol_version=1, creation_timestamp_utc="2026-08-05T00:00:00Z",
        git_commit="abc123", git_dirty_state="CLEAN", software_environment_digest="env-hash",
        hardware_profile_id="hw-1", receiver_profile_hash="rx-hash",
        association_policy_hash="assoc-hash", quality_policy_hash="qual-hash", dataset_policy_hash="ds-hash",
        split_manifest_hash="", interpretation_matrix_hash="interp-hash",
    )
    fields.update(overrides)
    return AnalysisContract(**fields)


def test_analysis_contract_is_frozen():
    contract = _minimal_contract()
    with pytest.raises(ValidationError):
        contract.protocol_version = 2


def test_analysis_contract_content_hash_is_order_independent():
    a = _minimal_contract(device_population={"same_model_enrolled": 5, "ambient_ble": 2})
    b = _minimal_contract(device_population={"ambient_ble": 2, "same_model_enrolled": 5})
    assert a.content_hash() == b.content_hash()


def test_analysis_contract_content_hash_changes_with_content():
    a = _minimal_contract(random_seeds=[1, 2, 3])
    b = _minimal_contract(random_seeds=[1, 2, 4])
    assert a.content_hash() != b.content_hash()


def test_analysis_contract_rejects_the_falsified_five_cc2650_claim():
    with pytest.raises(ValidationError):
        _minimal_contract(primary_population="five CC2650 same-model enrolled units", primary_unit_ids=["A", "B", "C", "D", "E"])


def test_analysis_contract_accepts_the_real_heterogeneous_population():
    contract = _minimal_contract(
        primary_population="ENROLLED_HETEROGENEOUS_DEVICES",
        primary_unit_ids=["CC2541SensorTag", "SHELLY-PLUG-01", "keyfobdemo 01", "keyfobdemo 02", "CC2650-UNIT-01"],
        population_claim_boundary="Conclusions generalize only to these five enrolled transmitters, not to any device family or model population.",
    )
    assert contract.primary_population == "ENROLLED_HETEROGENEOUS_DEVICES"
    assert len(contract.primary_unit_ids) == 5


def test_analysis_contract_requires_primary_unit_ids_when_primary_population_is_declared():
    with pytest.raises(ValidationError):
        _minimal_contract(primary_population="ENROLLED_HETEROGENEOUS_DEVICES", primary_unit_ids=[])


def test_analysis_contract_rejects_an_unverified_multi_unit_same_model_claim():
    with pytest.raises(ValidationError):
        _minimal_contract(secondary_same_model_subset={"group_name": "KEYFOB", "unit_ids": ["keyfobdemo 01", "keyfobdemo 02"], "verified": False})


def test_analysis_contract_accepts_a_verified_same_model_claim_with_a_basis():
    contract = _minimal_contract(secondary_same_model_subset={
        "group_name": "KEYFOB", "unit_ids": ["keyfobdemo 01", "keyfobdemo 02"], "verified": True,
        "verification_basis": "matching hardware_revision and firmware_hash confirmed by real inspection",
    })
    assert contract.secondary_same_model_subset["verified"] is True


def test_analysis_contract_round_trips_through_json():
    contract = _minimal_contract(channels=[37, 38], device_ids=["UNIT-A", "UNIT-B"])
    payload = contract.model_dump(mode="json")
    restored = AnalysisContract.model_validate(payload)
    assert restored.content_hash() == contract.content_hash()


def test_holdout_access_log_entry_is_frozen():
    entry = HoldoutAccessLogEntry(
        sequence_number=1, previous_entry_hash=None, entry_hash="h1", analysis_contract_hash="PROTO-1", paper_run_id=None,
        actor="tester", process="pytest", access_type="READ", access_path="future_holdout", resource_id="future_holdout",
        resource_hash=None, timestamp_utc="2026-08-05T00:00:00Z", reason="unit test",
    )
    with pytest.raises(ValidationError):
        entry.reason = "changed"


def test_preflight_report_overall_status_is_two_tiered():
    from app.modules.ble_scientific_results.contracts import (
        DesignCompletenessResult,
        IntegrityCheckResult,
        LeakageCheckResult,
        PaperCampaignCompletenessResult,
        PopulationSeparationResult,
        QualityCheckResult,
    )

    structural_passed = [
        IntegrityCheckResult(status="PASSED"), LeakageCheckResult(status="PASSED"),
        PopulationSeparationResult(status="PASSED"), QualityCheckResult(status="PASSED"),
        DesignCompletenessResult(status="PASSED"),
    ]
    # Structural passes but the whole-paper campaign requirements don't (the
    # realistic case for every dataset in this repository today) -> capped
    # at the dataset-structural tier, never silently promoted to
    # paper-campaign readiness.
    campaign_blocked = PaperCampaignCompletenessResult(status="BLOCKED", findings=["days: NOT_DOCUMENTED"])
    assert ScientificPreflightReport.compute_overall_status(structural_passed, campaign_blocked) == "DATASET_STRUCTURAL_PREFLIGHT_PASSED"

    campaign_passed = PaperCampaignCompletenessResult(status="PASSED")
    assert ScientificPreflightReport.compute_overall_status(structural_passed, campaign_passed) == "PAPER_CAMPAIGN_PREFLIGHT_PASSED"

    structural_one_blocked = [
        IntegrityCheckResult(status="PASSED"), LeakageCheckResult(status="BLOCKED", findings=["leakage found"]),
        PopulationSeparationResult(status="PASSED"), QualityCheckResult(status="PASSED"),
        DesignCompletenessResult(status="PASSED"),
    ]
    # A structural failure blocks everything, even if campaign-completeness
    # itself would have passed.
    assert ScientificPreflightReport.compute_overall_status(structural_one_blocked, campaign_passed) == "PREFLIGHT_BLOCKED"
