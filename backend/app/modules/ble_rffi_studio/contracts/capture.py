from __future__ import annotations

from typing import Literal

from .common import StudioContract

CAPTURE_SCHEMA_VERSION = "ble-rffi-studio-capture-v1"

AcquisitionQuality = Literal["PASSED", "FAILED", "INCOMPLETE"]
ReplayStatus = Literal["NOT_STARTED", "PARTIAL", "FULLY_PROCESSED", "COMPLETED_WITH_FAILED_SEGMENTS"]
# Required, never defaulted: every capture must say plainly whether its IQ
# came off a real USRP B200 or out of the synthetic demo generator. This is
# the field the whole SYNTHETIC_TEST_ONLY / operational-use gate is built on.
DataOrigin = Literal["REAL_B200", "SYNTHETIC_TEST_ONLY"]

# What the operator declared they were doing when they launched this
# session -- the Guided UI's very first question ("Que quieres capturar?").
# None only for captures that predate this field (legacy/manually-built).
#
# Four genuinely different experimental intents, never collapsed into one
# generic "background" bucket (that collapse was itself a real bug: a
# BACKGROUND_TARGET_OFF capture's whole point -- the target's absence is the
# EXPECTED, valid result -- was previously indistinguishable from a
# BACKGROUND_GENERAL capture that never had a specific unit to check against,
# and from UNKNOWN_DEVICE_COLLECTION, which is about capturing OTHER
# transmitters entirely, not the registered target at all):
#   TARGET_DEVICE_ON            -- the selected physical unit is powered on;
#                                   this capture is trying for positive
#                                   examples of it.
#   BACKGROUND_TARGET_OFF       -- the target unit is declared off/removed;
#                                   this capture is trying for negative
#                                   examples of the environment WITHOUT it.
#   BACKGROUND_GENERAL          -- environment recorded with no specific unit
#                                   in question at all (no target to be
#                                   absent or present).
#   UNKNOWN_DEVICE_COLLECTION   -- capturing whatever unregistered transmitters
#                                   happen to be nearby, for
#                                   UNKNOWN_DEVICE_REJECTION training only --
#                                   never treated as background/negative
#                                   evidence for TARGET_VS_BACKGROUND.
CapturePurpose = Literal["TARGET_DEVICE_ON", "BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL", "UNKNOWN_DEVICE_COLLECTION"]
TargetState = Literal["POWERED_ON", "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"]
DatasetRole = Literal["POSITIVE_CANDIDATE", "NEGATIVE_CANDIDATE", "UNKNOWN_CANDIDATE", "CONTROL_ONLY"]

# The exact experimental flavor behind a BACKGROUND_* capture_purpose --
# preserved as its own field (not just inferred from capture_purpose) so a
# consumer that only cares "is this real negative evidence, and of what kind"
# never has to keep its own copy of the capture_purpose->background mapping.
# None for TARGET_DEVICE_ON/UNKNOWN_DEVICE_COLLECTION.
BackgroundKind = Literal["TARGET_DECLARED_OFF_OR_REMOVED", "GENERAL_AMBIENT"]

# Whether the declared target unit was actually detected in this capture's
# OWN evidence, computed once Evidence Stage has run (None beforehand, and
# always NOT_APPLICABLE for BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION,
# which have no specific target to detect). This is what tells a
# BACKGROUND_TARGET_OFF capture's expected "the target is absent" apart from
# a TARGET_DEVICE_ON capture's problem "the target should have appeared but
# didn't" -- the same raw fact (no eligible positive match) means opposite
# things depending on capture_purpose, and must never be treated as one
# generic "no examples" case.
TargetPresenceStatus = Literal["DETECTED", "NOT_DETECTED", "INCONCLUSIVE", "NOT_APPLICABLE"]

# What was actually transmitted for this capture -- ORIGINAL (unmodified,
# real device traffic) or CONTROLLED_VARIANT (a deliberately modified packet
# content used for RQ4's packet-content-dependence check). Deliberately a
# DIFFERENT concept from packet_content/field_mapping.py's per-burst
# AnalyticalRegion (FULL_BURST/ADVA_EXCLUDED/PRE_PDU): packet_condition
# describes what was physically sent; AnalyticalRegion describes which
# derived sample region of an already-captured burst is analyzed. Renamed
# from the old, unconstrained, never-populated `packet_variant` free-text
# field (2026-08-09) precisely because its name collided with the
# AnalyticalRegion type alias despite meaning something different.
PacketCondition = Literal["ORIGINAL", "CONTROLLED_VARIANT"]


class CaptureRecord(StudioContract):
    """Describes one B200 IQ acquisition completely enough to reproduce and
    later interpret it -- sample format, count, and receiver configuration
    are not optional extras, they are what makes the IQ file meaningful."""

    schema_version: Literal["ble-rffi-studio-capture-v1"] = CAPTURE_SCHEMA_VERSION

    project_id: str
    campaign_id: str
    capture_id: str
    session_id: str
    execution_id: str
    data_origin: DataOrigin

    physical_unit_id: str | None = None  # null until evidence resolves an AddressBinding

    # Set only when the operator explicitly confirms, at capture time, that
    # this physical unit was the sole nearby transmitter for the whole
    # session -- a real, deliberate declaration, not inferred. Exists
    # because many real BLE devices rotate a resolvable/random advertising
    # address at the radio layer that never matches the "resolved identity"
    # a native OS BLE stack reports, making address-based AddressBinding
    # matching structurally unable to label them (observed directly: 0/4
    # real capture sessions produced an address match, including one where
    # the target was independently confirmed broadcasting seconds earlier).
    # Evidence Stage treats this as WEAKER ground truth than an
    # address+Windows-corroborated STRONG match -- it depends entirely on
    # the physical setup being correct, with no independent cross-check --
    # so it is always recorded and surfaced as PHYSICAL_ISOLATION_DECLARED,
    # never silently merged into address-based association_status values.
    isolation_declared_physical_unit_id: str | None = None

    # "Candidate" only: what the OPERATOR declared this session was for, at
    # launch time, before any evidence exists. A TARGET_DEVICE capture is not
    # yet a confirmed positive -- that still requires Evidence Stage to find
    # eligible examples; a BACKGROUND_ENVIRONMENT capture's whole point is
    # that its target_state is NEVER inferred from the absence of a signal,
    # only from this declaration (see EvidenceStage: a BACKGROUND_ENVIRONMENT
    # capture's examples are never linked as a positive for target_reference_id,
    # even if an address happens to match -- that is a real, honestly
    # surfaced contradiction, not evidence to silently trust).
    capture_purpose: CapturePurpose | None = None
    target_state: TargetState | None = None
    # Set only when capture_purpose is one of the BACKGROUND_* values --
    # preserves the exact experimental flavor (see BackgroundKind above)
    # independently of capture_purpose itself.
    background_kind: BackgroundKind | None = None
    # Documentary only: which physical unit this capture's declared purpose
    # is about -- the unit selected for a TARGET_DEVICE_ON capture, or the
    # unit the operator says was off/removed for a BACKGROUND_TARGET_OFF
    # capture. Never treated as ground truth for labeling on its own -- see
    # the EvidenceStage note above (a BACKGROUND_TARGET_OFF capture's
    # examples are never linked as positive for this unit, even on an
    # address match). Always None for BACKGROUND_GENERAL/
    # UNKNOWN_DEVICE_COLLECTION, which have no specific unit in question.
    target_reference_id: str | None = None
    dataset_role: DatasetRole | None = None
    # Computed once (and only once) Evidence Stage has actually run for this
    # capture -- never set at capture-declaration time, since it describes
    # what the evidence showed, not what the operator intended. None until
    # then. See TargetPresenceStatus above for what each value means per
    # capture_purpose.
    target_presence_status: TargetPresenceStatus | None = None

    receiver_device_id: str
    sdr_model: str
    sdr_serial: str | None = None
    rx_channel: str
    antenna_port: str

    sample_rate_sps: int
    sample_dtype: str
    byte_order: str
    sample_count: int
    channel_count: int

    center_frequency_hz: int
    frontend_bandwidth_hz: int
    effective_bandwidth_hz: int
    gain_db: float
    gain_mode: str
    clock_source: str | None = None
    time_source: str | None = None

    capture_duration_s: float
    capture_tool: str
    capture_tool_version: str | None = None
    software_commit: str | None = None

    iq_path: str
    iq_size_bytes: int
    iq_sha256: str

    acquisition_quality: AcquisitionQuality
    discontinuities: int = 0
    replay_status: ReplayStatus = "NOT_STARTED"
    created_at: str

    # Paper-campaign metadata (added for BLE Scientific Results Studio's
    # real experimental design -- day/intervention/content-variant/receiver-
    # epoch/environmental tracking). All optional, default None: every
    # capture recorded before this field set existed remains valid and
    # simply has no value here (never a silent default other than None).
    # Populated by ble_sdr_capture_worker.py from request.json when a
    # caller (e.g. the paper campaign runner) declares them before capture;
    # never inferred or reconstructed after the fact.
    day_id: str | None = None
    # Point-2 correction (2026-08-08): which real timestamp field day_id was
    # actually derived from, so provenance is auditable rather than implicit.
    # "B200_RF_STARTED_AT" is the real RF-acquisition start
    # (capture_manifest.json's b200_rf_started_at); "CREATED_AT_FALLBACK" is
    # only used when that field is missing (falls back to created_at_utc,
    # the acquisition JOB's own start time, not RF sampling itself).
    day_id_source: str | None = None
    campaign_period: str | None = None
    pre_or_post: str | None = None
    intervention_arm: str | None = None
    packet_condition: PacketCondition | None = None
    # Point-1 correction (2026-08-08): receiver_epoch used to be a bare
    # identity hash (WHICH physical B200), conflating identity with
    # "qualified acquisition epoch" (identity + acquisition profile +
    # session boundary). Now split into three separate, auditable fields:
    #   receiver_identity_id  -- WHICH physical B200 (sdr_model + real
    #                            hardware serial ONLY -- never the legacy
    #                            device_id field, which real data showed
    #                            inconsistently holds either a normalized/
    #                            hashed id or the raw serial for the SAME
    #                            physical unit).
    #   qualified_acquisition_profile_hash -- hash of every acquisition-
    #                            chain parameter that can plausibly change
    #                            what the receiver measures (sample rate,
    #                            bandwidth, gain/mode, antenna/rx channel,
    #                            clock/time source, capture tool version).
    #   receiver_epoch         -- identity + a sequential session index,
    #                            assigned by acquisition/receiver_epoch_
    #                            assignment.py over ALL captures of one
    #                            identity ordered by real acquisition time:
    #                            a new epoch starts at the first capture of
    #                            an identity, whenever the qualified profile
    #                            hash changes, or whenever the gap since the
    #                            previous capture of the same identity
    #                            exceeds RECEIVER_SESSION_GAP_S (a
    #                            documented proxy for reinitialization/
    #                            reconnection -- no real boot/session id is
    #                            recorded anywhere upstream). A manifest-
    #                            declared receiver_epoch (operator-confirmed,
    #                            e.g. after a documented recalibration)
    #                            always overrides the auto-assignment.
    receiver_identity_id: str | None = None
    qualified_acquisition_profile_hash: str | None = None
    receiver_epoch: str | None = None
    receiver_epoch_boundary_reason: str | None = None
    # Point-1 correction (2026-08-10): receiver_epoch's >1h session-gap
    # boundary is a documented PROXY for reinitialization -- no subsystem in
    # this codebase observes a real USRP B200 boot/reconnect event (every
    # real capture opens and closes its own SoapySDR device handle in a
    # fresh subprocess; there is no persistent-connection signal to key off,
    # confirmed by direct inspection of ble_sdr_capture_worker.py/
    # campaign_orchestrator.py/sdr_device_arbiter.py). Because of that, a
    # bare operator/schedule attestation is NOT trustworthy on its own -- the
    # schedule could declare "same session" across a real reconnect it never
    # observed. Split into two fields so the runtime path is what actually
    # governs pairing, never the schedule alone:
    #   receiver_session_id_declared -- the raw operator/schedule attestation
    #     (PaperCampaignRunner.freeze_schedule's generated or operator-
    #     supplied id), copied verbatim from the manifest. Intent, not proof.
    #   receiver_session_id -- the EFFECTIVE id RQ3 pairing actually checks,
    #     computed by StudioRepository AFTER the real, sequential
    #     receiver_epoch assignment runs (acquisition/receiver_epoch_
    #     assignment.py::derive_effective_receiver_session_id), by folding
    #     the declared label together with the real receiver_epoch. If a
    #     genuine reconnect/profile change/session-gap boundary is detected
    #     between two captures that both declare the SAME label, their real
    #     receiver_epoch differs, so their effective receiver_session_id
    #     differs too -- the schedule cannot mask a real detected boundary.
    #     None whenever receiver_session_id_declared is None (no schedule
    #     attestation at all) -- never fabricated for historical captures.
    receiver_session_id_declared: str | None = None
    receiver_session_id: str | None = None
    host_id: str | None = None
    firmware_hash: str | None = None
    configuration_hash: str | None = None
    time_since_power_on_s: float | None = None
    time_since_intervention_s: float | None = None
    capture_order: int | None = None
    review_status: str | None = None
    ambient_temperature_c: float | None = None
    battery_id: str | None = None
    battery_voltage_pre_v: float | None = None
    battery_voltage_post_v: float | None = None
    operator_id: str | None = None
    planned_capture_id: str | None = None
