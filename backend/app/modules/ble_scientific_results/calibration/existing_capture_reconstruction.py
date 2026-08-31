"""Reconstructs calibration/pilot eligibility and CalibrationEventRecords
from CAPTURES THAT ALREADY EXIST on disk -- never re-captures. Extracted
from a one-off analysis script into pure, tested functions so the Guided
Validation orchestrator (guided_validation/service.py) and any future
script can share exactly one implementation of "is this capture usable for
calibration/pilot purposes", never two.

CALIBRATION_GROUND_TRUTH note: `declared_target_device` here means the
capture's OWN operator-declared target (CaptureRecord.target_reference_id)
-- valid as ground truth for CALIBRATION reconstruction (the operator
controlled which device was active), but this function never promotes that
declaration into a TARGET_ASSOCIATED_PACKET label by itself; that gate
lives in records/burst_records.py and stays untouched here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..contracts import CalibrationEventRecord

CaptureEligibility = Literal["ASSOCIATION_CALIBRATION_ELIGIBLE", "QUALIFICATION_PILOT_ELIGIBLE", "DIAGNOSTIC_ONLY"]

# Fields a capture must have to be usable at all for calibration reconstruction.
_CALIBRATION_REQUIRED_FACTS = (
    "has_source_iq", "has_channel", "has_sample_rate", "has_timestamp",
    "has_native_observations", "has_association_ledger", "has_crc_valid_packets", "has_declared_target_device",
)

# Fields that ONLY the campaign runner declares before a real capture --
# never backfilled from folder/campaign names for pre-existing captures.
PILOT_REQUIRED_FIELDS = ("day_id", "campaign_period", "pre_or_post", "intervention_arm", "capture_order", "receiver_epoch")


@dataclass(frozen=True)
class CaptureEligibilityResult:
    classification: CaptureEligibility
    missing_fields: tuple[str, ...] = field(default_factory=tuple)


def evaluate_capture_eligibility(
    *, has_source_iq: bool, has_channel: bool, has_sample_rate: bool, has_timestamp: bool,
    has_native_observations: bool, has_association_ledger: bool, has_crc_valid_packets: bool,
    has_declared_target_device: bool, pilot_fields_present: dict[str, bool],
) -> CaptureEligibilityResult:
    """Pure classification -- never reads a file itself, so it is trivially
    testable against synthetic fact combinations. `pilot_fields_present`
    must have exactly the keys in PILOT_REQUIRED_FIELDS."""
    facts = {
        "has_source_iq": has_source_iq, "has_channel": has_channel, "has_sample_rate": has_sample_rate,
        "has_timestamp": has_timestamp, "has_native_observations": has_native_observations,
        "has_association_ledger": has_association_ledger, "has_crc_valid_packets": has_crc_valid_packets,
        "has_declared_target_device": has_declared_target_device,
    }
    missing = [name.removeprefix("has_") for name, ok in facts.items() if not ok]
    missing += [name for name in PILOT_REQUIRED_FIELDS if not pilot_fields_present.get(name, False)]

    calibration_eligible = all(facts.values())
    pilot_eligible = calibration_eligible and all(pilot_fields_present.get(name, False) for name in PILOT_REQUIRED_FIELDS)

    if pilot_eligible:
        classification: CaptureEligibility = "QUALIFICATION_PILOT_ELIGIBLE"
    elif calibration_eligible:
        classification = "ASSOCIATION_CALIBRATION_ELIGIBLE"
    else:
        classification = "DIAGNOSTIC_ONLY"
    return CaptureEligibilityResult(classification=classification, missing_fields=tuple(missing))


def calibration_event_from_ledger_row(
    row: dict, *, device_id: str, capture_id: str, fallback_timestamp: str,
) -> CalibrationEventRecord:
    """Maps one REAL packet_association_ledger.jsonl row into a
    CalibrationEventRecord. The real ledger is packet-centric (one row per
    SDR-decoded packet, matched against native observations); it does not
    carry a native-event-centric "second competing SDR candidate" residual.
    The closest real signal for "more than one competing candidate" it DOES
    carry is temporal_match_status=="AMBIGUOUS" (more than one native
    observation fell inside the packet's time window) -- mapped here to
    second_candidate_residual_ms=0.0 (unconditionally inside any grid
    threshold), so select_association_threshold's own ambiguity check
    blocks the event regardless of magnitude, exactly matching "no promover
    ninguno por ser ligeramente mas proximo". decoded_address_match uses
    address_match_status=="MATCHED" specifically (not MATCHED_NON_TARGET),
    which _associate() already only sets when the packet's own address
    equals the declared target's address."""
    time_delta = row.get("time_delta_ms")
    temporal = row.get("temporal_match_status")
    residual = abs(time_delta) if time_delta is not None else None
    second_residual = 0.0 if temporal == "AMBIGUOUS" else None
    return CalibrationEventRecord(
        native_event_id=f"{capture_id}:{row.get('packet_id')}", sdr_packet_id=row.get("packet_id"),
        physical_unit_id=device_id, capture_id=capture_id,
        native_timestamp_utc=row.get("nearest_windows_callback_timestamp") or fallback_timestamp,
        sdr_timestamp_utc=fallback_timestamp, absolute_residual_ms=residual,
        decoded_address_match=row.get("address_match_status") == "MATCHED",
        decoded_field_match=row.get("pdu_type") is not None,
        callback_batch_id=capture_id,
        number_of_competing_candidates=2 if temporal == "AMBIGUOUS" else (1 if temporal == "MATCHED" else 0),
        best_candidate_residual_ms=residual, second_candidate_residual_ms=second_residual,
        is_target_absence_control=False,
    )


def find_enrolled_devices_in_native_scan(native_rows: list[dict], device_addresses: dict[str, str]) -> list[str]:
    """Cross-checks a native BLE scan's observed addresses against every
    enrolled device's OWN bound address -- the real check a target-absence
    control needs (point 4 of the calibration request: "no aceptar como
    control reforzado una sesion sin escaner nativo" implies the converse
    too -- a session WITH scanning must be actually checked, not assumed
    clean just because it is labeled BACKGROUND_TARGET_OFF)."""
    seen = {str(row.get("address", "")).upper() for row in native_rows}
    return sorted(device_id for device_id, address in device_addresses.items() if address.upper() in seen)
