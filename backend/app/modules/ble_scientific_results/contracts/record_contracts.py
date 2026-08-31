"""Fase 2 (+ association/eligibility/deviation correction pass), Section B:
the four canonical scientific record types. Each is a read-only, 1:1
mapping from a real ble_rffi_studio/replay artifact field to a named column
here -- never a computed/inferred value dressed up as a raw observation. A
field with no real source is `None`, and its name is added to
`not_documented_fields` on that record -- never silently defaulted to 0,
"", or an inferred guess. See `records/` for the builders that populate
these from real artifacts, and each field's builder-side comment for its
exact source.

No `E0`-`E6` literal appears anywhere in this file: `ScientificBurstRecord.
burst_class` uses its own, unrelated vocabulary.

Correction pass (post Fase-2 review): `physical_unit_id` being resolved
must never, by itself, promote a burst to `TARGET_ASSOCIATED_PACKET` --
that requires the frozen native<->SDR association criterion to actually
pass (see `records/burst_records.py::_burst_class`). Eligibility and
diagnostic observations are now two structurally separate lists
(`blocking_reason_codes` vs `diagnostic_flags`) instead of one ambiguous
`exclusion_reason_codes` next to a single `eligible` bool.
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

RECORD_SCHEMA_VERSION = "ble-scientific-results-records-v2"

# SOURCE_CONTEXT_ONLY: identity comes only from experimental context (an
# operator's prior declaration, e.g. PHYSICAL_ISOLATION_DECLARED) or from no
# identity source at all -- never presented as a strong RFFI label.
# CRC_VALID_PACKET: decoded successfully, no identity source of either kind.
# TARGET_ASSOCIATED_PACKET: the frozen native<->SDR association criterion
# actually passed for this specific burst (see _burst_class) -- the only
# class allowed to carry a strong-association claim.
BurstClass = Literal["SOURCE_CONTEXT_ONLY", "CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET"]

# Where the identity attached to a burst/example actually came from --
# always present even when NONE, so "no identity" is never confused with
# "identity present but undocumented".
SourceIdentityOrigin = Literal["ASSOCIATION_STRONG", "OPERATOR_CONTEXT_DECLARED", "NONE"]

WindowStatus = Literal["INACTIVE", "ACTIVE_INSUFFICIENT_BURSTS", "ACTIVE_ELIGIBLE"]

DeviationClassification = Literal["CANDIDATE_EXCLUSION", "CAPTURE_EXCLUSION", "PROTOCOL_DEVIATION"]


class ScientificCaptureRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    paper_run_id: str
    protocol_id: str
    campaign_id: str
    capture_id: str

    physical_unit_id: str | None = None
    device_model: str | None = None
    firmware_hash: str | None = None
    configuration_hash: str | None = None
    source_population: str | None = None

    channel: int | None = None
    center_frequency_hz: int | None = None
    sample_rate_hz: int | None = None
    bandwidth_hz: int | None = None
    sample_format: str | None = None
    gain_db: float | None = None
    antenna: str | None = None
    receiver_id: str | None = None
    receiver_epoch: str | None = None
    # receiver_session_id is the EFFECTIVE, runtime-derived id (declared
    # label folded with the real receiver_epoch); receiver_session_id_declared
    # is the raw schedule/operator attestation alone -- see ble_rffi_studio's
    # CaptureRecord docstring on these two fields.
    receiver_session_id: str | None = None
    receiver_session_id_declared: str | None = None
    host_id: str | None = None

    day_id: str | None = None
    campaign_period: str | None = None
    session_id: str | None = None
    capture_order: int | None = None
    pre_or_post: str | None = None
    intervention_arm: str | None = None
    time_since_power_on_s: float | None = None
    time_since_intervention_s: float | None = None
    packet_condition: str | None = None

    ambient_temperature_c: float | None = None
    battery_id: str | None = None
    battery_voltage_pre_v: float | None = None
    battery_voltage_post_v: float | None = None
    operator_id: str | None = None
    planned_capture_id: str | None = None

    capture_start_utc: str | None = None
    duration_s: float | None = None
    window_duration_s: float | None = None
    expected_windows_per_capture: int | None = None
    expected_samples: int | None = None
    observed_samples: int | None = None
    overflow_count: int | None = None
    discontinuity_count: int | None = None
    short_read_count: int | None = None
    writer_backlog_count: int | None = None

    clipping_fraction: float | None = None
    near_zero_fraction: float | None = None
    noise_power_dbfs: float | None = None
    signal_power_dbfs: float | None = None
    snr_db: float | None = None
    occupied_bandwidth_hz: float | None = None
    frequency_offset_hz: float | None = None
    capture_quality: str | None = None

    label_status: str | None = None
    review_status: str | None = None
    experimental_role: str | None = None
    split: str | None = None

    source_iq_resolved_path: str | None = None
    source_iq_size_bytes: int | None = None
    source_iq_sha256: str | None = None
    metadata_path: str | None = None
    metadata_sha256: str | None = None

    # Eligibility (capture-level) vs. diagnostics, kept structurally
    # separate -- a capture can carry diagnostic_flags while still being
    # capture_eligible=True; blocking_reason_codes is the only thing that
    # can make capture_eligible False.
    capture_eligible: bool | None = None
    blocking_reason_codes: list[str] = []
    diagnostic_flags: list[str] = []
    source_manifest_ids: list[str] = []
    not_documented_fields: list[str] = []


class ScientificBurstRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    burst_id: str
    capture_id: str
    burst_class: BurstClass
    source_identity_origin: SourceIdentityOrigin

    sample_start: int
    sample_end: int
    burst_start_utc_estimate: str | None = None
    decision_window_id: str
    candidate_group_id: str | None = None
    detector_version: str | None = None

    synchronization_status: str | None = None
    synchronization_score: float | None = None
    symbol_phase: float | None = None
    frequency_offset_hz: float | None = None
    frequency_fit_quality: float | None = None

    crc_status: str | None = None
    decoded_pdu_type: str | None = None
    decoded_adva: str | None = None
    decoded_payload_hash: str | None = None

    native_event_id: str | None = None
    association_status: str | None = None
    association_time_residual_ms: float | None = None
    association_cost: float | None = None
    association_policy_hash: str | None = None
    # The exact rule (file:function, criterion) that produced
    # source_identity_origin for this burst -- never just a bare field name.
    label_authority: str | None = None

    competing_energy: float | None = None
    clipping_overlap: float | None = None
    discontinuity_overlap: float | None = None
    edge_margin_samples: int | None = None
    burst_snr_db: float | None = None
    burst_quality: str | None = None

    # Eligibility tiers, kept structurally separate from diagnostics.
    # packet_eligible: CRC-valid and processed -- usable at all.
    # label_eligible: a real identity source passed the frozen criterion
    # (source_identity_origin != NONE and, for TARGET_ASSOCIATED_PACKET,
    # the full association criterion in _burst_class).
    # training_eligible: packet_eligible AND label_eligible AND the parent
    # capture's own capture_eligible.
    packet_eligible: bool | None = None
    label_eligible: bool | None = None
    training_eligible: bool | None = None
    blocking_reason_codes: list[str] = []
    diagnostic_flags: list[str] = []
    source_artifact_ids: list[str] = []
    not_documented_fields: list[str] = []


class ScientificDecisionWindowRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    decision_window_id: str
    capture_id: str
    window_index: int
    window_duration_s: float

    window_start_sample: int
    window_end_sample: int
    window_start_utc: str | None = None
    window_end_utc: str | None = None

    window_status: WindowStatus
    candidate_burst_ids: list[str] = []
    crc_valid_burst_ids: list[str] = []
    target_associated_burst_ids: list[str] = []
    eligible_burst_ids: list[str] = []
    candidate_count: int
    crc_valid_count: int
    target_associated_count: int
    eligible_count: int
    selection_policy_hash: str | None = None
    minimum_eligible_bursts: int

    ineligibility_reason_codes: list[str] = []
    not_documented_fields: list[str] = []


class ScientificCampaignDeviationRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    deviation_id: str
    paper_run_id: str
    campaign_id: str
    classification: DeviationClassification

    affected_object_type: str
    affected_object_id: str
    day_id: str | None = None
    session_id: str | None = None

    deviation_type: str
    description: str
    detected_stage: str
    detected_before_outcome_access: bool
    severity: str
    blocking: bool
    protocol_rule: str | None = None

    observed_value: str | None = None
    expected_value: str | None = None
    action: str
    scientific_impact: str

    source_artifact_ids: list[str] = []

    # Populated only for PROTOCOL_DEVIATION rows produced from a
    # PaperCampaignRunner pre-capture rejection (see records/
    # campaign_deviations.py::build_runner_rejection_deviations) -- the
    # exact link the runner's own rejection log already carries: which
    # protocol/planned capture/operator/moment this refusal happened at.
    protocol_id: str | None = None
    planned_capture_id: str | None = None
    operator_id: str | None = None
    detected_at: str | None = None


class RecordBuildResult(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION
    paper_run_id: str
    generated_at: str
    capture_record_count: int
    burst_record_count: int
    decision_window_record_count: int
    campaign_deviation_count: int
    captures_without_replay: list[str] = []
