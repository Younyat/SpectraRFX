"""Known-outcome tests for the frozen threshold-selection rule (point 4):
scan the grid, pick the SMALLEST value meeting coverage + zero-false-strong
simultaneously, never the one that produces the most associations."""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.calibration import NoThresholdSatisfiesCriteriaError, select_association_policy, select_association_threshold
from app.modules.ble_scientific_results.contracts import AssociationPolicy, CalibrationEventRecord


def _event(residual: float, *, second: float | None = None, address_match: bool = True, field_match: bool = True, unit="UNIT-A", capture="CAP-1", absence=False) -> CalibrationEventRecord:
    return CalibrationEventRecord(
        native_event_id=f"native-{residual}-{second}", sdr_packet_id="pkt-1", physical_unit_id=unit, capture_id=capture,
        native_timestamp_utc="2026-08-06T00:00:00Z", sdr_timestamp_utc="2026-08-06T00:00:00Z",
        absolute_residual_ms=residual, decoded_address_match=address_match, decoded_field_match=field_match,
        best_candidate_residual_ms=residual, second_candidate_residual_ms=second,
        number_of_competing_candidates=0 if second is None else 1, is_target_absence_control=absence,
    )


def _policy_kwargs(**overrides):
    base = dict(
        threshold_grid=[50, 100, 150, 200, 250, 300, 400, 500], calibration_campaign_id="CAL-1",
        devices_used=["UNIT-A", "UNIT-B"], captures_used=["CAP-1", "CAP-2"],
        callback_batching_policy="per-capture", duplicate_policy="first-decoded-wins", field_match_policy="address+PDU-type",
    )
    base.update(overrides)
    return base


def test_selects_smallest_threshold_meeting_both_criteria():
    # At 50ms coverage is too low (only 1/4); at 150ms coverage reaches
    # 4/4=100% and the control has no false strongs -> 150 must be picked,
    # not a larger threshold that would also technically qualify.
    calibration_events = [_event(30.0), _event(80.0), _event(120.0), _event(140.0)]
    control_events = [_event(300.0, absence=True)]  # far outside every small threshold
    policy = select_association_threshold(calibration_events=calibration_events, target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())
    assert policy.threshold_ms == 150
    assert policy.threshold_grid == [50, 100, 150, 200, 250, 300, 400, 500]
    assert policy.target_absence_result["false_strong_at_selected_threshold"] == 0


def test_rejects_every_threshold_once_the_control_residual_is_reached_even_if_coverage_is_perfect():
    # Coverage reaches 100% already at the smallest grid value (50ms), but
    # the control event's own residual (45ms) is inside every threshold
    # from 50ms upward -- since a threshold only ever WIDENS the accepted
    # gate, once a control event is inside it stays inside at every larger
    # threshold too. No grid value can ever be safe here: fail closed.
    calibration_events = [_event(30.0), _event(40.0)]
    control_events = [_event(45.0, absence=True)]
    with pytest.raises(NoThresholdSatisfiesCriteriaError):
        select_association_threshold(calibration_events=calibration_events, target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())


def test_ambiguous_event_never_counts_as_valid_strong_even_within_threshold():
    # Both candidates admissible at 150ms -> AMBIGUOUS, never promoted.
    calibration_events = [_event(50.0, second=90.0), _event(60.0, second=95.0)]
    control_events = []
    with pytest.raises(NoThresholdSatisfiesCriteriaError):
        select_association_threshold(calibration_events=calibration_events, target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())


def test_field_or_address_mismatch_never_counts_as_valid_strong():
    calibration_events = [_event(30.0, address_match=False), _event(40.0, field_match=False)]
    with pytest.raises(NoThresholdSatisfiesCriteriaError):
        select_association_threshold(calibration_events=calibration_events, target_absence_events=[], minimum_coverage=0.95, **_policy_kwargs())


def test_fails_closed_when_no_threshold_in_grid_ever_satisfies_criteria():
    # Coverage never reaches 95% at any grid value (half the events are
    # far outside even the largest threshold).
    calibration_events = [_event(30.0), _event(30.0), _event(9999.0), _event(9999.0)]
    with pytest.raises(NoThresholdSatisfiesCriteriaError):
        select_association_threshold(calibration_events=calibration_events, target_absence_events=[], minimum_coverage=0.95, **_policy_kwargs())


def test_never_selects_a_threshold_purely_because_it_maximizes_associations():
    # 100ms would already give 100% coverage and zero false strongs -- a
    # "maximize associations" rule might still wander to a larger threshold
    # for no reason; this must not happen: the smallest qualifying value
    # (100) must be selected even though 500 would also technically qualify.
    calibration_events = [_event(40.0), _event(60.0), _event(90.0)]
    control_events = [_event(500.0, absence=True)]
    policy = select_association_threshold(calibration_events=calibration_events, target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())
    assert policy.threshold_ms == 100


def test_select_association_policy_returns_a_single_global_policy_when_it_succeeds():
    calibration_events = [_event(30.0, unit="unit-A"), _event(40.0, unit="unit-A"), _event(45.0, unit="unit-A")]
    control_events = [_event(300.0, unit="unit-A", absence=True)]
    result = select_association_policy(
        calibration_events=calibration_events, target_absence_events=control_events, device_family_by_unit={"unit-A": "FAMILY_A"},
        minimum_coverage=0.95, **_policy_kwargs(),
    )
    assert isinstance(result, AssociationPolicy)
    assert result.threshold_ms == 50


def test_select_association_policy_falls_back_to_per_family_stratification_when_global_fails():
    # Family A needs only t=50 for 100% coverage; family B needs t=200.
    # Family A's own control (100) is safely above A's own needed threshold
    # but sits BELOW family B's needed threshold -- so a single global
    # threshold covering both families always drags family A's control
    # into the accepted gate. Global must fail at every grid point; each
    # family stratified on its own must succeed.
    calibration_events = [
        _event(20.0, unit="unit-A", capture="CAP-A"), _event(25.0, unit="unit-A", capture="CAP-A"), _event(30.0, unit="unit-A", capture="CAP-A"),
        _event(150.0, unit="unit-B", capture="CAP-B"), _event(160.0, unit="unit-B", capture="CAP-B"), _event(170.0, unit="unit-B", capture="CAP-B"),
    ]
    control_events = [_event(100.0, unit="unit-A", capture="CAP-A", absence=True), _event(500.0, unit="unit-B", capture="CAP-B", absence=True)]
    device_family_by_unit = {"unit-A": "FAMILY_A", "unit-B": "FAMILY_B"}

    result = select_association_policy(
        calibration_events=calibration_events, target_absence_events=control_events, device_family_by_unit=device_family_by_unit,
        minimum_coverage=0.95, **_policy_kwargs(),
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"FAMILY_A", "FAMILY_B"}
    assert result["FAMILY_A"].threshold_ms == 50
    assert result["FAMILY_B"].threshold_ms == 200


def test_select_association_policy_fails_closed_when_a_family_also_fails():
    calibration_events = [_event(20.0, unit="unit-A"), _event(9999.0, unit="unit-A")]  # unit-A itself never reaches 95% coverage
    control_events = []
    with pytest.raises(NoThresholdSatisfiesCriteriaError):
        select_association_policy(
            calibration_events=calibration_events, target_absence_events=control_events, device_family_by_unit={"unit-A": "FAMILY_A"},
            minimum_coverage=0.95, **_policy_kwargs(),
        )


def test_no_threshold_satisfies_criteria_error_carries_the_real_sweep_structurally():
    # Paper-representation pass (2026-08-17): the per-threshold sweep must be
    # readable as real attributes, not only recoverable by parsing the
    # message string.
    calibration_events = [_event(30.0), _event(30.0), _event(9999.0), _event(9999.0)]
    with pytest.raises(NoThresholdSatisfiesCriteriaError) as excinfo:
        select_association_threshold(calibration_events=calibration_events, target_absence_events=[], minimum_coverage=0.95, **_policy_kwargs())
    error = excinfo.value
    assert error.threshold_grid == [50, 100, 150, 200, 250, 300, 400, 500]
    assert error.minimum_coverage == 0.95
    assert set(error.coverage_by_threshold_ms.keys()) == set(error.threshold_grid)
    assert all(v == 0 for v in error.false_strong_by_threshold_ms.values())  # no control events supplied
    assert error.coverage_by_threshold_ms[500] == 0.5  # 2 of 4 events within even the largest grid value


def test_select_association_policy_re_raises_the_real_global_sweep_when_no_family_info_exists():
    # No device_family_by_unit entries at all -- previously raised a bare
    # message with zero structured data; now re-raises the real global
    # attempt's own sweep instead.
    calibration_events = [_event(20.0, unit="unit-A"), _event(9999.0, unit="unit-A")]
    with pytest.raises(NoThresholdSatisfiesCriteriaError) as excinfo:
        select_association_policy(
            calibration_events=calibration_events, target_absence_events=[], device_family_by_unit={},
            minimum_coverage=0.95, **_policy_kwargs(),
        )
    assert excinfo.value.coverage_by_threshold_ms  # real, non-empty sweep, not a bare message


def test_policy_hash_changes_when_selected_threshold_changes():
    control_events = [_event(300.0, absence=True)]
    policy_a = select_association_threshold(calibration_events=[_event(40.0), _event(60.0), _event(90.0)], target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())
    policy_b = select_association_threshold(calibration_events=[_event(40.0), _event(60.0), _event(140.0)], target_absence_events=control_events, minimum_coverage=0.95, **_policy_kwargs())
    assert policy_a.threshold_ms != policy_b.threshold_ms
    assert policy_a.policy_hash != policy_b.policy_hash
