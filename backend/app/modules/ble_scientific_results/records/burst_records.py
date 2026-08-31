"""ScientificBurstRecord builder.

One burst = one row of `candidate_manifest.jsonl` (the pipeline's own real
RF-burst unit -- verified via direct research this session against
`ble_offline_replay.py`, not assumed). Its decode/association details, when
present, come from the matching row of `packet_association_ledger.jsonl`
(same `candidate_id`).

**Association semantics correction (post Fase-2 review)**: `physical_unit_id`
being resolved on the underlying `ExampleRecord` must NEVER, by itself,
promote a burst to `TARGET_ASSOCIATED_PACKET`. That resolution can come from
`PHYSICAL_ISOLATION_DECLARED` (an operator's prior declaration -- weaker
ground truth, no independent cross-check, see
docs/ble/SCIENTIFIC_STATUS.md), which is a real and useful signal but not a
strong RFFI association. `TARGET_ASSOCIATED_PACKET` requires the frozen
native<->SDR criterion below to actually pass for THIS burst's own ledger
row.

**STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN (post-calibration-request
correction)**: `TARGET_ASSOCIATED_PACKET` additionally requires a real,
frozen `AssociationPolicy` (produced only by a real calibration campaign --
see calibration/association_calibration.py) to be passed in. Without one,
`_passes_target_association_criterion` always returns False, regardless of
what the ledger row itself contains -- there is no default threshold to
silently fall back to. `ASSOCIATION_TIME_THRESHOLD_MS` (250 ms, the exact
constant `_associate()` hardcodes in `ble_offline_replay.py`) is kept ONLY
as a diagnostic reference for `_would_pass_with_legacy_threshold`, which
flags (never classifies) a burst that would have qualified under the old,
pre-calibration rule -- so a row disabled purely for lacking a frozen
policy is visibly distinct from one that genuinely fails association.

Fields whose source was added this pass (synchronization_score, symbol_phase,
frequency_offset_hz, frequency_fit_quality) are read from the ledger row
when present; on captures replayed BEFORE the decoder plumbing fix (see
records/build_records.py's docstring and the external ble-worker-lab repo),
they will still be absent on old ledger rows -- absence is detected
per-row, not assumed statically, so this code is correct for both old and
newly-replayed real data. competing_energy/clipping_overlap/
discontinuity_overlap/edge_margin_samples/burst_snr_db have no source
anywhere yet (confirmed by direct code research, not assumed) and are
always None + not_documented.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.ble_rffi_studio.contracts import ExampleRecord

from ..contracts import AssociationPolicy, BurstClass, ScientificBurstRecord, SourceIdentityOrigin

# The exact constant _associate() already hardcodes in ble_offline_replay.py
# (verified this session, not assumed). No longer used to classify a burst
# (see STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN above) -- kept only
# as the reference value _would_pass_with_legacy_threshold diagnoses against.
ASSOCIATION_TIME_THRESHOLD_MS = 250.0

# Genuinely absent everywhere in ble_rffi_studio's real pipeline today
# (confirmed by direct code research) -- no per-burst source exists to
# compute these from, so they are always None + not_documented.
_STRUCTURALLY_ABSENT_BURST_FIELDS = (
    "competing_energy", "clipping_overlap", "discontinuity_overlap", "edge_margin_samples", "burst_snr_db",
    "burst_start_utc_estimate", "detector_version", "native_event_id", "association_cost", "burst_quality",
)

# Optional (present only on ledger rows written after the decoder-plumbing
# fix, see docstring above) -- checked per-row, not assumed present.
_OPTIONAL_LEDGER_FIELDS = ("synchronization_score", "symbol_phase", "frequency_offset_hz", "frequency_fit_quality")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _passes_target_association_criterion(ledger_row: dict | None, association_policy: AssociationPolicy | None) -> bool:
    """The frozen criterion for TARGET_ASSOCIATED_PACKET: unique association
    (address_match_status == MATCHED, i.e. exactly one native candidate in
    the window shared this address -- AMBIGUOUS means more than one),
    admissible time residual, compatible content (target_address_match),
    and no rejection reason recorded. STRONG in the ledger already implies
    is_target + MATCHED (see ble_offline_replay.py's own
    association_strength computation) -- re-checked explicitly here anyway
    so this function's own criterion is self-contained and never silently
    depends on the ledger's internal logic staying exactly as-is.

    STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN: with no real, frozen
    `association_policy`, this ALWAYS returns False -- there is no default
    threshold to fall back to. See _would_pass_with_legacy_threshold for
    the diagnostic-only check against the old hardcoded rule."""
    if association_policy is None:
        return False
    if ledger_row is None:
        return False
    if ledger_row.get("association_strength") != "STRONG":
        return False
    if ledger_row.get("address_match_status") != "MATCHED":
        return False
    if ledger_row.get("association_rejection_reason"):
        return False
    if ledger_row.get("target_address_match") is not True:
        return False
    time_delta_ms = ledger_row.get("time_delta_ms")
    if time_delta_ms is None or float(time_delta_ms) > association_policy.threshold_ms:
        return False
    return True


def _would_pass_with_legacy_threshold(ledger_row: dict | None) -> bool:
    """Diagnostic only, NEVER used to classify a burst: would this row have
    qualified under the pre-calibration hardcoded 250ms rule? Lets a burst
    disabled purely for lacking a frozen AssociationPolicy be flagged as
    such, distinct from one that genuinely fails association on its own
    merits."""
    if ledger_row is None:
        return False
    if ledger_row.get("association_strength") != "STRONG":
        return False
    if ledger_row.get("address_match_status") != "MATCHED":
        return False
    if ledger_row.get("association_rejection_reason"):
        return False
    if ledger_row.get("target_address_match") is not True:
        return False
    time_delta_ms = ledger_row.get("time_delta_ms")
    if time_delta_ms is None or float(time_delta_ms) > ASSOCIATION_TIME_THRESHOLD_MS:
        return False
    return True


def _burst_class_and_origin(candidate: dict, ledger_row: dict | None, physical_unit_id: str | None, association_policy: AssociationPolicy | None) -> tuple[BurstClass, SourceIdentityOrigin, str | None]:
    """CRC validity comes from the candidate's OWN crc_status
    (candidate_manifest.jsonl) -- never gated on a ledger row existing.

    burst_class is NOT a simple decode-quality ladder -- it is a claim about
    IDENTITY STRENGTH first: any identity that came only from operator
    context/declaration (OPERATOR_CONTEXT_DECLARED) is SOURCE_CONTEXT_ONLY
    REGARDLESS of whether the packet itself decoded with a valid CRC --
    exactly the user's own framing ("nunca para una etiqueta fuerte de
    RFFI"). CRC_VALID_PACKET is reserved for a genuinely unknown
    transmitter (no identity claim of either kind) that still decoded
    successfully. Only ASSOCIATION_STRONG (the frozen native<->SDR
    criterion actually passing for THIS burst) may produce
    TARGET_ASSOCIATED_PACKET -- and even then only if the packet itself is
    CRC-valid (an association without a decodable packet cannot be
    "target-associated content")."""
    crc_valid = candidate.get("processing_status") == "PROCESSED" and candidate.get("crc_status") == "VALID"

    if _passes_target_association_criterion(ledger_row, association_policy):
        origin: SourceIdentityOrigin = "ASSOCIATION_STRONG"
        authority = f"burst_records._passes_target_association_criterion (native<->SDR STRONG association, <={association_policy.threshold_ms}ms residual per frozen policy {association_policy.policy_id}, MATCHED, no rejection)"
        burst_class: BurstClass = "TARGET_ASSOCIATED_PACKET" if crc_valid else "SOURCE_CONTEXT_ONLY"
    elif physical_unit_id is not None:
        origin = "OPERATOR_CONTEXT_DECLARED"
        authority = "EvidenceStage.physical_unit_id (PHYSICAL_ISOLATION_DECLARED or address-binding resolution -- weaker ground truth, no independent cross-check)"
        burst_class = "SOURCE_CONTEXT_ONLY"
    else:
        origin = "NONE"
        authority = None
        burst_class = "CRC_VALID_PACKET" if crc_valid else "SOURCE_CONTEXT_ONLY"
    return burst_class, origin, authority


def build_burst_records(
    *, capture_id: str, replay_dir: Path | None, examples: list[ExampleRecord],
    association_policy_hash: str | None, capture_eligible: bool, association_policy: AssociationPolicy | None = None,
) -> list[ScientificBurstRecord]:
    if replay_dir is None:
        return []

    candidates = _read_jsonl(replay_dir / "candidate_manifest.jsonl")
    ledger_by_candidate = {row["candidate_id"]: row for row in _read_jsonl(replay_dir / "packet_association_ledger.jsonl") if row.get("candidate_id")}
    example_by_candidate = {example.candidate_id: example for example in examples}
    # The frozen policy's own hash always wins over whatever hash the
    # caller passed in -- the two must never silently diverge once a real
    # policy exists.
    effective_policy_hash = association_policy.policy_hash if association_policy is not None else association_policy_hash

    records: list[ScientificBurstRecord] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        ledger_row = ledger_by_candidate.get(candidate_id)
        example = example_by_candidate.get(candidate_id)
        physical_unit_id = example.physical_unit_id if example else None

        not_documented = list(_STRUCTURALLY_ABSENT_BURST_FIELDS)
        optional_values: dict[str, float | None] = {}
        for field in _OPTIONAL_LEDGER_FIELDS:
            if ledger_row is not None and field in ledger_row and ledger_row[field] is not None:
                optional_values[field] = ledger_row[field]
            else:
                optional_values[field] = None
                not_documented.append(field)

        source_artifact_ids = [candidate_id] if candidate_id else []
        if ledger_row:
            source_artifact_ids.append(ledger_row.get("packet_id", ""))
        if example:
            source_artifact_ids.append(example.example_id)

        burst_class, source_identity_origin, label_authority = _burst_class_and_origin(candidate, ledger_row, physical_unit_id, association_policy)

        packet_eligible = candidate.get("processing_status") == "PROCESSED" and candidate.get("crc_status") == "VALID"
        label_eligible = source_identity_origin != "NONE"
        training_eligible = packet_eligible and label_eligible and capture_eligible

        blocking_reason_codes: list[str] = []
        diagnostic_flags: list[str] = []
        if candidate.get("processing_status") != "PROCESSED":
            blocking_reason_codes.append(f"PROCESSING_{candidate.get('processing_status') or 'UNKNOWN'}")
        elif candidate.get("crc_status") != "VALID":
            blocking_reason_codes.append("NO_CRC_VALID_PACKET")
        if not label_eligible:
            blocking_reason_codes.append("NO_TARGET_ASSOCIATION")
        # An association rejection reason is diagnostic, not blocking, when
        # the burst is otherwise packet_eligible -- e.g. MULTIPLE_NATIVE_
        # CALLBACKS is a normal, expected candidate-level ambiguity, never a
        # protocol failure (see campaign_deviations.py's classification).
        if ledger_row and ledger_row.get("association_rejection_reason"):
            diagnostic_flags.append(f"ASSOCIATION_{ledger_row['association_rejection_reason']}")
        if association_policy is None and _would_pass_with_legacy_threshold(ledger_row):
            diagnostic_flags.append("STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN")
        elif ledger_row and ledger_row.get("association_strength") == "STRONG" and not _passes_target_association_criterion(ledger_row, association_policy):
            diagnostic_flags.append("STRONG_BUT_FAILED_FULL_CRITERION")

        records.append(ScientificBurstRecord(
            burst_id=candidate.get("burst_id") or candidate_id, capture_id=capture_id,
            burst_class=burst_class, source_identity_origin=source_identity_origin,
            sample_start=candidate.get("start_sample", 0), sample_end=candidate.get("end_sample", 0),
            burst_start_utc_estimate=None, decision_window_id=candidate_id, candidate_group_id=candidate_id,
            detector_version=None,
            synchronization_status="LOCKED" if candidate.get("processing_status") == "PROCESSED" else "NOT_LOCKED",
            synchronization_score=optional_values["synchronization_score"], symbol_phase=optional_values["symbol_phase"],
            frequency_offset_hz=optional_values["frequency_offset_hz"], frequency_fit_quality=optional_values["frequency_fit_quality"],
            crc_status=candidate.get("crc_status"),
            decoded_pdu_type=(ledger_row or {}).get("pdu_type"), decoded_adva=(ledger_row or {}).get("advertiser_address_canonical"),
            decoded_payload_hash=(ledger_row or {}).get("payload_sha256"),
            native_event_id=None, association_status=(ledger_row or {}).get("association_strength"),
            association_time_residual_ms=(ledger_row or {}).get("time_delta_ms"), association_cost=None,
            association_policy_hash=effective_policy_hash, label_authority=label_authority,
            packet_eligible=packet_eligible, label_eligible=label_eligible, training_eligible=training_eligible,
            blocking_reason_codes=blocking_reason_codes, diagnostic_flags=diagnostic_flags,
            source_artifact_ids=source_artifact_ids, not_documented_fields=sorted(set(not_documented)),
        ))
    return records
