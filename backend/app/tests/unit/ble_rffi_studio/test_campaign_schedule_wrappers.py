"""Study Control Center, phases 04/06/07 (2026-08-11): StudioRepository's
paper-campaign-schedule wrappers over the already-tested PaperCampaignRunner
(see test_paper_campaign_runner.py). The one genuinely new piece these
wrappers add is `_rebuild_capture_record_with_schedule_metadata` -- proving
that the CaptureRecord returned after a scheduled capture actually carries
the schedule's declared day_id/pre_or_post/intervention_arm (not just the
raw manifest, which PaperCampaignRunner itself already tests).
"""
from __future__ import annotations

import json

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository

def _entry(**overrides) -> dict:
    fields = dict(
        planned_capture_id="planned-1", protocol_id="PROTO-1", day_id="DAY-1", campaign_period="qualification",
        physical_unit_id="UNIT-A", capture_order=1, pre_or_post="PRE", intervention_arm="CONTROL",
        packet_condition="ORIGINAL", channel=37, receiver_epoch="EPOCH-1",
    )
    fields.update(overrides)
    return fields


class _StubOrchestrator:
    """Mimics the real CampaignOrchestrator.run_session() closely enough for
    this test: writes a real capture_manifest.json and builds the FIRST
    CaptureRecord (before schedule metadata is applied), exactly what real
    hardware capture does internally."""

    def __init__(self, repository: StudioRepository, capture_id: str) -> None:
        self.repository = repository
        self.capture_id = capture_id
        self.calls: list[dict] = []

    def run_session(self, **kwargs):
        self.calls.append(kwargs)
        capture_dir = self.repository.legacy_capture_root / self.capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "capture_id": self.capture_id, "experimental_metadata": {"session_id": f"S-{self.capture_id}"},
            "sample_rate_sps": 4_000_000, "sample_format": "cf32_le", "sample_count": 1, "center_frequency_hz": 2_402_000_000,
            "bandwidth_hz": 2_000_000, "bytes_per_cpu_sample": 8, "actual_duration_seconds": 1.0, "data_path": "x.sigmf-data",
            "actual_file_size_bytes": 1, "file_size": 1, "data_sha256": f"sha-{self.capture_id}",
            "created_at_utc": "2026-08-11T00:00:00Z", "b200_rf_started_at": "2026-08-11T00:00:00Z",
            "diagnostic_status": "PASSED", "continuity_status": "PASSED", "hash_status": "VERIFIED", "capture_complete": True,
            "device_serial": "E3R04Z1B2", "hardware": "B200", "antenna": "RX2",
            "gain_configuration": {"gain_db": kwargs.get("gain_db", 20.0), "mode": "manual"},
            "capture_software_revision": "ble-sdr-capture-v3",
        }
        (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        session_id = f"S-{self.capture_id}"
        self.repository.build_capture(
            capture_id=self.capture_id, project_id=kwargs["project_id"], campaign_id=kwargs["campaign_id"],
            execution_id=session_id, session_id=session_id,
            capture_purpose=kwargs["capture_purpose"], target_reference_id=kwargs.get("physical_unit_id"),
            target_state="POWERED_ON", dataset_role="POSITIVE_CANDIDATE",
        )
        return {"capture_id": self.capture_id, "session_id": session_id}


@pytest.fixture
def repository(tmp_path):
    repo = StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "iq_captures", legacy_session_root=tmp_path / "sessions")
    orchestrator = _StubOrchestrator(repo, "REAL-CAP-1")
    repo.campaign_orchestrator = orchestrator
    repo.paper_campaign_runner.campaign_orchestrator = orchestrator
    return repo


def test_freeze_and_get_campaign_schedule(repository):
    repository.freeze_campaign_schedule(schedule_id="SCHED-1", protocol_id="PROTO-1", entries=[_entry()])
    schedule = repository.get_campaign_schedule("SCHED-1")
    assert schedule.schedule_id == "SCHED-1"
    assert len(schedule.entries) == 1


def test_execute_next_campaign_schedule_capture_rebuilds_the_capture_record_with_schedule_metadata(repository):
    repository.freeze_campaign_schedule(schedule_id="SCHED-2", protocol_id="PROTO-1", entries=[_entry(day_id="DAY-7", pre_or_post="POST", intervention_arm="RESET")])

    capture_record = repository.execute_next_campaign_schedule_capture(schedule_id="SCHED-2", duration_seconds=10.0)

    assert capture_record.capture_id == "REAL-CAP-1"
    assert capture_record.day_id == "DAY-7"
    assert capture_record.pre_or_post == "POST"
    assert capture_record.intervention_arm == "RESET"
    assert capture_record.project_id == "PROTO-1"  # execute_next_campaign_schedule_capture passes schedule.protocol_id as project_id

    reloaded_schedule = repository.get_campaign_schedule("SCHED-2")
    assert reloaded_schedule.entries[0].executed is True
    assert reloaded_schedule.entries[0].executed_capture_id == "REAL-CAP-1"


def test_execute_next_campaign_schedule_capture_raises_when_schedule_is_fully_executed(repository):
    repository.freeze_campaign_schedule(schedule_id="SCHED-3", protocol_id="PROTO-1", entries=[_entry()])
    repository.execute_next_campaign_schedule_capture(schedule_id="SCHED-3", duration_seconds=10.0)
    with pytest.raises(ValueError, match="CAMPAIGN_SCHEDULE_FULLY_EXECUTED"):
        repository.execute_next_campaign_schedule_capture(schedule_id="SCHED-3", duration_seconds=10.0)


def test_execute_next_campaign_schedule_capture_without_an_orchestrator_raises_a_clear_error(tmp_path):
    bare_repository = StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "iq_captures", legacy_session_root=tmp_path / "sessions")
    bare_repository.freeze_campaign_schedule(schedule_id="SCHED-4", protocol_id="PROTO-1", entries=[_entry()])
    with pytest.raises(RuntimeError, match="REAL_CAMPAIGN_NOT_AVAILABLE"):
        bare_repository.execute_next_campaign_schedule_capture(schedule_id="SCHED-4", duration_seconds=10.0)


def test_list_campaign_schedule_rejections_starts_empty_and_records_a_real_out_of_schedule_attempt(repository):
    repository.freeze_campaign_schedule(schedule_id="SCHED-5", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1"), _entry(planned_capture_id="p2", capture_order=2)])
    assert repository.list_campaign_schedule_rejections("SCHED-5") == []

    schedule = repository.get_campaign_schedule("SCHED-5")
    with pytest.raises(Exception):
        repository.paper_campaign_runner.execute(schedule, "p2", build_capture_record=repository._rebuild_capture_record_with_schedule_metadata)

    rejections = repository.list_campaign_schedule_rejections("SCHED-5")
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "WRONG_CAPTURE_ORDER"
