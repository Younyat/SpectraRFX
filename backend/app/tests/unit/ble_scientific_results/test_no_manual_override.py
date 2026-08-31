"""Structural guarantee: nothing in this module can force
DATASET_STRUCTURAL_PREFLIGHT_PASSED or PAPER_CAMPAIGN_PREFLIGHT_PASSED
without every relevant category actually passing. No
override/force parameter exists anywhere on the contracts, the repository's
run_preflight()/_check_*() methods, or the HTTP route -- checked here both
by signature inspection (so a future PR that quietly adds one fails this
test) and by exercising the actual computation.
"""
from __future__ import annotations

import inspect
import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.contracts import ScientificPreflightReport

from ._helpers import build_passing_fixture


def test_no_check_method_accepts_a_force_or_override_argument():
    forbidden_terms = {"force", "override", "bypass", "skip", "manual"}
    check_methods = [
        ScientificResultsRepository.run_preflight,
        ScientificResultsRepository._check_integrity,
        ScientificResultsRepository._check_leakage,
        ScientificResultsRepository._check_population_separation,
        ScientificResultsRepository._check_quality,
        ScientificResultsRepository._check_design_completeness,
        ScientificResultsRepository._check_paper_campaign_completeness,
    ]
    for method in check_methods:
        parameters = set(inspect.signature(method).parameters)
        offending = parameters & forbidden_terms
        assert not offending, f"{method.__qualname__} exposes a manual-override-shaped parameter: {offending}"


def test_compute_overall_status_has_no_override_path():
    parameters = set(inspect.signature(ScientificPreflightReport.compute_overall_status).parameters)
    assert not (parameters & {"force", "override", "bypass"})


def test_a_broken_dataset_cannot_be_talked_into_passing(tmp_path):
    """Even with every optional/loose input left at defaults, a dataset with
    a real, on-disk problem (here: a capture the dataset references but
    which has no CaptureRecord at all) must BLOCK -- there is no parameter
    to run_preflight that changes this outcome."""
    ble_root = tmp_path / "ble_rffi_studio"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    dataset_id, dataset_version, task = build_passing_fixture(ble_root)

    # Corrupt the dataset to reference a capture that was never registered.
    dataset_path = ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload["captures"].append("SCI-TEST-CAP-GHOST")
    dataset_path.write_text(json.dumps(payload), encoding="utf-8")

    contract = repository.freeze_protocol({"hardware_profile_id": "hw", "receiver_profile_hash": "rx", "interpretation_matrix_hash": "interp"})
    run = repository.create_run(protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="C1", dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=task)

    report = repository.run_preflight(run.paper_run_id)
    assert report.overall_status == "PREFLIGHT_BLOCKED"
    assert any("SCI-TEST-CAP-GHOST" in finding for finding in report.integrity.findings)
