"""Paper progress dashboard backend (2026-08-10): get_study_status(),
get_paper_readiness(), and run_paper_export() are pure reporting -- every
field is either a direct pass-through of an already-real repository method
or a presence/absence check against a real file. Nothing here computes a
new scientific value or fabricates data when an artifact is absent.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _confirmatory_ready_payload(**overrides) -> dict:
    payload = dict(
        protocol_id="PROTO-STUDY-STATUS", hardware_profile_id="usrp-b200-e3r04z1b2", receiver_profile_hash="rx-profile-hash",
        interpretation_matrix_hash="interp-hash-v1",
        rq2_primary_branch="raw_iq", rq2_branch_selection_rule="highest VALIDATION composite_score",
        rq3_primary_analysis="raw_iq", rq4_primary_analysis="raw_iq",
        rq3_reset_control_definition="PRE -> RESET -> POST vs PRE -> CONTINUOUS_POWER -> POST",
        rq4_representation_definitions={"FULL_BURST": "original window", "ADVA_EXCLUDED": "AdvA spliced out", "PRE_PDU": "preamble+AA only"},
        decision_window_duration_s=10.0, minimum_eligible_bursts=1, score_aggregation_rule="MEDIAN_PROBABILITY_PER_CLASS",
        threshold_selection_procedure="VALIDATION-only max-precision-floor scan",
        non_inferiority_margin=0.05, non_inferiority_direction="HIGHER_IS_BETTER", alpha=0.05,
        confirmatory_hypotheses=["H1"], holm_family=["H1"],
        decision_rule="reject H0 iff Holm-adjusted p <= alpha", future_test_access_policy_ref="read_group/holdout chain",
    )
    payload.update(overrides)
    return payload


def test_study_status_with_zero_real_artifacts_is_all_honest_absence(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_status()
    assert status["protocol_id"] is None
    assert status["contract_status"] == "NO_DATA"
    assert status["association_policy_status"] == "NONE"
    assert status["protected_future_test_status"] == "UNTOUCHED"
    assert status["protocol_freeze_status"] == "NOT_STARTED"
    assert status["real_capture_count"] == 0
    assert status["git_sha"]  # real, always computable in a git checkout


def test_study_status_reflects_a_real_incomplete_protocol(tmp_path):
    repo = _repo(tmp_path)
    repo.freeze_protocol(dict(
        protocol_id="PROTO-A", hardware_profile_id="hw-1", receiver_profile_hash="rx-1", interpretation_matrix_hash="interp-1",
    ))
    status = repo.get_study_status()
    assert status["protocol_id"] == "PROTO-A"
    assert status["contract_status"] == "INCOMPLETE"
    assert "rq2_primary_branch" in status["missing_confirmatory_readiness_fields"]


def test_study_status_reflects_a_real_frozen_protocol(tmp_path):
    repo = _repo(tmp_path)
    contract = repo.freeze_protocol(_confirmatory_ready_payload())
    repo.execute_protocol_freeze(contract.protocol_id)

    status = repo.get_study_status()
    assert status["contract_status"] == "FROZEN"
    assert status["protocol_freeze_status"] == "COMPLETE"
    assert status["contract_sha256"] == contract.contract_sha256


def test_paper_readiness_is_data_pending_for_everything_with_no_real_artifacts(tmp_path):
    repo = _repo(tmp_path)
    rows = repo.get_paper_readiness()
    by_element = {r["manuscript_element"]: r for r in rows}
    assert {"Qualification", "Association", "Experimental Design", "Dataset", "RQ1", "RQ2", "RQ3", "RQ4", "Coverage",
            "Sensitivity", "S1", "S2", "Provenance", "Results", "Discussion", "Conclusion"} == set(by_element.keys())
    assert by_element["RQ1"]["paper_evidence_status"] == "DATA_PENDING"
    assert by_element["RQ1"]["available"] is False
    assert by_element["RQ1"]["table_ready"] is False
    assert by_element["RQ1"]["figure_ready"] is False


def test_paper_readiness_rq1_available_but_not_confirmatory_without_a_real_freeze(tmp_path):
    repo = _repo(tmp_path)
    run_dir = tmp_path / "sci_results" / "RUN-1" / "06_statistics"
    run_dir.mkdir(parents=True)
    (run_dir / "rq1_acquisition_dependence_report.json").write_text(json.dumps({"ba_window": 0.9}), encoding="utf-8")

    rows = repo.get_paper_readiness()
    by_element = {r["manuscript_element"]: r for r in rows}
    assert by_element["RQ1"]["available"] is True
    assert by_element["RQ1"]["confirmatory"] is False  # no real protocol freeze exists
    assert by_element["RQ1"]["evidence_maturity"] == "VALIDATION"
    assert by_element["RQ1"]["paper_evidence_status"] == "PRELIMINARY"
    assert by_element["RQ1"]["table_ready"] is True  # VALIDATION dry-run tables are real, just not CONFIRMATORY


def test_paper_readiness_rq2_points_at_its_own_real_canonical_artifact(tmp_path):
    """Dashboard closure (2026-08-11): a real bug -- this row used to point
    at confirmatory_future_analysis_report.json, RQ3/RQ4/Coverage's
    artifact, never RQ2's own real canonical file
    (rq2_representation_comparison_report.json, persist_rq2_representation_
    comparison_report's output)."""
    repo = _repo(tmp_path)
    rows = repo.get_paper_readiness()
    by_element = {r["manuscript_element"]: r for r in rows}
    assert "06_statistics/rq2_representation_comparison_report.json" in by_element["RQ2"]["canonical_artifact"]

    run_dir = tmp_path / "sci_results" / "RUN-1" / "06_statistics"
    run_dir.mkdir(parents=True)
    (run_dir / "rq2_representation_comparison_report.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    rows = repo.get_paper_readiness()
    by_element = {r["manuscript_element"]: r for r in rows}
    assert by_element["RQ2"]["available"] is True


def test_run_paper_export_writes_real_study_status_and_readiness_and_skips_the_rest(tmp_path):
    repo = _repo(tmp_path)
    manifest = repo.run_paper_export()

    statuses = {e["file"]: e["status"] for e in manifest["entries"]}
    assert statuses["study_status.json"] == "GENERATED"
    assert statuses["paper_readiness.json"] == "GENERATED"
    # scientific_completeness.csv and the campaign timeline always have real content to
    # report (even "nothing available yet"), and paper_tables.tex picks up the completeness
    # section -- these three are GENERATED even on an empty repo, unlike the RQ1-4/figure
    # exports below which correctly stay SKIPPED_NO_DATA until real data exists.
    assert statuses["scientific_completeness.csv"] == "GENERATED"
    assert statuses["figures/campaign_timeline.pdf"] == "GENERATED"
    assert statuses["paper_tables.tex"] == "GENERATED"
    assert manifest["generated_count"] == 5
    assert manifest["skipped_count"] > 20  # every planned CSV/LaTeX/figure export
    assert statuses["rq1_results.csv"] == "SKIPPED_NO_DATA"
    assert statuses["figures/rq1_acquisition_dependence.pdf"] == "SKIPPED_NO_DATA"

    on_disk_status = json.loads((tmp_path / "sci_results" / "paper_exports" / "study_status.json").read_text(encoding="utf-8"))
    assert on_disk_status["contract_status"] == "NO_DATA"

    reloaded = repo.get_paper_export_manifest()
    assert reloaded == manifest


def test_run_paper_export_never_fabricates_a_csv_row(tmp_path):
    repo = _repo(tmp_path)
    repo.run_paper_export()
    for planned_csv in ("rq1_results.csv", "rq2_results.csv", "rq3_results.csv", "rq4_results.csv", "coverage_results.csv"):
        assert not (tmp_path / "sci_results" / "paper_exports" / planned_csv).exists()


def test_get_paper_export_manifest_is_none_before_any_export_runs(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_paper_export_manifest() is None
