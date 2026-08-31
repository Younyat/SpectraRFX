"""ScientificDecisionWindowRecord builder.

**Correction (post Fase-2 review)**: a decision window is now a real
TIME window (default 10 s, matching the paper's own design), not 1
candidate = 1 window as Fase 2 first shipped. Bursts are grouped by which
`window_duration_s`-wide slice of the capture their `sample_start` falls
into (`sample_start // (window_duration_s * sample_rate_hz)`), so a window
genuinely aggregates every candidate whose start time lands inside it --
not just a single burst wearing a "window" label. `window_status` is a
single three-valued field (INACTIVE / ACTIVE_INSUFFICIENT_BURSTS /
ACTIVE_ELIGIBLE) instead of two overlapping booleans.

No score/threshold/predicted_class/model decision field exists on this
record -- that is Fase 3+ territory (RQ1-4/S1-S2), explicitly out of scope
here. `minimum_eligible_bursts` is the only knob a future phase needs to
turn into a real gate (`window_score = median(burst_scores)`), left as a
plain parameter, not implemented.
"""
from __future__ import annotations

from ..contracts import ScientificBurstRecord, ScientificDecisionWindowRecord

DEFAULT_MINIMUM_ELIGIBLE_BURSTS = 1


def build_decision_window_records(
    *, capture_id: str, bursts: list[ScientificBurstRecord], sample_rate_hz: int, window_duration_s: float,
    minimum_eligible_bursts: int = DEFAULT_MINIMUM_ELIGIBLE_BURSTS,
) -> list[ScientificDecisionWindowRecord]:
    if not bursts or not sample_rate_hz or not window_duration_s:
        return []

    window_samples = int(round(window_duration_s * sample_rate_hz))
    if window_samples <= 0:
        return []

    by_window_index: dict[int, list[ScientificBurstRecord]] = {}
    for burst in bursts:
        window_index = burst.sample_start // window_samples
        by_window_index.setdefault(window_index, []).append(burst)

    records: list[ScientificDecisionWindowRecord] = []
    for window_index in sorted(by_window_index):
        window_bursts = by_window_index[window_index]
        candidate_ids = [b.burst_id for b in window_bursts]
        crc_valid_ids = [b.burst_id for b in window_bursts if b.burst_class in ("CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET")]
        target_associated_ids = [b.burst_id for b in window_bursts if b.burst_class == "TARGET_ASSOCIATED_PACKET"]
        eligible_ids = [b.burst_id for b in window_bursts if b.training_eligible]

        active = len(candidate_ids) > 0
        if not active:
            window_status = "INACTIVE"
        elif len(eligible_ids) >= minimum_eligible_bursts:
            window_status = "ACTIVE_ELIGIBLE"
        else:
            window_status = "ACTIVE_INSUFFICIENT_BURSTS"

        ineligibility_reasons: list[str] = []
        if window_status == "ACTIVE_INSUFFICIENT_BURSTS":
            ineligibility_reasons.append(f"BELOW_MINIMUM_ELIGIBLE_BURSTS:{len(eligible_ids)}<{minimum_eligible_bursts}")

        policy_hashes = {b.association_policy_hash for b in window_bursts if b.association_policy_hash}
        selection_policy_hash = next(iter(policy_hashes)) if len(policy_hashes) == 1 else None

        window_start_sample = window_index * window_samples
        records.append(ScientificDecisionWindowRecord(
            decision_window_id=f"{capture_id}-win-{window_index:05d}", capture_id=capture_id, window_index=window_index,
            window_duration_s=window_duration_s, window_start_sample=window_start_sample, window_end_sample=window_start_sample + window_samples,
            window_start_utc=None, window_end_utc=None, window_status=window_status,
            candidate_burst_ids=candidate_ids, crc_valid_burst_ids=crc_valid_ids, target_associated_burst_ids=target_associated_ids,
            eligible_burst_ids=eligible_ids, candidate_count=len(candidate_ids), crc_valid_count=len(crc_valid_ids),
            target_associated_count=len(target_associated_ids), eligible_count=len(eligible_ids),
            selection_policy_hash=selection_policy_hash, minimum_eligible_bursts=minimum_eligible_bursts,
            ineligibility_reason_codes=ineligibility_reasons, not_documented_fields=["window_start_utc", "window_end_utc"],
        ))
    return records
