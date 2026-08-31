"""P0.4 correction (2026-08-08): association_policy_hash must identify a
real, calibrated, frozen AssociationPolicy -- not evidence_stage.py's own
source-code hash -- and build_records()/freeze_protocol() must pick one up
automatically the moment a real calibration campaign ever succeeds, with no
caller needing to remember to pass one explicitly. Until then, strong
source association must stay disabled (already enforced by
STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN -- these tests verify the
NEW auto-discovery wiring around that existing gate).
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api import ScientificResultsRepository
from app.modules.ble_scientific_results.contracts import AssociationPolicy

from .test_records_and_accounting import _build_fixture_with_replay, _freeze_and_create_run, _frozen_test_policy, _new_repository


def _write_policy_result(repository, run_id: str, policy: AssociationPolicy, *, status: str = "FROZEN") -> None:
    path = repository.root / "guided_validation" / run_id / "association_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "policy_scope": "GLOBAL_POLICY", "policy": policy.model_dump(mode="json")} if status == "FROZEN" else {"status": status, "detail": "no threshold satisfied", "policy_scope": None}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_find_frozen_association_policy_returns_none_when_none_ever_calibrated(tmp_path):
    repository, _ = _new_repository(tmp_path)
    assert repository.find_frozen_association_policy() is None


def test_find_frozen_association_policy_ignores_non_frozen_attempts(tmp_path):
    repository, _ = _new_repository(tmp_path)
    _write_policy_result(repository, "GVAL-REJECTED-1", _frozen_test_policy(), status="NO_THRESHOLD_SATISFIES_CRITERIA")
    assert repository.find_frozen_association_policy() is None


def test_find_frozen_association_policy_finds_a_real_frozen_one(tmp_path):
    repository, _ = _new_repository(tmp_path)
    policy = _frozen_test_policy()
    _write_policy_result(repository, "GVAL-FROZEN-1", policy)
    found = repository.find_frozen_association_policy()
    assert found is not None
    assert found.policy_id == policy.policy_id
    assert found.policy_hash == policy.policy_hash


def test_find_frozen_association_policy_picks_the_most_recent(tmp_path):
    repository, _ = _new_repository(tmp_path)
    older = _frozen_test_policy(threshold_ms=250.0)
    older = older.model_copy(update={"frozen_at": "2026-08-01T00:00:00Z", "policy_id": "old-policy"})
    newer = _frozen_test_policy(threshold_ms=300.0)
    newer = newer.model_copy(update={"frozen_at": "2026-08-07T00:00:00Z", "policy_id": "new-policy"})
    _write_policy_result(repository, "GVAL-OLD", older)
    _write_policy_result(repository, "GVAL-NEW", newer)

    found = repository.find_frozen_association_policy()
    assert found.policy_id == "new-policy"


def test_freeze_protocol_association_policy_hash_is_self_documenting_when_uncalibrated(tmp_path):
    repository, _ = _new_repository(tmp_path)
    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    assert contract.association_policy_hash.startswith("NO_CALIBRATED_POLICY_YET:")


def test_freeze_protocol_association_policy_hash_matches_the_real_calibrated_policy_once_one_exists(tmp_path):
    repository, _ = _new_repository(tmp_path)
    policy = _frozen_test_policy()
    _write_policy_result(repository, "GVAL-FROZEN-1", policy)
    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    assert contract.association_policy_hash == policy.policy_hash
    assert not contract.association_policy_hash.startswith("NO_CALIBRATED_POLICY_YET:")


def test_build_records_auto_discovers_a_real_frozen_policy_without_the_caller_passing_one(tmp_path):
    """The real, load-bearing end-to-end check: a caller that calls
    build_records(paper_run_id) exactly as every existing caller in this
    codebase already does (guided_validation/service.py, the build-records
    job, etc.) -- passing NO association_policy -- must still get
    TARGET_ASSOCIATED_PACKET classification once a real policy is frozen,
    with zero changes to any of those callers."""
    repository, ble_root = _new_repository(tmp_path)
    dataset_id, dataset_version, task, capture_id, candidate_ids = _build_fixture_with_replay(ble_root)
    policy = _frozen_test_policy()
    _write_policy_result(repository, "GVAL-FROZEN-1", policy)
    run = _freeze_and_create_run(repository, dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    result = repository.build_records(run.paper_run_id)  # deliberately no association_policy= kwarg

    bursts = repository.list_burst_records(run.paper_run_id, limit=100)
    strong = [b for b in bursts if b["burst_class"] == "TARGET_ASSOCIATED_PACKET"]
    assert len(strong) == 1
    assert strong[0]["association_policy_hash"] == policy.policy_hash
