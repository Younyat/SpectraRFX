"""Scientific Dashboard closure, Levels A (Experiment Health) and B (Data/
Evidence Quality) -- 2026-08-11. Both aggregations are real cross-references
over already-real getters/canonical tables: get_experiment_health_summary()
reads real PaperCampaignSchedule entries + real rejections.jsonl + real
campaign_deviations rows; get_evidence_quality_summary() groups real
capture/burst/decision-window canonical rows. Neither computes a new
scientific quantity.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_schedule(repo, *, schedule_id: str, protocol_id: str = "PROTO-1", qualification_only: bool = False) -> None:
    entries = [
        {"planned_capture_id": "p1", "physical_unit_id": "UNIT-A", "executed": True, "executed_capture_id": "CAP-1"},
        {"planned_capture_id": "p2", "physical_unit_id": "UNIT-A", "executed": False, "executed_capture_id": None},
        {"planned_capture_id": "p3", "physical_unit_id": "UNIT-B", "executed": True, "executed_capture_id": "CAP-3"},
    ]
    schedule_dir = repo.ble_root / "paper_campaign" / "schedules" / schedule_id
    schedule_dir.mkdir(parents=True, exist_ok=True)
    (schedule_dir / "1.json").write_text(json.dumps({
        "schedule_id": schedule_id, "protocol_id": protocol_id, "qualification_only": qualification_only,
        "entries": entries, "receiver_session_id": "sess-1", "frozen_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")
    rejections = [
        {"schedule_id": schedule_id, "planned_capture_id": "p2", "reason": "WRONG_UNIT"},
        {"schedule_id": schedule_id, "planned_capture_id": "p2", "reason": "WRONG_CHANNEL"},
    ]
    with (schedule_dir / "rejections.jsonl").open("w", encoding="utf-8") as handle:
        for rejection in rejections:
            handle.write(json.dumps(rejection) + "\n")


def test_get_experiment_health_summary_reports_real_block_counts_and_rejected_attempts(tmp_path):
    repo = _repo(tmp_path)
    _write_schedule(repo, schedule_id="SCHED-1")
    summary = repo.get_experiment_health_summary()

    assert summary["schema_version"] == "ble-scientific-results-experiment-health-v1"
    assert len(summary["campaigns"]) == 1
    campaign = summary["campaigns"][0]
    assert campaign["schedule_id"] == "SCHED-1"
    assert campaign["scheduled_blocks"] == 3
    assert campaign["completed_blocks"] == 2
    assert campaign["incomplete_blocks"] == 1
    assert campaign["rejected_attempt_count"] == 2  # both rejections reference p2
    assert campaign["blocks_by_physical_unit"]["UNIT-A"] == {"scheduled_blocks": 2, "completed_blocks": 1, "rejected_attempt_count": 2}
    assert campaign["blocks_by_physical_unit"]["UNIT-B"] == {"scheduled_blocks": 1, "completed_blocks": 1, "rejected_attempt_count": 0}
    assert campaign["evidence_maturity"] == "DEVELOPMENT"


def test_get_experiment_health_summary_marks_qualification_only_schedules(tmp_path):
    repo = _repo(tmp_path)
    _write_schedule(repo, schedule_id="PILOT-1", qualification_only=True)
    summary = repo.get_experiment_health_summary()
    assert summary["campaigns"][0]["evidence_maturity"] == "QUALIFICATION"


def test_get_experiment_health_summary_is_empty_and_honest_on_an_empty_repository(tmp_path):
    repo = _repo(tmp_path)
    summary = repo.get_experiment_health_summary()
    assert summary["campaigns"] == []
    assert summary["deviation_type_distribution"] == {}
    assert summary["association_policy_status"] == "NONE"
    assert summary["protected_future_test_status"] == "UNTOUCHED"


def _write_canonical_tables(repo, paper_run_id: str) -> None:
    records_dir = repo._canonical_records_dir(paper_run_id)
    records_dir.mkdir(parents=True, exist_ok=True)
    captures = [
        {"capture_id": "CAP-1", "physical_unit_id": "UNIT-A", "day_id": "2026-08-01", "experimental_role": "DEVELOPMENT", "blocking_reason_codes": [], "discontinuity_count": 0},
        {"capture_id": "CAP-2", "physical_unit_id": "UNIT-B", "day_id": "2026-08-01", "experimental_role": "DEVELOPMENT", "blocking_reason_codes": ["NO_CRC_VALID_PACKET"], "discontinuity_count": 1},
    ]
    bursts = [
        {"burst_id": "B1", "capture_id": "CAP-1", "crc_status": "VALID", "packet_eligible": True},
        {"burst_id": "B2", "capture_id": "CAP-1", "crc_status": "INVALID", "packet_eligible": False},
        {"burst_id": "B3", "capture_id": "CAP-2", "crc_status": "VALID", "packet_eligible": True},
    ]
    windows = [
        {"decision_window_id": "W1", "capture_id": "CAP-1", "window_status": "ACTIVE_ELIGIBLE", "eligible_count": 2},
        {"decision_window_id": "W2", "capture_id": "CAP-2", "window_status": "ACTIVE_INSUFFICIENT_BURSTS", "eligible_count": 0},
    ]
    deviations = [{"deviation_id": "D1", "deviation_type": "DISCONTINUITY"}]
    (records_dir / "capture_records.json").write_text(json.dumps(captures), encoding="utf-8")
    (records_dir / "burst_records.json").write_text(json.dumps(bursts), encoding="utf-8")
    (records_dir / "decision_window_records.json").write_text(json.dumps(windows), encoding="utf-8")
    (records_dir / "campaign_deviations.json").write_text(json.dumps(deviations), encoding="utf-8")


def test_get_evidence_quality_summary_returns_none_when_records_are_not_built_yet(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_evidence_quality_summary("RUN-1") is None


def test_get_evidence_quality_summary_groups_real_canonical_rows(tmp_path):
    repo = _repo(tmp_path)
    _write_canonical_tables(repo, "RUN-1")
    summary = repo.get_evidence_quality_summary("RUN-1")

    assert summary["capture_count"] == 2
    assert summary["burst_count"] == 3
    assert summary["captures_per_physical_unit"] == {"UNIT-A": 1, "UNIT-B": 1}
    assert summary["captures_per_day"] == {"2026-08-01": 2}
    assert summary["candidate_bursts_per_capture"] == {"CAP-1": 2, "CAP-2": 1}
    assert summary["crc_valid_per_capture"] == {"CAP-1": 1, "CAP-2": 1}
    assert summary["admitted_per_capture"] == {"CAP-1": 1, "CAP-2": 1}
    assert summary["exclusion_reason_counts"] == {"NO_CRC_VALID_PACKET": 1}
    assert summary["eligible_bursts_per_window"] == {"W1": 2, "W2": 0}
    assert summary["usable_windows"] == 1
    assert summary["insufficient_evidence_abstention_windows"] == 1
    assert summary["captures_with_discontinuities"] == 1
    assert summary["deviation_count"] == 1
    assert summary["physical_unit_by_capture_id"] == {"CAP-1": "UNIT-A", "CAP-2": "UNIT-B"}
