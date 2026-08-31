from __future__ import annotations

from app.modules.ble_scientific_results.calibration.existing_capture_reconstruction import (
    PILOT_REQUIRED_FIELDS,
    calibration_event_from_ledger_row,
    evaluate_capture_eligibility,
    find_enrolled_devices_in_native_scan,
)

_ALL_PILOT_PRESENT = {name: True for name in PILOT_REQUIRED_FIELDS}
_NO_PILOT_PRESENT = {name: False for name in PILOT_REQUIRED_FIELDS}


def _facts(**overrides) -> dict:
    base = dict(
        has_source_iq=True, has_channel=True, has_sample_rate=True, has_timestamp=True,
        has_native_observations=True, has_association_ledger=True, has_crc_valid_packets=True,
        has_declared_target_device=True, pilot_fields_present=_NO_PILOT_PRESENT,
    )
    base.update(overrides)
    return base


def test_full_facts_with_no_pilot_fields_is_calibration_eligible():
    result = evaluate_capture_eligibility(**_facts())
    assert result.classification == "ASSOCIATION_CALIBRATION_ELIGIBLE"
    assert result.missing_fields == PILOT_REQUIRED_FIELDS


def test_full_facts_with_pilot_fields_is_pilot_eligible():
    result = evaluate_capture_eligibility(**_facts(pilot_fields_present=_ALL_PILOT_PRESENT))
    assert result.classification == "QUALIFICATION_PILOT_ELIGIBLE"
    assert result.missing_fields == ()


def test_missing_crc_valid_is_diagnostic_only():
    result = evaluate_capture_eligibility(**_facts(has_crc_valid_packets=False))
    assert result.classification == "DIAGNOSTIC_ONLY"
    assert "crc_valid_packets" in result.missing_fields


def test_missing_native_observations_is_diagnostic_only():
    result = evaluate_capture_eligibility(**_facts(has_native_observations=False))
    assert result.classification == "DIAGNOSTIC_ONLY"


def test_missing_declared_target_is_diagnostic_only():
    result = evaluate_capture_eligibility(**_facts(has_declared_target_device=False))
    assert result.classification == "DIAGNOSTIC_ONLY"


def test_partial_pilot_fields_stays_calibration_eligible_not_pilot():
    partial = dict(_ALL_PILOT_PRESENT)
    partial["day_id"] = False
    result = evaluate_capture_eligibility(**_facts(pilot_fields_present=partial))
    assert result.classification == "ASSOCIATION_CALIBRATION_ELIGIBLE"
    assert result.missing_fields == ("day_id",)


def _ledger_row(**overrides) -> dict:
    base = dict(
        packet_id="pkt-1", time_delta_ms=42.0, temporal_match_status="MATCHED",
        address_match_status="MATCHED", pdu_type="ADV_IND", nearest_windows_callback_timestamp=None,
    )
    base.update(overrides)
    return base


def test_calibration_event_matched_row_has_no_second_candidate():
    event = calibration_event_from_ledger_row(_ledger_row(), device_id="DEV-1", capture_id="CAP-1", fallback_timestamp="2026-08-06T00:00:00Z")
    assert event.decoded_address_match is True
    assert event.best_candidate_residual_ms == 42.0
    assert event.second_candidate_residual_ms is None
    assert event.number_of_competing_candidates == 1


def test_calibration_event_ambiguous_row_forces_second_candidate_inside_any_gate():
    event = calibration_event_from_ledger_row(_ledger_row(temporal_match_status="AMBIGUOUS", address_match_status="NO_CANDIDATE_IN_WINDOW"), device_id="DEV-1", capture_id="CAP-1", fallback_timestamp="2026-08-06T00:00:00Z")
    assert event.second_candidate_residual_ms == 0.0
    assert event.number_of_competing_candidates == 2


def test_calibration_event_matched_non_target_is_not_decoded_address_match():
    event = calibration_event_from_ledger_row(_ledger_row(address_match_status="MATCHED_NON_TARGET"), device_id="DEV-1", capture_id="CAP-1", fallback_timestamp="2026-08-06T00:00:00Z")
    assert event.decoded_address_match is False


def test_find_enrolled_devices_in_native_scan_detects_presence():
    native_rows = [{"address": "aa:bb:cc:dd:ee:ff"}, {"address": "11:22:33:44:55:66"}]
    addresses = {"DEV-A": "AA:BB:CC:DD:EE:FF", "DEV-B": "99:88:77:66:55:44"}
    assert find_enrolled_devices_in_native_scan(native_rows, addresses) == ["DEV-A"]


def test_find_enrolled_devices_in_native_scan_empty_when_none_present():
    native_rows = [{"address": "00:00:00:00:00:01"}]
    addresses = {"DEV-A": "AA:BB:CC:DD:EE:FF"}
    assert find_enrolled_devices_in_native_scan(native_rows, addresses) == []
