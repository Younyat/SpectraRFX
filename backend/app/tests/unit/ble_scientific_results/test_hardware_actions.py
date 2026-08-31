from __future__ import annotations

from app.modules.ble_scientific_results.guided_validation.hardware_actions import classify_timing_diagnostic


def _classify(**overrides):
    base = dict(
        native_event_count=10, target_native_event_count=5, target_address_packet_count=3,
        narrow_window_valid_count=0, narrow_window_ambiguous_count=0, wide_window_residuals_ms=(),
    )
    base.update(overrides)
    return classify_timing_diagnostic(**base)


def test_no_native_events_at_all():
    result = _classify(native_event_count=0, target_native_event_count=0)
    assert result.code == "NATIVE_SCANNER_NOT_RUNNING"


def test_scanner_ran_but_never_saw_the_target():
    result = _classify(native_event_count=10, target_native_event_count=0)
    assert result.code == "NATIVE_SCANNER_COVERAGE_INSUFFICIENT"


def test_target_address_never_decoded():
    result = _classify(target_native_event_count=5, target_address_packet_count=0)
    assert result.code == "DECODED_FIELDS_DO_NOT_MATCH"


def test_unique_match_inside_gate_is_calibration_possible():
    result = _classify(narrow_window_valid_count=3, narrow_window_ambiguous_count=0)
    assert result.code == "ASSOCIATION_CALIBRATION_POSSIBLE"


def test_match_inside_gate_but_ambiguous():
    result = _classify(narrow_window_valid_count=3, narrow_window_ambiguous_count=2)
    assert result.code == "MULTIPLE_COMPETING_CANDIDATES"


def test_no_pairing_at_all_even_in_wide_window():
    result = _classify(narrow_window_valid_count=0, wide_window_residuals_ms=[])
    assert result.code == "NATIVE_SCANNER_COVERAGE_INSUFFICIENT"


def test_tight_cluster_close_to_gate_is_gate_too_narrow():
    result = _classify(narrow_window_valid_count=0, wide_window_residuals_ms=[300, 305, 310, 320])
    assert result.code == "TIME_GATE_TOO_NARROW"
    assert "307" in result.explanation or "308" in result.explanation


def test_tight_cluster_far_from_gate_is_timestamp_domains_incompatible():
    result = _classify(narrow_window_valid_count=0, wide_window_residuals_ms=[1995, 2000, 2005, 2010])
    assert result.code == "TIMESTAMP_DOMAINS_INCOMPATIBLE"


def test_scattered_residuals_are_coverage_insufficient_not_a_timing_offset():
    result = _classify(narrow_window_valid_count=0, wide_window_residuals_ms=[100, 500, 3000, 7000, 9000])
    assert result.code == "NATIVE_SCANNER_COVERAGE_INSUFFICIENT"


def test_every_result_carries_a_next_action():
    for kwargs in (
        dict(native_event_count=0),
        dict(target_native_event_count=0),
        dict(target_address_packet_count=0),
        dict(narrow_window_valid_count=1),
    ):
        result = _classify(**kwargs)
        assert result.next_action
        assert result.explanation
