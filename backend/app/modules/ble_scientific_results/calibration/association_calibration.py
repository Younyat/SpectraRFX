"""Objective, non-cherry-picked selection of the native<->SDR association
time threshold from a real calibration campaign -- user's explicit rule
(point 4 of the post-calibration request): scan a FROZEN grid, pick the
SMALLEST threshold that simultaneously satisfies coverage and zero-false-
strong criteria, never the value that happens to produce the most
associations. Ground truth for every calibration event comes from physical
isolation of the active unit (CALIBRATION_GROUND_TRUTH on
CalibrationEventRecord), never from the association algorithm's own output.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..contracts import AssociationPolicy, CalibrationEventRecord


class NoThresholdSatisfiesCriteriaError(Exception):
    """Raised when NO value in the frozen grid meets both criteria at every
    tested threshold -- fails closed. Never silently falls back to "the
    least-bad" threshold; the caller must re-run calibration with a wider
    grid, more captures, or investigate the association pipeline itself.

    Paper-representation pass (2026-08-17): carries the real per-threshold
    sweep as structured attributes (never only inside the message string)
    so a caller can persist/display the diagnostic sweep even though no
    policy could be frozen -- this is exactly the real data the selection
    rule already computed internally; only its previous presentation (a
    stringified dict embedded in free text) made it unusable for anything
    but a log line."""

    def __init__(
        self, message: str, *, threshold_grid: list[float], minimum_coverage: float,
        coverage_by_threshold_ms: dict[float, float], false_strong_by_threshold_ms: dict[float, int],
        ambiguous_by_threshold_ms: dict[float, int],
    ) -> None:
        super().__init__(message)
        self.threshold_grid = threshold_grid
        self.minimum_coverage = minimum_coverage
        self.coverage_by_threshold_ms = coverage_by_threshold_ms
        self.false_strong_by_threshold_ms = false_strong_by_threshold_ms
        self.ambiguous_by_threshold_ms = ambiguous_by_threshold_ms


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_valid_strong(event: CalibrationEventRecord, threshold_ms: float) -> bool:
    if event.best_candidate_residual_ms is None or event.best_candidate_residual_ms > threshold_ms:
        return False
    if not event.decoded_address_match or not event.decoded_field_match:
        return False
    # A second candidate inside the same accepted gate makes this event
    # AMBIGUOUS -- never promoted just for being the closer of the two.
    if event.second_candidate_residual_ms is not None and event.second_candidate_residual_ms <= threshold_ms:
        return False
    return True


def _is_ambiguous(event: CalibrationEventRecord, threshold_ms: float) -> bool:
    return (
        event.best_candidate_residual_ms is not None and event.best_candidate_residual_ms <= threshold_ms
        and event.second_candidate_residual_ms is not None and event.second_candidate_residual_ms <= threshold_ms
    )


def is_valid_strong_event(event: CalibrationEventRecord, threshold_ms: float) -> bool:
    """Public wrapper -- the SAME criterion select_association_threshold
    uses internally, exposed so a single real capture (e.g. a target-
    absence control run outside a full calibration campaign) can be
    checked against a threshold without re-deriving the rule."""
    return _is_valid_strong(event, threshold_ms)


def is_ambiguous_event(event: CalibrationEventRecord, threshold_ms: float) -> bool:
    return _is_ambiguous(event, threshold_ms)


def false_strong_counts_by_threshold(events: list[CalibrationEventRecord], threshold_grid: list[float]) -> dict[float, int]:
    """Same aggregate select_association_threshold computes internally for
    its own target_absence_events, exposed for a standalone control run
    (e.g. the Guided Validation "Reinforced Target-Absence Control"
    action) that has no calibration_events counterpart to pair it with."""
    return {threshold: sum(1 for event in events if _is_valid_strong(event, threshold)) for threshold in sorted(threshold_grid)}


def select_association_threshold(
    *, calibration_events: list[CalibrationEventRecord], target_absence_events: list[CalibrationEventRecord],
    threshold_grid: list[float], calibration_campaign_id: str, devices_used: list[str], captures_used: list[str],
    callback_batching_policy: str, duplicate_policy: str, field_match_policy: str,
    minimum_coverage: float = 0.95,
) -> AssociationPolicy:
    if not calibration_events:
        raise ValueError("NEED_AT_LEAST_ONE_CALIBRATION_EVENT")
    sorted_grid = sorted(threshold_grid)

    coverage_by_threshold: dict[float, float] = {}
    false_strong_by_threshold: dict[float, int] = {}
    ambiguous_by_threshold: dict[float, int] = {}
    selected_threshold: float | None = None

    for threshold in sorted_grid:
        valid_count = sum(1 for event in calibration_events if _is_valid_strong(event, threshold))
        coverage = valid_count / len(calibration_events)
        false_strong = sum(1 for event in target_absence_events if _is_valid_strong(event, threshold))
        ambiguous = sum(1 for event in calibration_events if _is_ambiguous(event, threshold))
        coverage_by_threshold[threshold] = coverage
        false_strong_by_threshold[threshold] = false_strong
        ambiguous_by_threshold[threshold] = ambiguous
        if selected_threshold is None and coverage >= minimum_coverage and false_strong == 0:
            selected_threshold = threshold

    if selected_threshold is None:
        raise NoThresholdSatisfiesCriteriaError(
            f"NO_THRESHOLD_IN_GRID_SATISFIES_CRITERIA:grid={sorted_grid}:"
            f"coverage_by_threshold={coverage_by_threshold}:false_strong_by_threshold={false_strong_by_threshold}",
            threshold_grid=sorted_grid, minimum_coverage=minimum_coverage,
            coverage_by_threshold_ms=coverage_by_threshold, false_strong_by_threshold_ms=false_strong_by_threshold,
            ambiguous_by_threshold_ms=ambiguous_by_threshold,
        )

    selection_rule = (
        f"Smallest value in the frozen grid {sorted_grid} ms for which calibration coverage >= {minimum_coverage:.0%} "
        "AND zero false-strong associations occur in the reinforced target-absence control, where a 'valid strong' "
        "event additionally requires decoded_address_match, decoded_field_match, and no competing candidate residual "
        "inside the same accepted gate (such an event is AMBIGUOUS instead, never promoted for being closer)."
    )
    ambiguity_policy = (
        "A native event with two or more SDR candidate residuals within the accepted threshold is classified "
        "AMBIGUOUS and never promoted to a strong association, regardless of which candidate is closer in time."
    )
    target_absence_result = {
        "n_events": len(target_absence_events),
        "false_strong_by_threshold_ms": {str(t): count for t, count in false_strong_by_threshold.items()},
        "false_strong_at_selected_threshold": false_strong_by_threshold[selected_threshold],
    }

    frozen_at = utc_now()
    policy_id = AssociationPolicy.make_policy_id(calibration_campaign_id=calibration_campaign_id, frozen_at=frozen_at)
    fields = dict(
        policy_id=policy_id, threshold_ms=selected_threshold, threshold_grid=sorted_grid, selection_rule=selection_rule,
        calibration_campaign_id=calibration_campaign_id, devices_used=sorted(set(devices_used)), captures_used=sorted(set(captures_used)),
        callback_batching_policy=callback_batching_policy, duplicate_policy=duplicate_policy, field_match_policy=field_match_policy,
        ambiguity_policy=ambiguity_policy, target_absence_result=target_absence_result, frozen_at=frozen_at,
    )
    unhashed = AssociationPolicy(**fields, policy_hash="")
    policy_hash = unhashed.content_hash(exclude={"policy_hash"})
    return AssociationPolicy(**fields, policy_hash=policy_hash)


def select_association_policy(
    *, calibration_events: list[CalibrationEventRecord], target_absence_events: list[CalibrationEventRecord],
    device_family_by_unit: dict[str, str], threshold_grid: list[float], calibration_campaign_id: str,
    devices_used: list[str], captures_used: list[str], callback_batching_policy: str, duplicate_policy: str,
    field_match_policy: str, minimum_coverage: float = 0.95,
) -> AssociationPolicy | dict[str, AssociationPolicy]:
    """Point 9: try ONE global policy across all enrolled devices first
    (advertising intervals/callback behavior can differ enough by family
    that a single threshold may not fit everyone). Only if that fails does
    this fall back to a policy PER device_family -- never per capture, per
    the user's explicit rule -- and EVERY family with calibration events
    must itself succeed before any stratified policy is returned; if even
    one family fails, the whole selection fails closed (propagates
    NoThresholdSatisfiesCriteriaError), since a partially-frozen stratified
    policy would leave some real devices with no valid rule at all."""
    global_attempt_error: NoThresholdSatisfiesCriteriaError | None = None
    try:
        return select_association_threshold(
            calibration_events=calibration_events, target_absence_events=target_absence_events, threshold_grid=threshold_grid,
            calibration_campaign_id=calibration_campaign_id, devices_used=devices_used, captures_used=captures_used,
            callback_batching_policy=callback_batching_policy, duplicate_policy=duplicate_policy,
            field_match_policy=field_match_policy, minimum_coverage=minimum_coverage,
        )
    except NoThresholdSatisfiesCriteriaError as error:
        # `error` (the `except...as` binding) is auto-deleted by Python at
        # the end of this block -- must be copied to a name declared outside
        # it to survive for the re-raise below.
        global_attempt_error = error

    families = sorted({device_family_by_unit[event.physical_unit_id] for event in calibration_events if event.physical_unit_id in device_family_by_unit})
    if not families:
        # Re-raises the real global-attempt sweep (still the most informative
        # real data available here) rather than a bare message with none.
        raise global_attempt_error

    policies: dict[str, AssociationPolicy] = {}
    for family in families:
        family_calibration = [event for event in calibration_events if device_family_by_unit.get(event.physical_unit_id) == family]
        family_absence = [event for event in target_absence_events if device_family_by_unit.get(event.physical_unit_id) == family]
        if not family_calibration:
            continue
        # Propagates NoThresholdSatisfiesCriteriaError if THIS family also
        # fails -- every family must freeze successfully before ANY
        # stratified policy may be used for the definitive campaign.
        policies[family] = select_association_threshold(
            calibration_events=family_calibration, target_absence_events=family_absence, threshold_grid=threshold_grid,
            calibration_campaign_id=f"{calibration_campaign_id}-{family}",
            devices_used=sorted({event.physical_unit_id for event in family_calibration}),
            captures_used=sorted({event.capture_id for event in family_calibration}),
            callback_batching_policy=callback_batching_policy, duplicate_policy=duplicate_policy,
            field_match_policy=field_match_policy, minimum_coverage=minimum_coverage,
        )
    return policies
