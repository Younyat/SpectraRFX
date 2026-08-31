"""Scientific Reporting & Paper Closure Layer, point A (2026-08-11):
persist_rq2_representation_comparison_report is the ONLY place that writes
per-branch representation-comparison metrics to a canonical, disk-persisted
artifact. It computes nothing itself -- select_primary_rq2_branch_from_validation()
and Evaluator.evaluate_split() already compute everything a branch entry
carries; this method only validates real branch/analysis_role identity and
persists verbatim, so dashboard/CSV/LaTeX/figures all read one source.
"""
from __future__ import annotations

import json

import pytest
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _real_branch_results():
    return [
        {"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "balanced_accuracy": 0.91, "macro_f1": 0.89, "coverage": 0.97, "model_bundle_id": "BUNDLE-RAW-IQ"},
        {"branch": "engineered_rf", "analysis_role": "SENSITIVITY", "evaluation_domain": "VALIDATION", "balanced_accuracy": 0.84, "macro_f1": 0.80, "coverage": 1.0, "model_bundle_id": "BUNDLE-RF"},
        {"branch": "stft", "analysis_role": "UNSELECTED", "evaluation_domain": "VALIDATION"},
    ]


def test_persists_a_real_canonical_artifact_with_every_required_linking_field(tmp_path):
    repo = _repo(tmp_path)
    artifact = repo.persist_rq2_representation_comparison_report(
        paper_run_id="RUN-RQ2-1", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
        branch_results=_real_branch_results(),
    )
    for required_field in ("protocol_id", "protocol_version", "contract_sha256", "git_sha", "dataset_id", "dataset_version", "split_manifest_id", "split_manifest_sha256", "branches", "generated_at", "evaluation_unit", "evidence_status"):
        assert required_field in artifact, required_field
    assert len(artifact["branches"]) == 3
    primary = next(b for b in artifact["branches"] if b["analysis_role"] == "PRIMARY")
    assert primary["branch"] == "raw_iq"
    assert primary["balanced_accuracy"] == 0.91
    # Figure/artifact sync closure (2026-08-18): same real field, read
    # directly by the figure generator/figure_manifest.json.
    assert artifact["evaluation_unit"] == "EXAMPLE_RECORD"
    assert artifact["evidence_status"] == "DEVELOPMENT"


def test_persisted_artifact_round_trips_from_disk(tmp_path):
    repo = _repo(tmp_path)
    repo.persist_rq2_representation_comparison_report(
        paper_run_id="RUN-RQ2-2", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
        branch_results=_real_branch_results(),
    )
    path = tmp_path / "sci_results" / "RUN-RQ2-2" / "06_statistics" / "rq2_representation_comparison_report.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert len(on_disk["branches"]) == 3

    reloaded = repo.get_rq2_representation_comparison_report("RUN-RQ2-2")
    assert reloaded == on_disk
    assert repo.get_rq2_representation_comparison_report("RUN-NEVER-RAN") is None


def test_missing_required_branch_identity_field_is_rejected_not_defaulted(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="RQ2_BRANCH_RESULT_MISSING_REQUIRED_FIELDS"):
        repo.persist_rq2_representation_comparison_report(
            paper_run_id="RUN-RQ2-3", protocol_id="PROTO-1", protocol_version=1, contract_sha256="hash",
            dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
            branch_results=[{"branch": "raw_iq", "evaluation_domain": "VALIDATION"}],  # missing analysis_role
        )


def test_unknown_branch_name_is_rejected(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="RQ2_UNKNOWN_BRANCH"):
        repo.persist_rq2_representation_comparison_report(
            paper_run_id="RUN-RQ2-4", protocol_id="PROTO-1", protocol_version=1, contract_sha256="hash",
            dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
            branch_results=[{"branch": "not_a_real_branch", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION"}],
        )


def test_invalid_analysis_role_is_rejected(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="RQ2_INVALID_ANALYSIS_ROLE"):
        repo.persist_rq2_representation_comparison_report(
            paper_run_id="RUN-RQ2-5", protocol_id="PROTO-1", protocol_version=1, contract_sha256="hash",
            dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
            branch_results=[{"branch": "raw_iq", "analysis_role": "BEST", "evaluation_domain": "VALIDATION"}],
        )


def test_optional_metrics_absent_stay_absent_never_fabricated(tmp_path):
    repo = _repo(tmp_path)
    artifact = repo.persist_rq2_representation_comparison_report(
        paper_run_id="RUN-RQ2-6", protocol_id="PROTO-1", protocol_version=1, contract_sha256="hash",
        dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
        branch_results=[{"branch": "coarse_morphology", "analysis_role": "UNSELECTED", "evaluation_domain": "VALIDATION"}],
    )
    branch = artifact["branches"][0]
    assert branch.get("balanced_accuracy") is None
    assert branch.get("model_bundle_id") is None
