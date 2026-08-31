"""The frozen schedule a real paper campaign must follow, plus one entry's
declared metadata -- every field `paper_campaign_runner.py` requires an
operator to declare BEFORE a capture happens, never reconstructed after.

Frozen the same way AnalysisContract/DatasetManifest already are elsewhere
in this codebase (StudioContract: immutable, content-hashable) -- a
schedule, once frozen, is never edited; a correction creates a new
schedule_version.
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract, identity_hash

PAPER_CAMPAIGN_SCHEDULE_SCHEMA_VERSION = "ble-rffi-studio-paper-campaign-schedule-v1"

PrePost = Literal["PRE", "POST", "NOT_APPLICABLE"]
InterventionArm = Literal["RESET", "CONTROL", "NOT_APPLICABLE"]


class PaperCampaignScheduleEntry(StudioContract):
    planned_capture_id: str
    protocol_id: str
    day_id: str
    campaign_period: str | None = None
    physical_unit_id: str
    capture_order: int
    pre_or_post: PrePost
    intervention_arm: InterventionArm
    packet_condition: str
    channel: int
    time_since_power_on_s: float | None = None
    time_since_intervention_s: float | None = None
    firmware_hash: str | None = None
    configuration_hash: str | None = None
    receiver_epoch: str
    # Operator-attested marker of receiver-connection continuity for this
    # whole schedule (see contracts/capture.py's receiver_session_id
    # docstring for why this can't be auto-detected: every real capture
    # opens/closes its own SDR device handle, so there is no software signal
    # for "same physical connection" across captures). Propagated from
    # PaperCampaignSchedule.receiver_session_id at freeze time.
    receiver_session_id: str
    capture_purpose: str = "TARGET_DEVICE_ON"

    # Set only once the entry has actually been executed -- never true at
    # schedule-freeze time.
    executed: bool = False
    executed_capture_id: str | None = None

    @staticmethod
    def make_planned_capture_id(*, protocol_id: str, day_id: str, physical_unit_id: str, capture_order: int) -> str:
        return identity_hash(protocol_id, day_id, physical_unit_id, capture_order, prefix="planned-capture")


class PaperCampaignSchedule(StudioContract):
    schema_version: str = PAPER_CAMPAIGN_SCHEDULE_SCHEMA_VERSION
    schedule_id: str
    schedule_version: int
    protocol_id: str
    entries: list[PaperCampaignScheduleEntry] = []
    # A qualification pilot is explicitly excluded from paper results --
    # see PILOT_CHECKLIST.md. A schedule frozen for the real campaign must
    # leave this False.
    qualification_only: bool = False
    # Operator-attested: "the B200 stayed connected/powered for this whole
    # schedule." Generated once at freeze time (see
    # PaperCampaignRunner.freeze_schedule) unless the operator supplies
    # their own value. A genuine physical disconnect/power-cycle mid-campaign
    # means freezing a NEW schedule (hence a new id), never mutating this one.
    receiver_session_id: str
    frozen_at: str
