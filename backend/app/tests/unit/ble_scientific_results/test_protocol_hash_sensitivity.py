"""Fase 1 closure item A.2: proves StudioContract's inherited canonical-hash
machinery genuinely covers every field of AnalysisContract the user asked
to verify -- not just the ones exercised incidentally by other tests. Each
case builds two otherwise-identical contracts differing in exactly one
field and asserts content_hash() differs; a field that silently didn't
participate in the hash (e.g. because of a typo excluding it, or a field
pydantic dropped) would make its case fail here first.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.contracts import AnalysisContract


def _base_contract(**overrides) -> AnalysisContract:
    fields = dict(
        protocol_id="PROTO-HASH-TEST", protocol_version=1, creation_timestamp_utc="2026-08-05T00:00:00Z",
        git_commit="abc123", git_dirty_state="CLEAN", software_environment_digest="env-hash",
        hardware_profile_id="hw-1", receiver_profile_hash="rx-hash-A",
        device_population={"same_model_enrolled": 5}, campaign_schedule={"days": 3},
        intervention_schedule={"arms": ["reset", "control"]}, content_variants=["FULL_BURST_UNMASKED"],
        association_policy_hash="assoc-hash-A", quality_policy_hash="qual-hash-A", dataset_policy_hash="ds-hash-A",
        split_manifest_hash="split-hash-A", model_branch_definitions=[{"branch": "cnn1d"}],
        random_seeds=[1, 2, 3], effect_thresholds={"h1": 0.05}, non_inferiority_margins={"h3b": 0.02},
        multiplicity_family={"family": "confirmatory"}, interpretation_matrix_hash="interp-hash-A",
    )
    fields.update(overrides)
    return AnalysisContract(**fields)


HASH_SENSITIVE_FIELD_CASES = [
    ("receiver_profile_hash", "rx-hash-B"),
    ("device_population", {"same_model_enrolled": 6}),
    ("campaign_schedule", {"days": 4}),
    ("intervention_schedule", {"arms": ["reset"]}),
    ("content_variants", ["PRE_PDU_PRIMARY"]),
    ("association_policy_hash", "assoc-hash-B"),
    ("quality_policy_hash", "qual-hash-B"),
    ("split_manifest_hash", "split-hash-B"),
    ("model_branch_definitions", [{"branch": "cnn2d"}]),
    ("random_seeds", [1, 2, 4]),
    ("effect_thresholds", {"h1": 0.10}),
    ("non_inferiority_margins", {"h3b": 0.05}),
    ("multiplicity_family", {"family": "exploratory"}),
    ("interpretation_matrix_hash", "interp-hash-B"),
]


@pytest.mark.parametrize("field_name,changed_value", HASH_SENSITIVE_FIELD_CASES, ids=[c[0] for c in HASH_SENSITIVE_FIELD_CASES])
def test_content_hash_changes_when_field_changes(field_name, changed_value):
    baseline = _base_contract()
    changed = _base_contract(**{field_name: changed_value})
    assert baseline.content_hash() != changed.content_hash(), f"content_hash() did not change when {field_name} changed -- field is not covered by canonical hashing."


def test_content_hash_is_stable_for_identical_contracts():
    a = _base_contract()
    b = _base_contract()
    assert a.content_hash() == b.content_hash()


def test_dict_field_hash_is_key_order_independent():
    a = _base_contract(device_population={"same_model_enrolled": 5, "ambient_ble": 2})
    b = _base_contract(device_population={"ambient_ble": 2, "same_model_enrolled": 5})
    assert a.content_hash() == b.content_hash()


def test_list_field_hash_is_order_sensitive_by_design():
    """Lists are NOT treated as order-independent sets -- for something like
    random_seeds, order can be experimentally meaningful (e.g. seed
    assignment to restart index), so canonicalization must never silently
    discard that information. This is a deliberate design choice, not an
    oversight: no list field in AnalysisContract is assumed order-
    insensitive without the user specifying which ones are."""
    a = _base_contract(random_seeds=[1, 2, 3])
    b = _base_contract(random_seeds=[3, 2, 1])
    assert a.content_hash() != b.content_hash()


def test_timestamp_canonicalization_utc_offset_equals_z_suffix():
    a = _base_contract(creation_timestamp_utc="2026-08-05T00:00:00Z")
    b = _base_contract(creation_timestamp_utc="2026-08-05T00:00:00+00:00")
    assert a.creation_timestamp_utc == b.creation_timestamp_utc == "2026-08-05T00:00:00Z"
    assert a.content_hash() == b.content_hash()


@pytest.mark.parametrize("field_name", [
    "protocol_id", "git_commit", "hardware_profile_id", "receiver_profile_hash",
    "association_policy_hash", "quality_policy_hash", "dataset_policy_hash", "interpretation_matrix_hash",
])
def test_confirmatory_field_rejects_empty_string(field_name):
    with pytest.raises(ValueError):
        _base_contract(**{field_name: ""})


def test_split_manifest_hash_may_legitimately_be_empty_at_protocol_freeze_time():
    # Not a confirmatory field at protocol-freeze granularity -- it is
    # attached once a concrete dataset/split is chosen, per
    # freeze_protocol()'s own documented design.
    contract = _base_contract(split_manifest_hash="")
    assert contract.split_manifest_hash == ""
