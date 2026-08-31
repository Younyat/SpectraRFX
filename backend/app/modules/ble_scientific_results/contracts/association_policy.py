"""The frozen native<->SDR association-timing policy a real calibration
campaign must produce BEFORE any TARGET_ASSOCIATED_PACKET label may be used
for definitive data (see records/burst_records.py's
STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN gate). `CalibrationEventRecord`
is the per-event input the selection rule (calibration/
association_calibration.py::select_association_threshold) consumes; ground
truth during calibration comes from physical isolation of the active unit
(CALIBRATION_GROUND_TRUTH), never from the association algorithm's own
output -- the whole point of a calibration campaign is to validate that
algorithm against something it did not produce.
"""
from __future__ import annotations

from typing import Any

from .common import StudioContract, identity_hash

ASSOCIATION_POLICY_SCHEMA_VERSION = "ble-scientific-results-association-policy-v1"
CALIBRATION_EVENT_SCHEMA_VERSION = "ble-scientific-results-calibration-event-v1"

CALIBRATION_GROUND_TRUTH = "CALIBRATION_GROUND_TRUTH"


class CalibrationEventRecord(StudioContract):
    schema_version: str = CALIBRATION_EVENT_SCHEMA_VERSION

    native_event_id: str
    sdr_packet_id: str | None = None
    physical_unit_id: str
    capture_id: str
    native_timestamp_utc: str
    sdr_timestamp_utc: str | None = None
    absolute_residual_ms: float | None = None
    decoded_address_match: bool
    decoded_field_match: bool
    callback_batch_id: str | None = None
    number_of_competing_candidates: int = 0
    best_candidate_residual_ms: float | None = None
    second_candidate_residual_ms: float | None = None

    # Not one of the fields the user listed verbatim, but required to run
    # the selection rule at all (point 4's "zero false strong associations
    # in the reinforced target-absence control" criterion needs to know
    # which events come from that control, as opposed to a real target-
    # active calibration capture). Ground truth for BOTH kinds comes from
    # physical isolation/experimental control, never from the association
    # algorithm itself.
    is_target_absence_control: bool = False
    ground_truth_source: str = CALIBRATION_GROUND_TRUTH


class AssociationPolicy(StudioContract):
    schema_version: str = ASSOCIATION_POLICY_SCHEMA_VERSION
    policy_id: str

    threshold_ms: float
    threshold_grid: list[float]
    selection_rule: str
    calibration_campaign_id: str
    devices_used: list[str]
    captures_used: list[str]
    callback_batching_policy: str
    duplicate_policy: str
    field_match_policy: str
    ambiguity_policy: str
    target_absence_result: dict[str, Any]

    frozen_at: str
    policy_hash: str

    @staticmethod
    def make_policy_id(*, calibration_campaign_id: str, frozen_at: str) -> str:
        return identity_hash(calibration_campaign_id, frozen_at, prefix="association-policy")
