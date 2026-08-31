"""Covers the pure, hardware-free pieces of run_campaign.py (the single-
command pilot executor): schedule freeze-or-reuse and the operator-facing
description text. main()'s hardware bootstrap (ble_lab_module.build_router,
real B200 managers) is deliberately NOT exercised here -- it requires real
hardware and is out of scope for a unit test."""
from __future__ import annotations

from app.modules.ble_rffi_studio.campaign import PaperCampaignRunner
from app.modules.ble_scientific_results.run_campaign import _describe, _load_schedule


def _entry_dict(**overrides) -> dict:
    fields = dict(
        planned_capture_id="planned-1", protocol_id="PROTO-1", day_id="DAY-1", physical_unit_id="UNIT-A", capture_order=1,
        pre_or_post="PRE", intervention_arm="CONTROL", packet_condition="original", channel=37,
        receiver_epoch="EPOCH-1", time_since_power_on_s=30.0, time_since_intervention_s=None,
    )
    fields.update(overrides)
    return fields


def test_load_schedule_freezes_on_first_call_and_reuses_on_second(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule_input = {"schedule_id": "PILOT-1", "qualification_only": True, "entries": [_entry_dict()]}

    first = _load_schedule(runner, schedule_id="PILOT-1", protocol_id="PROTO-1", schedule_input=schedule_input)
    assert first.schedule_version == 1
    assert first.qualification_only is True
    assert first.entries[0].protocol_id == "PROTO-1"

    second = _load_schedule(runner, schedule_id="PILOT-1", protocol_id="PROTO-1", schedule_input=schedule_input)
    assert second.schedule_version == 1  # reused, not re-frozen as a new version


def test_describe_includes_every_field_the_operator_must_see(tmp_path):
    runner = PaperCampaignRunner(storage_root=tmp_path / "storage", legacy_capture_root=tmp_path / "iq_captures")
    schedule = runner.freeze_schedule(schedule_id="PILOT-2", protocol_id="PROTO-1", entries=[_entry_dict()])
    text = _describe(schedule.entries[0])

    for expected in ("planned-1", "DAY-1", "UNIT-A", "37", "PRE", "CONTROL", "original", "EPOCH-1", "time_since_power_on_s=30.0"):
        assert expected in text