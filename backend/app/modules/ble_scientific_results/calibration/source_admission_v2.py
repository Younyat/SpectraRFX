"""SOURCE ADMISSION V2 -- admits a decoded SDR PDU as a reference-source
example for a controlled physical unit WITHOUT requiring a packet-level
native<->SDR temporal match. The packet-level match (association_calibration.py
/ select_association_threshold) is preserved unchanged and keeps running --
it is reclassified as TEMPORAL_ASSOCIATION_DIAGNOSTIC, characterizing the
native-scanner<->SDR timing relationship, but it is no longer a mandatory
prerequisite for admitting a reference example (real audit: native callbacks
are structurally sparser and more batched than the SDR's own packet rate --
see LESSONS_LEARNED_TECHNICAL.md 2026-08-13/14 -- so a per-packet ±window
match is the wrong denominator for "is this evidence admissible", even
though it remains a valid, separate diagnostic).

Ground truth for admission is session-level, multi-signal corroboration --
never a single field alone:
  1. qualified real B200 capture (data_origin/acquisition_quality)
  2. controlled TARGET_DEVICE_ON acquisition (capture_purpose + target_reference_id)
  3. CRC-valid recovered PDU (packet_association_ledger.jsonl rows are
     CRC-valid by construction -- see ble_offline_replay.py -- listed here
     explicitly so the rule is self-documenting rather than relying on that
     upstream invariant silently)
  4. PDU transmitting role compatible with emission BY the target (never
     SCAN_REQ -- its address field identifies who is being scanned, not who
     transmitted it)
  5. decoded SDR address bound to the enrolled physical unit
  6. valid source-IQ provenance
  7. native observation of the SAME unit somewhere in the SAME
     acquisition/session (session-level corroboration, not a per-packet
     timestamp match)
  8. target-specific OFF control available and PASSED for that physical unit
     (see evaluate_target_specific_off_control below)
"""
from __future__ import annotations

from dataclasses import dataclass, field

TARGET_EMITTED_PDU_TYPES = frozenset({"ADV_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND", "SCAN_RSP"})


def is_target_emitted_pdu_role(pdu_type: str | None) -> bool:
    """SCAN_REQ AdvA=target is NEVER eligible as target-emitted RF (point B
    of the source-admission request, verbatim)."""
    return pdu_type in TARGET_EMITTED_PDU_TYPES


@dataclass(frozen=True)
class CaptureAdmissionResult:
    capture_id: str
    physical_unit_id: str
    admitted: bool
    admitted_pdu_count: int
    direct_target_pdu_count: int
    native_target_observation_count: int
    failed_conditions: tuple[str, ...] = field(default_factory=tuple)


def evaluate_capture_admission_v2(
    *, capture_id: str, physical_unit_id: str, capture_purpose: str | None, target_reference_id: str | None,
    data_origin: str | None, acquisition_quality: str | None, bound_address: str | None,
    native_target_observation_count: int, off_control_passed: bool, ledger_rows: list[dict],
) -> CaptureAdmissionResult:
    """Pure, per-capture evaluation of the 8 admission conditions -- never
    reads a file itself, so it is trivially testable against synthetic fact
    combinations. `ledger_rows` is the capture's FULL
    packet_association_ledger.jsonl (every CRC-valid decoded packet, any
    address) -- condition 4/5 are evaluated per row against
    `advertiser_address_canonical`/`pdu_type`."""
    failed: list[str] = []

    if not (capture_purpose == "TARGET_DEVICE_ON" and target_reference_id == physical_unit_id):
        failed.append("CONTROLLED_TARGET_DEVICE_ON_ACQUISITION")
    if not (data_origin == "REAL_B200" and acquisition_quality == "PASSED"):
        failed.append("QUALIFIED_REAL_B200_CAPTURE_OR_PROVENANCE")
    if not bound_address:
        failed.append("PHYSICAL_UNIT_HAS_NO_BOUND_ADDRESS")
    if not off_control_passed:
        failed.append("TARGET_SPECIFIC_OFF_CONTROL_NOT_AVAILABLE_OR_NOT_PASSED")
    if native_target_observation_count <= 0:
        failed.append("NO_NATIVE_SESSION_CORROBORATION")

    direct_target_pdus = 0
    if bound_address:
        target_upper = bound_address.upper()
        for row in ledger_rows:
            address = str(row.get("advertiser_address_canonical", "")).upper()
            if address == target_upper and is_target_emitted_pdu_role(row.get("pdu_type")):
                direct_target_pdus += 1

    if not failed and direct_target_pdus == 0:
        failed.append("NO_TARGET_EMITTED_PDU_IN_THIS_CAPTURE")

    admitted = not failed
    return CaptureAdmissionResult(
        capture_id=capture_id, physical_unit_id=physical_unit_id, admitted=admitted,
        admitted_pdu_count=direct_target_pdus if admitted else 0,
        direct_target_pdu_count=direct_target_pdus,
        native_target_observation_count=native_target_observation_count,
        failed_conditions=tuple(failed),
    )


@dataclass(frozen=True)
class UnitAdmissionSummary:
    physical_unit_id: str
    eligible_captures: int
    admitted_captures: int
    admitted_direct_pdus: int
    off_control_passed: bool
    capture_results: tuple[CaptureAdmissionResult, ...] = field(default_factory=tuple)

    @property
    def excluded_captures(self) -> tuple[CaptureAdmissionResult, ...]:
        return tuple(result for result in self.capture_results if not result.admitted)

    @property
    def readiness(self) -> str:
        return "READY" if self.admitted_captures > 0 and self.off_control_passed else "BLOCKED"


def summarize_unit_admission(
    physical_unit_id: str, capture_results: list[CaptureAdmissionResult], off_control_passed: bool,
) -> UnitAdmissionSummary:
    return UnitAdmissionSummary(
        physical_unit_id=physical_unit_id,
        eligible_captures=len(capture_results),
        admitted_captures=sum(1 for result in capture_results if result.admitted),
        admitted_direct_pdus=sum(result.admitted_pdu_count for result in capture_results),
        off_control_passed=off_control_passed,
        capture_results=tuple(capture_results),
    )


@dataclass(frozen=True)
class TargetSpecificOffControlResult:
    physical_unit_id: str
    negative_sessions: int
    target_native_observations: int
    target_sdr_compatible_pdus: int
    false_target_attributions: int
    passed: bool


def evaluate_target_specific_off_control(
    *, physical_unit_id: str, bound_address: str | None,
    negative_session_native_rows: list[list[dict]], negative_session_ledger_rows: list[list[dict]],
) -> TargetSpecificOffControlResult:
    """Pure evaluation of condition 8 for one physical unit: across every
    declared-OFF session for it (standard BACKGROUND_TARGET_OFF captures
    AND experimenter-attested sessions -- the caller resolves which sessions
    qualify and passes their already-loaded rows in), the unit's own address
    must never appear, neither as a native observation nor as a decoded SDR
    packet. `negative_session_native_rows`/`negative_session_ledger_rows`
    are parallel lists, one entry per negative session."""
    address = bound_address.upper() if bound_address else None
    native_count = 0
    sdr_count = 0
    if address:
        for rows in negative_session_native_rows:
            native_count += sum(1 for row in rows if str(row.get("address", "")).upper() == address)
        for rows in negative_session_ledger_rows:
            sdr_count += sum(1 for row in rows if str(row.get("advertiser_address_canonical", "")).upper() == address)

    passed = bool(address) and len(negative_session_native_rows) > 0 and native_count == 0 and sdr_count == 0
    return TargetSpecificOffControlResult(
        physical_unit_id=physical_unit_id, negative_sessions=len(negative_session_native_rows),
        target_native_observations=native_count, target_sdr_compatible_pdus=sdr_count,
        false_target_attributions=native_count + sdr_count, passed=passed,
    )
