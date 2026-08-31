"""Study Control Center, Phase 1 (2026-08-11): automates real BLE-RFFI
hardware qualification end-to-end from a single job -- B200 detection, real
IQ acquisition, BLE decode + CRC (via the existing
CampaignOrchestrator.run_session/BleOfflineReplayService pipeline), the
Eq.(6)-(7) real-IQ smoke test, and assembling the real gate values
`run_campaign_qualification_preflight()` already knows how to classify.
This module computes NO new science -- it only drives real hardware and
real, already-existing functions (`run_session`, `apply_base_preprocessing_
with_provenance`, `build_pre_post_pairs`, `find_frozen_association_policy`
via the preflight call itself), then wires their real outputs into the
untouched preflight classifier.

`association_state` and `rq3_readiness` are NOT satisfiable from a single
fresh capture (see the docstrings on `find_frozen_association_policy`/
`build_pre_post_pairs`) -- a first real qualification run legitimately
lands on `overall_status=NOT_READY` or `PRELIMINARY`, and this module never
tries to force otherwise. Any real acquisition/session failure (hardware
absent, B200 busy, invalid physical_unit_id, etc.) is recorded honestly as
`b200_detected=False` with the real error text preserved -- never silently
swallowed, never retried automatically.
"""
from __future__ import annotations

from typing import Any, Callable

from app.modules.ble_rffi_studio.campaign.pre_post_pairing import build_pre_post_pairs
from app.modules.ble_rffi_studio.preprocessing.base_preprocessing import (
    BasePreprocessingProfile,
    apply_base_preprocessing_with_provenance,
    load_iq_window,
)
from app.modules.ble_rffi_studio.registry.physical_device_registry import PhysicalDeviceRegistry

ProgressHook = Callable[[str, float, str], None] | None

# The same paper-compliant Eq.(6)-(7) profile id already used elsewhere in
# this codebase's fixtures/provenance chain (e.g. inference_run manifests'
# base_preprocessing_profile_id) -- not a new profile definition, just the
# one real, existing profile shape with paper_eq6_7_compensation enabled.
EQ6_7_SMOKE_TEST_PROFILE = BasePreprocessingProfile(profile_id="paper-eq6-7-v1", paper_eq6_7_compensation=True)

HARDWARE_QUALIFICATION_PROJECT_ID = "HARDWARE-QUALIFICATION"
HARDWARE_QUALIFICATION_CAMPAIGN_ID = "HARDWARE-QUALIFICATION"


class HardwareQualificationError(Exception):
    pass


def _run_eq6_7_smoke_test(sci_repository: Any, capture: Any) -> bool | None:
    """True/False only when a real admitted example from this exact capture
    was actually run through the real Eq.(6)-(7) compensation step; None
    (NOT_CHECKED, never a fabricated pass/fail) when this capture produced
    no admitted example to test against."""
    examples = sci_repository._load_examples(capture.capture_id)
    if not examples:
        return None
    example = examples[0]
    iq_path = sci_repository._resolve_iq_path(capture)
    if not iq_path.is_file():
        return None
    window = load_iq_window(iq_path, example.iq_start_sample, example.iq_end_sample)
    _, provenance = apply_base_preprocessing_with_provenance(window, EQ6_7_SMOKE_TEST_PROFILE, capture.sample_rate_sps)
    return provenance is not None and provenance.compensation_status == "APPLIED"


def run_real_hardware_qualification(
    *, sci_repository: Any, campaign_orchestrator: Any, physical_unit_id: str, channel: int,
    duration_seconds: float, progress: ProgressHook = None, cancel_event: Any = None,
) -> dict[str, Any]:
    if campaign_orchestrator is None:
        raise HardwareQualificationError("NO_CAMPAIGN_ORCHESTRATOR_CONFIGURED:real ble_lab hardware managers are not available in this process")

    def report(stage: str, fraction: float, message: str) -> None:
        if progress:
            progress(stage, fraction, str(message))

    report("b200_detection_and_acquisition", 0.05, f"Starting real B200 acquisition for {physical_unit_id} on channel {channel}")
    try:
        session_result = campaign_orchestrator.run_session(
            ble_channel=channel, duration_seconds=duration_seconds, gain_db=20.0,
            condition_label="hardware-qualification-probe", physical_unit_id=physical_unit_id,
            project_id=HARDWARE_QUALIFICATION_PROJECT_ID, campaign_id=HARDWARE_QUALIFICATION_CAMPAIGN_ID, session_index=1,
            isolation_declared=True, capture_purpose="TARGET_DEVICE_ON", progress=progress, cancel_event=cancel_event,
        )
    except Exception as error:  # noqa: BLE001 -- a real acquisition failure is honest gate data, not a crash to hide
        if "CANCELLED_BY_OPERATOR" in str(error):
            raise  # a deliberate operator cancel is not a qualification result -- let the job manager mark it cancelled
        report("b200_detection_and_acquisition", 0.1, f"Real B200 acquisition did not complete: {error}")
        preflight_report = sci_repository.run_campaign_qualification_preflight(b200_detected=False)
        return {"capture_id": None, "session_id": None, "acquisition_error": str(error), "preflight_report": preflight_report}

    capture_id = session_result["capture_id"]
    report("ble_decode_and_crc", 0.4, f"Reading real CaptureRecord and decode/CRC evidence for {capture_id}")
    capture = sci_repository._load_capture(capture_id)
    if capture is None:
        raise HardwareQualificationError(f"CAPTURE_RECORD_NOT_FOUND_AFTER_REAL_SESSION:{capture_id}")

    report("eq6_7_smoke_test", 0.65, "Running the Eq.(6)-(7) real-IQ smoke test")
    eq6_7_passed = _run_eq6_7_smoke_test(sci_repository, capture)

    report("association_and_rq3_rq4", 0.8, "Reading real association policy / RQ3 pairing / RQ4 eligibility state")
    all_captures = sci_repository._load_all_captures()
    real_pairs = build_pre_post_pairs(all_captures)
    registry = PhysicalDeviceRegistry(sci_repository.ble_root / "registry")
    units = registry.list_physical_units()
    eligible_count = sum(1 for unit in units if unit.rq4_eligibility == "ELIGIBLE")

    report("assembling_report", 0.95, "Assembling the canonical qualification report")
    preflight_report = sci_repository.run_campaign_qualification_preflight(
        b200_detected=True,
        receiver_identity_confirmed=bool(capture.receiver_identity_id),
        qualified_receiver_profile=(
            {"sdr_model": capture.sdr_model, "receiver_device_id": capture.receiver_device_id, "qualified_acquisition_profile_hash": capture.qualified_acquisition_profile_hash}
            if capture.qualified_acquisition_profile_hash else None
        ),
        channel_frequency_integrity_ok=capture.center_frequency_hz is not None,
        capture_continuity_ok=(capture.discontinuities or 0) == 0,
        quality_summary_reviewed=capture.acquisition_quality == "PASSED",
        iq_digest_verified=bool(capture.iq_sha256),
        real_pre_post_pairs=real_pairs,
        rq4_eligible_device_count=eligible_count, rq4_total_device_count=len(units),
        paper_eq6_7_smoke_test_passed=eq6_7_passed,
    )
    return {"capture_id": capture_id, "session_id": session_result["session_id"], "preflight_report": preflight_report}
