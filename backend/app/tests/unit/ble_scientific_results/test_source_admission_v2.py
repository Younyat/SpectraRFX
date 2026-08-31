from __future__ import annotations

from app.modules.ble_scientific_results.calibration.source_admission_v2 import (
    evaluate_capture_admission_v2,
    evaluate_target_specific_off_control,
    is_target_emitted_pdu_role,
    summarize_unit_admission,
)

_TARGET_ADDRESS = "AA:BB:CC:DD:EE:FF"
_OTHER_ADDRESS = "11:22:33:44:55:66"


def _admission_kwargs(**overrides) -> dict:
    base = dict(
        capture_id="BLE-IQ-test", physical_unit_id="UNIT-01", capture_purpose="TARGET_DEVICE_ON",
        target_reference_id="UNIT-01", data_origin="REAL_B200", acquisition_quality="PASSED",
        bound_address=_TARGET_ADDRESS, native_target_observation_count=1, off_control_passed=True,
        ledger_rows=[{"advertiser_address_canonical": _TARGET_ADDRESS, "pdu_type": "ADV_IND"}],
    )
    base.update(overrides)
    return base


def test_pdu_role_never_admits_scan_req():
    assert is_target_emitted_pdu_role("SCAN_REQ") is False
    for role in ("ADV_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND", "SCAN_RSP"):
        assert is_target_emitted_pdu_role(role) is True


def test_all_conditions_met_admits_capture():
    result = evaluate_capture_admission_v2(**_admission_kwargs())
    assert result.admitted is True
    assert result.admitted_pdu_count == 1
    assert result.failed_conditions == ()


def test_scan_req_never_counted_even_with_matching_address():
    rows = [{"advertiser_address_canonical": _TARGET_ADDRESS, "pdu_type": "SCAN_REQ"}]
    result = evaluate_capture_admission_v2(**_admission_kwargs(ledger_rows=rows))
    assert result.admitted is False
    assert result.direct_target_pdu_count == 0
    assert "NO_TARGET_EMITTED_PDU_IN_THIS_CAPTURE" in result.failed_conditions


def test_not_controlled_target_on_acquisition_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(capture_purpose="BACKGROUND_TARGET_OFF"))
    assert result.admitted is False
    assert "CONTROLLED_TARGET_DEVICE_ON_ACQUISITION" in result.failed_conditions


def test_target_reference_id_mismatch_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(target_reference_id="SOME-OTHER-UNIT"))
    assert result.admitted is False
    assert "CONTROLLED_TARGET_DEVICE_ON_ACQUISITION" in result.failed_conditions


def test_bad_provenance_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(data_origin="SYNTHETIC"))
    assert result.admitted is False
    assert "QUALIFIED_REAL_B200_CAPTURE_OR_PROVENANCE" in result.failed_conditions

    result2 = evaluate_capture_admission_v2(**_admission_kwargs(acquisition_quality="FAILED"))
    assert result2.admitted is False
    assert "QUALIFIED_REAL_B200_CAPTURE_OR_PROVENANCE" in result2.failed_conditions


def test_no_bound_address_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(bound_address=None))
    assert result.admitted is False
    assert "PHYSICAL_UNIT_HAS_NO_BOUND_ADDRESS" in result.failed_conditions


def test_off_control_not_passed_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(off_control_passed=False))
    assert result.admitted is False
    assert "TARGET_SPECIFIC_OFF_CONTROL_NOT_AVAILABLE_OR_NOT_PASSED" in result.failed_conditions


def test_no_native_session_corroboration_fails():
    result = evaluate_capture_admission_v2(**_admission_kwargs(native_target_observation_count=0))
    assert result.admitted is False
    assert "NO_NATIVE_SESSION_CORROBORATION" in result.failed_conditions


def test_native_corroboration_is_session_level_not_per_packet():
    # A single native observation anywhere in the session is enough to admit
    # every eligible PDU in that capture -- no per-packet timestamp match required.
    rows = [{"advertiser_address_canonical": _TARGET_ADDRESS, "pdu_type": "ADV_IND"} for _ in range(50)]
    result = evaluate_capture_admission_v2(**_admission_kwargs(native_target_observation_count=1, ledger_rows=rows))
    assert result.admitted is True
    assert result.admitted_pdu_count == 50


def test_other_address_pdus_never_counted_as_target_emitted():
    rows = [{"advertiser_address_canonical": _OTHER_ADDRESS, "pdu_type": "ADV_IND"}]
    result = evaluate_capture_admission_v2(**_admission_kwargs(ledger_rows=rows))
    assert result.admitted is False
    assert result.direct_target_pdu_count == 0


def test_summarize_unit_admission_aggregates_and_reports_readiness():
    admitted = evaluate_capture_admission_v2(**_admission_kwargs(capture_id="cap-A"))
    excluded = evaluate_capture_admission_v2(**_admission_kwargs(capture_id="cap-B", off_control_passed=False))
    summary = summarize_unit_admission("UNIT-01", [admitted, excluded], off_control_passed=True)
    assert summary.eligible_captures == 2
    assert summary.admitted_captures == 1
    assert summary.admitted_direct_pdus == 1
    assert summary.readiness == "READY"
    assert [r.capture_id for r in summary.excluded_captures] == ["cap-B"]


def test_summarize_unit_admission_blocked_when_off_control_fails():
    admitted = evaluate_capture_admission_v2(**_admission_kwargs())
    summary = summarize_unit_admission("UNIT-01", [admitted], off_control_passed=False)
    assert summary.readiness == "BLOCKED"


def test_off_control_passes_when_target_address_never_appears():
    result = evaluate_target_specific_off_control(
        physical_unit_id="UNIT-01", bound_address=_TARGET_ADDRESS,
        negative_session_native_rows=[[{"address": _OTHER_ADDRESS}], [{"address": _OTHER_ADDRESS}]],
        negative_session_ledger_rows=[[{"advertiser_address_canonical": _OTHER_ADDRESS}], []],
    )
    assert result.passed is True
    assert result.negative_sessions == 2
    assert result.false_target_attributions == 0


def test_off_control_fails_when_target_address_appears_natively():
    result = evaluate_target_specific_off_control(
        physical_unit_id="UNIT-01", bound_address=_TARGET_ADDRESS,
        negative_session_native_rows=[[{"address": _TARGET_ADDRESS}]],
        negative_session_ledger_rows=[[]],
    )
    assert result.passed is False
    assert result.target_native_observations == 1


def test_off_control_fails_when_target_address_decoded_by_sdr():
    result = evaluate_target_specific_off_control(
        physical_unit_id="UNIT-01", bound_address=_TARGET_ADDRESS,
        negative_session_native_rows=[[{"address": _OTHER_ADDRESS}]],
        negative_session_ledger_rows=[[{"advertiser_address_canonical": _TARGET_ADDRESS}]],
    )
    assert result.passed is False
    assert result.target_sdr_compatible_pdus == 1


def test_off_control_fails_with_zero_negative_sessions():
    result = evaluate_target_specific_off_control(
        physical_unit_id="UNIT-01", bound_address=_TARGET_ADDRESS,
        negative_session_native_rows=[], negative_session_ledger_rows=[],
    )
    assert result.passed is False
    assert result.negative_sessions == 0


def test_off_control_fails_without_bound_address():
    result = evaluate_target_specific_off_control(
        physical_unit_id="UNIT-01", bound_address=None,
        negative_session_native_rows=[[{"address": _OTHER_ADDRESS}]], negative_session_ledger_rows=[[]],
    )
    assert result.passed is False
