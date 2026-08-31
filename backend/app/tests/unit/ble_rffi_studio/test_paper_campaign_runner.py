"""Paper campaign runner: frozen schedule, refuse-off-schedule enforcement,
declared-metadata application to a real capture manifest -- exercised
against a synthetic capture fixture (a stub orchestrator stands in for real
hardware, since this suite never touches a B200)."""
from __future__ import annotations

import json

import pytest

from app.modules.ble_rffi_studio.campaign import PaperCampaignRunner, PaperCampaignSchedulingError, build_balanced_crossover_assignment
from app.modules.ble_rffi_studio.contracts import PaperCampaignScheduleEntry


def _entry(**overrides) -> dict:
    fields = dict(
        planned_capture_id="planned-1", protocol_id="PROTO-1", day_id="DAY-1", campaign_period="qualification",
        physical_unit_id="UNIT-A", capture_order=1, pre_or_post="PRE", intervention_arm="CONTROL",
        packet_condition="original", channel=37, receiver_epoch="EPOCH-1",
    )
    fields.update(overrides)
    return fields


class _StubOrchestrator:
    def __init__(self, capture_id: str) -> None:
        self.capture_id = capture_id
        self.calls: list[dict] = []

    def run_session(self, **kwargs):
        self.calls.append(kwargs)
        return {"capture_id": self.capture_id}


def _write_real_capture_manifest(legacy_capture_root, capture_id: str) -> None:
    capture_dir = legacy_capture_root / capture_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "capture_manifest.json").write_text(json.dumps({"capture_id": capture_id, "sample_rate_sps": 4_000_000}), encoding="utf-8")


def test_freeze_schedule_and_next_planned_capture(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(schedule_id="SCHED-1", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1"), _entry(planned_capture_id="p2", capture_order=2)])
    assert schedule.schedule_version == 1
    assert len(schedule.entries) == 2

    next_entry = runner.next_planned_capture(schedule)
    assert next_entry.planned_capture_id == "p1"


def test_duplicate_planned_capture_id_rejected(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    with pytest.raises(Exception):
        runner.freeze_schedule(schedule_id="SCHED-DUP", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1"), _entry(planned_capture_id="p1")])


def test_execute_applies_declared_metadata_and_marks_entry_executed(tmp_path):
    legacy_root = tmp_path / "iq_captures"
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=legacy_root, campaign_orchestrator=_StubOrchestrator("REAL-CAP-1"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-2", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    _write_real_capture_manifest(legacy_root, "REAL-CAP-1")

    captured_ids = []
    capture_record = runner.execute(schedule, "p1", build_capture_record=lambda cap_id: captured_ids.append(cap_id) or cap_id)

    assert capture_record == "REAL-CAP-1"
    manifest = json.loads((legacy_root / "REAL-CAP-1" / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["day_id"] == "DAY-1"
    assert manifest["pre_or_post"] == "PRE"
    assert manifest["intervention_arm"] == "CONTROL"
    assert manifest["planned_capture_id"] == "p1"

    reloaded = runner.load_schedule("SCHED-2")
    assert reloaded.entries[0].executed is True
    assert reloaded.entries[0].executed_capture_id == "REAL-CAP-1"


def test_execute_refuses_a_planned_capture_id_not_in_schedule(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures", campaign_orchestrator=_StubOrchestrator("X"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-3", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "not-scheduled", build_capture_record=lambda cap_id: cap_id)


def test_execute_refuses_a_planned_capture_id_already_executed(tmp_path):
    legacy_root = tmp_path / "iq_captures"
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=legacy_root, campaign_orchestrator=_StubOrchestrator("REAL-CAP-1"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-4", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    _write_real_capture_manifest(legacy_root, "REAL-CAP-1")
    runner.execute(schedule, "p1", build_capture_record=lambda cap_id: cap_id)

    reloaded = runner.load_schedule("SCHED-4")
    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(reloaded, "p1", build_capture_record=lambda cap_id: cap_id)


def test_execute_without_orchestrator_raises(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(schedule_id="SCHED-5", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "p1", build_capture_record=lambda cap_id: cap_id)


def test_reject_out_of_schedule_returns_a_plain_record_without_executing(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(schedule_id="SCHED-6", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    rejection = runner.reject_out_of_schedule(schedule=schedule, attempted={"physical_unit_id": "UNIT-B"}, reason="CAPTURE_OUT_OF_SCHEDULE")
    assert rejection["reason"] == "CAPTURE_OUT_OF_SCHEDULE"
    assert rejection["schedule_id"] == "SCHED-6"


def test_execute_persists_rejection_for_unknown_planned_capture_id(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures", campaign_orchestrator=_StubOrchestrator("X"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-7", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "not-scheduled", build_capture_record=lambda cap_id: cap_id, operator_id="OP-1")

    rejections = runner.list_rejections("SCHED-7")
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "CAPTURE_OUT_OF_SCHEDULE"
    assert rejections[0]["operator_id"] == "OP-1"
    assert rejections[0]["protocol_id"] == "PROTO-1"


def test_execute_rejects_out_of_order_capture_before_running(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures", campaign_orchestrator=_StubOrchestrator("X"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-8", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1"), _entry(planned_capture_id="p2", capture_order=2)])
    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "p2", build_capture_record=lambda cap_id: cap_id)

    rejections = runner.list_rejections("SCHED-8")
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "WRONG_CAPTURE_ORDER"
    assert rejections[0]["planned_capture_id"] == "p2"


def test_execute_rejects_attempted_field_mismatch_and_never_runs_session(tmp_path):
    orchestrator = _StubOrchestrator("X")
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures", campaign_orchestrator=orchestrator)
    schedule = runner.freeze_schedule(schedule_id="SCHED-9", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])

    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "p1", build_capture_record=lambda cap_id: cap_id, attempted={"channel": 99, "physical_unit_id": "UNIT-B"})

    assert orchestrator.calls == []  # no silent override: the real capture never ran
    rejections = runner.list_rejections("SCHED-9")
    assert len(rejections) == 1
    codes = rejections[0]["reason"].split(",")
    assert "WRONG_CHANNEL" in codes
    assert "WRONG_UNIT" in codes


def test_build_balanced_crossover_assignment_gives_each_device_equal_reset_and_control_days():
    assignment = build_balanced_crossover_assignment(device_ids=["D1", "D2", "D3"], n_days=20)
    assert set(assignment.keys()) == {"D1", "D2", "D3"}
    for labels in assignment.values():
        assert len(labels) == 20
        assert labels.count("RESET") == 10
        assert labels.count("CONTROL") == 10


def test_build_balanced_crossover_assignment_shuffles_independently_per_device():
    assignment = build_balanced_crossover_assignment(device_ids=["D1", "D2"], n_days=4)
    # Not asserting a specific order (that would over-specify an
    # implementation detail of the RNG) -- only that the two devices are
    # not forced into the identical sequence.
    assert assignment["D1"] != [] and assignment["D2"] != []


def test_build_balanced_crossover_assignment_is_reproducible_with_the_same_seed():
    a = build_balanced_crossover_assignment(device_ids=["D1", "D2"], n_days=6, seed=42)
    b = build_balanced_crossover_assignment(device_ids=["D1", "D2"], n_days=6, seed=42)
    assert a == b


def test_build_balanced_crossover_assignment_rejects_odd_day_counts():
    with pytest.raises(ValueError):
        build_balanced_crossover_assignment(device_ids=["D1"], n_days=5)


def test_execute_with_matching_attempted_fields_proceeds_normally(tmp_path):
    legacy_root = tmp_path / "iq_captures"
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=legacy_root, campaign_orchestrator=_StubOrchestrator("REAL-CAP-2"))
    schedule = runner.freeze_schedule(schedule_id="SCHED-10", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])
    _write_real_capture_manifest(legacy_root, "REAL-CAP-2")

    capture_record = runner.execute(
        schedule, "p1", build_capture_record=lambda cap_id: cap_id,
        attempted={"channel": 37, "physical_unit_id": "UNIT-A"},
    )
    assert capture_record == "REAL-CAP-2"
    assert runner.list_rejections("SCHED-10") == []


def test_freeze_schedule_gives_every_entry_the_same_receiver_session_id(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(
        schedule_id="SCHED-11", protocol_id="PROTO-1",
        entries=[_entry(planned_capture_id="p1"), _entry(planned_capture_id="p2", capture_order=2, pre_or_post="POST")],
    )
    assert schedule.receiver_session_id
    assert all(e.receiver_session_id == schedule.receiver_session_id for e in schedule.entries)


def test_freeze_schedule_honors_an_operator_supplied_receiver_session_id(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(
        schedule_id="SCHED-12", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")],
        receiver_session_id="operator-declared-session",
    )
    assert schedule.receiver_session_id == "operator-declared-session"
    assert schedule.entries[0].receiver_session_id == "operator-declared-session"


def test_execute_rejects_attempted_receiver_session_id_mismatch(tmp_path):
    orchestrator = _StubOrchestrator("X")
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures", campaign_orchestrator=orchestrator)
    schedule = runner.freeze_schedule(schedule_id="SCHED-13", protocol_id="PROTO-1", entries=[_entry(planned_capture_id="p1")])

    with pytest.raises(PaperCampaignSchedulingError):
        runner.execute(schedule, "p1", build_capture_record=lambda cap_id: cap_id, attempted={"receiver_session_id": "a-different-session"})

    assert orchestrator.calls == []
    rejections = runner.list_rejections("SCHED-13")
    assert rejections[0]["reason"] == "RECEIVER_SESSION_ID_MISMATCH"
