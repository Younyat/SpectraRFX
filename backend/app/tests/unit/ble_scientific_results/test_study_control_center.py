"""Study Control Center, Phase 1 (2026-08-11): get_study_control_center_status()
computes no science -- only real gating logic over already-real getters. These
tests prove the dependency-gated BLOCKED/READY/COMPLETE state machine against
an empty repository and against a repository with real qualification data.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _phase(status, phase_id):
    return next(p for p in status["phases"] if p["phase_id"] == phase_id)


def test_empty_repository_phase_01_is_ready_and_everything_downstream_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    assert len(status["phases"]) == 17
    assert _phase(status, "01")["state"] == "READY"
    assert _phase(status, "01")["blocking_reasons"] == []
    for phase_id in ("02", "03", "04", "17"):
        phase = _phase(status, phase_id)
        assert phase["state"] == "BLOCKED"
        assert phase["blocking_reasons"]


def test_phase_01_completes_when_qualification_report_is_ready(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "READY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    phase01 = _phase(status, "01")
    assert phase01["state"] == "COMPLETE"
    assert phase01["real_data_available"] is True
    # Phase 02 depends only on phase 01 -- now unblocked (though it will be
    # BLOCKED again itself if no physical units are registered -- that's
    # phase 02's OWN prerequisite check, not phase 01's).
    phase02 = _phase(status, "02")
    assert "Hardware Qualification" not in phase02["blocking_reasons"]


def test_phase_01_preliminary_when_qualification_report_is_preliminary(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "PRELIMINARY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    assert _phase(status, "01")["state"] == "PRELIMINARY"


def test_phase_01_blocked_when_qualification_report_is_not_ready(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "NOT_READY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    assert _phase(status, "01")["state"] == "BLOCKED"


def _write_run(repo, *, paper_run_id: str, dataset_id: str, dataset_version: str, scientific_task: str, created_at: str) -> None:
    run_dir = repo.root / paper_run_id
    (run_dir / "06_statistics").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": paper_run_id,
        "campaign_id": "TEST-CAMPAIGN", "protocol_id": "PROTO-1", "protocol_version": 1,
        "dataset_id": dataset_id, "dataset_version": dataset_version, "scientific_task": scientific_task,
        "analysis_code_commit": "deadbeef", "analysis_environment_hash": "envhash",
        "storage_path": str(run_dir), "created_at": created_at,
    }), encoding="utf-8")


def _write_split_ready(repo, *, dataset_id: str, dataset_version: str, scientific_task: str) -> None:
    path = repo.ble_root / "splits" / f"{dataset_id}__{dataset_version}__{scientific_task}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": dataset_id, "dataset_version": dataset_version,
        "scientific_task": scientific_task, "policy": "test-policy", "split_status": "READY", "assignments": [],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-17T00:00:00Z", "split_manifest_sha256": "real-hash",
    }), encoding="utf-8")


def test_phase_06_completes_when_the_latest_runs_split_is_ready(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo, paper_run_id="RUN-1", dataset_id="DS-1", dataset_version="v1", scientific_task="TARGET_VS_BACKGROUND", created_at="2026-08-17T00:00:00Z")
    status = repo.get_study_control_center_status()
    assert _phase(status, "06")["execution_state"] != "COMPLETE"  # split not built yet -- real, honest non-complete state

    _write_split_ready(repo, dataset_id="DS-1", dataset_version="v1", scientific_task="TARGET_VS_BACKGROUND")
    status = repo.get_study_control_center_status()
    phase06 = _phase(status, "06")
    assert phase06["execution_state"] == "COMPLETE"
    assert phase06["artifacts"]


def test_phase_07_completes_when_a_real_rq1_or_rq2_report_exists_for_the_latest_run(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo, paper_run_id="RUN-1", dataset_id="DS-1", dataset_version="v1", scientific_task="TARGET_VS_BACKGROUND", created_at="2026-08-17T00:00:00Z")
    _write_split_ready(repo, dataset_id="DS-1", dataset_version="v1", scientific_task="TARGET_VS_BACKGROUND")
    status = repo.get_study_control_center_status()
    assert _phase(status, "07")["execution_state"] != "COMPLETE"  # split ready, but no evaluation yet

    (repo.root / "RUN-1" / "06_statistics" / "rq1_acquisition_dependence_report.json").write_text(
        json.dumps({"ba_window": 0.9, "ba_capture": 0.8}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    assert _phase(status, "07")["execution_state"] == "COMPLETE"


def test_every_phase_reports_git_sha_and_protocol_version(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    for phase in status["phases"]:
        assert phase["git_sha"]
        assert "protocol_version" in phase


def _write_pilot_schedule(repo, *, schedule_id: str, executed_count: int, total: int) -> None:
    entries = [
        {"planned_capture_id": f"p{i}", "executed": i < executed_count, "executed_capture_id": f"CAP-{i}" if i < executed_count else None}
        for i in range(total)
    ]
    path = repo.ble_root / "paper_campaign" / "schedules" / schedule_id / "1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schedule_id": schedule_id, "qualification_only": True, "entries": entries}), encoding="utf-8")


def test_phase_04_in_progress_when_a_real_pilot_schedule_is_partially_executed(tmp_path):
    repo = _repo(tmp_path)
    _write_pilot_schedule(repo, schedule_id="PILOT-1", executed_count=1, total=4)
    status = repo.get_study_control_center_status()
    phase04 = _phase(status, "04")
    assert phase04["real_data_available"] is True
    assert phase04["state"] == "IN_PROGRESS"


def test_phase_04_complete_when_a_real_pilot_schedule_is_fully_executed(tmp_path):
    repo = _repo(tmp_path)
    _write_pilot_schedule(repo, schedule_id="PILOT-1", executed_count=4, total=4)
    status = repo.get_study_control_center_status()
    assert _phase(status, "04")["state"] == "COMPLETE"


def test_mechanism_launcher_execution_are_three_independent_states(tmp_path):
    """Normalization (2026-08-11): mechanism_state/launcher_state are never
    conflated with execution_state -- a phase whose mechanism+launcher are
    both real (READY) can still legitimately report execution_state=NOT_RUN,
    and that must never collapse into a single blended READY that could be
    misread as "already executed"."""
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    phase01 = _phase(status, "01")
    assert phase01["mechanism_state"] == "READY"
    assert phase01["launcher_state"] == "READY"
    assert phase01["execution_state"] == "NOT_RUN"

    # Fast-closure pass (2026-08-12): every phase now has a real launcher
    # -- 11 (Definitive Controlled Campaign) composes the already-real
    # Campaign Schedule + RQ3/RQ4 launchers (no duplicated acquisition/
    # scoring logic); 12 (Protected FUTURE) and 13 (Confirmatory Analysis)
    # gained their own real launchers this pass.
    for phase_id in ("11", "12", "13"):
        phase = _phase(status, phase_id)
        assert phase["mechanism_state"] == "READY"
        assert phase["launcher_state"] == "READY"


def test_operationally_closed_count_requires_both_mechanism_and_launcher_ready(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    assert status["phases_total"] == 17
    # Fast-closure pass (2026-08-12): every one of the 17 phases now has
    # both mechanism_state and launcher_state READY.
    assert status["phases_with_mechanism_and_launcher_ready"] == 17
