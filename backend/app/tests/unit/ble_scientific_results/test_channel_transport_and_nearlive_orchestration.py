"""Fast-closure pass (2026-08-12), Phase 14/15 launcher backends:
compute_channel_transport_report/compute_offline_nearlive_report were real
and tested but had no real caller gathering real inputs -- this proves the
missing orchestration (run_channel_transport_analysis/
run_offline_nearlive_analysis), never a second scoring path (reuses
OfflineInferenceService.run() via a stub, exactly like test_rq3_frr_
analysis.py's own pattern).
"""
from __future__ import annotations

import json

import pytest

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

from ._helpers import make_example, write_capture, write_examples


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_paper_run(repo, paper_run_id: str, *, scientific_task: str = "SAME_MODEL_UNIT_IDENTIFICATION") -> None:
    run_dir = repo.root / paper_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir).joinpath("run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": paper_run_id, "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": scientific_task, "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")


def _write_rq2_primary(repo, paper_run_id: str, *, model_bundle_id: str) -> None:
    (repo._run_dir(paper_run_id) / "06_statistics").mkdir(parents=True, exist_ok=True)
    (repo._run_dir(paper_run_id) / "06_statistics" / "rq2_representation_comparison_report.json").write_text(json.dumps({
        "branches": [{"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "model_bundle_id": model_bundle_id}],
    }), encoding="utf-8")


class _StubOfflineInferenceService:
    def __init__(self, decisions_by_example_id: dict[str, dict]) -> None:
        self.decisions_by_example_id = decisions_by_example_id
        self.calls: list[dict] = []

    def run(self, *, bundle_id, examples, base_profile=None):
        self.calls.append({"bundle_id": bundle_id, "n_examples": len(examples)})
        return [self.decisions_by_example_id[e.example_id] for e in examples if e.example_id in self.decisions_by_example_id]


def test_run_channel_transport_analysis_scores_real_examples_grouped_by_channel(tmp_path):
    repo = _repo(tmp_path)
    _write_paper_run(repo, "RUN-1")
    _write_rq2_primary(repo, "RUN-1", model_bundle_id="BUNDLE-PRIMARY")

    capture = write_capture(repo.ble_root, capture_id="CAP-1", session_id="S1", physical_unit_id="UNIT-A")
    ex37 = make_example(capture=capture, index=0, physical_unit_id="UNIT-A")
    ex38 = make_example(capture=capture, index=1, physical_unit_id="UNIT-A")
    ex38 = ex38.model_copy(update={"channel": 38})
    write_examples(repo.ble_root, capture, [ex37, ex38])

    service = _StubOfflineInferenceService({
        ex37.example_id: {"example_id": ex37.example_id, "predicted_class": "UNIT-A", "final_decision": "IDENTIFIED"},
        ex38.example_id: {"example_id": ex38.example_id, "predicted_class": "UNIT-A", "final_decision": "UNKNOWN"},
    })

    report = repo.run_channel_transport_analysis(paper_run_id="RUN-1", offline_inference_service=service)

    assert service.calls[0]["bundle_id"] == "BUNDLE-PRIMARY"  # auto-resolved from the frozen PRIMARY branch
    by_channel = {row["channel"]: row for row in report["per_channel"]}
    assert set(by_channel.keys()) == {37, 38}
    assert by_channel[37]["balanced_accuracy"] == pytest.approx(1.0)

    reloaded = repo.get_channel_transport_report("RUN-1")
    assert reloaded["per_channel"] == report["per_channel"]


def test_run_channel_transport_analysis_raises_without_a_frozen_primary_rq2_branch(tmp_path):
    repo = _repo(tmp_path)
    _write_paper_run(repo, "RUN-1")
    with pytest.raises(ValueError, match="NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID"):
        repo.run_channel_transport_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}))


def test_run_channel_transport_analysis_raises_with_no_real_examples(tmp_path):
    repo = _repo(tmp_path)
    _write_paper_run(repo, "RUN-1")
    _write_rq2_primary(repo, "RUN-1", model_bundle_id="BUNDLE-PRIMARY")
    with pytest.raises(ValueError, match="NO_REAL_EXAMPLES_TO_SCORE"):
        repo.run_channel_transport_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}))


def test_run_offline_nearlive_analysis_persists_an_honest_no_data_report_with_no_real_predictions(tmp_path):
    repo = _repo(tmp_path)
    _write_paper_run(repo, "RUN-1")
    report = repo.run_offline_nearlive_analysis(paper_run_id="RUN-1")
    assert report["pairing_status"] == "NO_DATA"
    assert report["analytical_agreement"] is None
    reloaded = repo.get_offline_nearlive_report("RUN-1")
    assert reloaded["pairing_status"] == "NO_DATA"


def test_run_offline_nearlive_analysis_pairs_real_supplied_predictions(tmp_path):
    repo = _repo(tmp_path)
    _write_paper_run(repo, "RUN-1")
    report = repo.run_offline_nearlive_analysis(
        paper_run_id="RUN-1",
        offline_predictions=[{"evidence_interval_id": "e1", "predicted_class": "UNIT-A", "final_decision": "IDENTIFIED"}],
        nearlive_predictions=[{"evidence_interval_id": "e1", "predicted_class": "UNIT-A", "final_decision": "IDENTIFIED"}],
    )
    assert report["pairing_status"] == "COMPUTED_FROM_EXACT_EVIDENCE_INTERVAL_MATCH"
    assert report["matched_pair_count"] == 1
