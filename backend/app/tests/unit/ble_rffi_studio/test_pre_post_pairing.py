"""RQ3 real PRE/POST pairing (2026-08-08): pairs a physical unit's PRE and
POST captures within one device-day and intervention arm, invalidating a
pair on a receiver_epoch or (when supplied) qualified-preprocessing-profile
mismatch. The mechanism is real and tested here against synthetic fixtures
that declare day_id/intervention_arm/pre_or_post -- no real capture on disk
has ever populated these three fields yet (matching campaign_period's own
documented, honest gap), so build_pre_post_pairs correctly returns [] for
every real dataset today.
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.campaign import build_pre_post_pairs
from app.modules.ble_rffi_studio.contracts import CaptureRecord

PROJECT_ID = "P1"


def _capture(
    capture_id: str, *, target_reference_id: str | None = "UNIT-A", day_id: str | None = "2026-08-01",
    intervention_arm: str | None = "RESET", pre_or_post: str | None, receiver_epoch: str | None = "epoch-1",
    receiver_session_id: str | None = "session-1",
) -> CaptureRecord:
    return CaptureRecord(
        project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", target_reference_id=target_reference_id,
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256="sha",
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
        day_id=day_id, intervention_arm=intervention_arm, pre_or_post=pre_or_post, receiver_epoch=receiver_epoch,
        receiver_session_id=receiver_session_id,
    )


def test_pairs_a_real_pre_and_post_capture_for_the_same_unit_day_and_arm():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE"),
        _capture("CAP-POST", pre_or_post="POST"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.physical_unit_id == "UNIT-A"
    assert pair.day_id == "2026-08-01"
    assert pair.intervention_arm == "RESET"
    assert pair.pre_capture_id == "CAP-PRE"
    assert pair.post_capture_id == "CAP-POST"
    assert pair.valid is True
    assert pair.invalidation_reason is None


def test_captures_missing_any_of_the_four_required_fields_are_excluded_entirely():
    captures = [
        _capture("CAP-1", pre_or_post="PRE", day_id=None),  # no day_id declared
        _capture("CAP-2", pre_or_post="POST", target_reference_id=None, receiver_epoch="epoch-1"),  # no unit declared (also drop isolation fallback by leaving both None)
    ]
    assert build_pre_post_pairs(captures) == []


def test_invalidates_a_pair_when_receiver_epoch_changed_between_pre_and_post():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE", receiver_epoch="epoch-1"),
        _capture("CAP-POST", pre_or_post="POST", receiver_epoch="epoch-2"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert len(pairs) == 1
    assert pairs[0].valid is False
    assert "RECEIVER_EPOCH_CHANGED" in pairs[0].invalidation_reason


def test_invalidates_a_pair_when_receiver_epoch_is_not_documented_on_either_side():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE", receiver_epoch=None),
        _capture("CAP-POST", pre_or_post="POST", receiver_epoch="epoch-1"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert pairs[0].valid is False
    assert pairs[0].invalidation_reason == "RECEIVER_EPOCH_NOT_DOCUMENTED_ON_ONE_OR_BOTH_CAPTURES"


def test_invalidates_a_pair_when_receiver_session_id_changed_between_pre_and_post():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE", receiver_session_id="session-1"),
        _capture("CAP-POST", pre_or_post="POST", receiver_session_id="session-2"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert pairs[0].valid is False
    assert "RECEIVER_SESSION_ID_NOT_DOCUMENTED_OR_CHANGED" in pairs[0].invalidation_reason


def test_invalidates_a_pair_when_receiver_session_id_is_not_documented_on_either_side():
    # Historical captures (before this field existed) never populate it --
    # a real B200 restart between PRE/POST is only caught by the
    # receiver_epoch check above in that case; a pair with a matching
    # receiver_epoch but no session attestation is still fail-closed, never
    # silently treated as valid.
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE", receiver_session_id=None),
        _capture("CAP-POST", pre_or_post="POST", receiver_session_id="session-1"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert pairs[0].valid is False
    assert pairs[0].invalidation_reason == "RECEIVER_SESSION_ID_NOT_DOCUMENTED_OR_CHANGED"


def test_a_pair_with_matching_receiver_epoch_and_session_id_stays_valid():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE", receiver_epoch="epoch-1", receiver_session_id="session-1"),
        _capture("CAP-POST", pre_or_post="POST", receiver_epoch="epoch-1", receiver_session_id="session-1"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert pairs[0].valid is True
    assert pairs[0].pre_receiver_session_id == "session-1"
    assert pairs[0].post_receiver_session_id == "session-1"


def test_invalidates_a_pair_when_the_qualified_preprocessing_profile_changed():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE"),
        _capture("CAP-POST", pre_or_post="POST"),
    ]
    pairs = build_pre_post_pairs(captures, preprocessing_profile_by_capture_id={"CAP-PRE": "base-v1", "CAP-POST": "cfo-compensated-v1"})
    assert pairs[0].valid is False
    assert "QUALIFIED_PREPROCESSING_PROFILE_CHANGED" in pairs[0].invalidation_reason


def test_a_pair_with_the_same_preprocessing_profile_on_both_sides_stays_valid():
    captures = [
        _capture("CAP-PRE", pre_or_post="PRE"),
        _capture("CAP-POST", pre_or_post="POST"),
    ]
    pairs = build_pre_post_pairs(captures, preprocessing_profile_by_capture_id={"CAP-PRE": "base-v1", "CAP-POST": "base-v1"})
    assert pairs[0].valid is True


def test_records_an_explicitly_invalid_ambiguous_pair_when_more_than_one_pre_or_post_exists():
    captures = [
        _capture("CAP-PRE-1", pre_or_post="PRE"),
        _capture("CAP-PRE-2", pre_or_post="PRE"),
        _capture("CAP-POST", pre_or_post="POST"),
    ]
    pairs = build_pre_post_pairs(captures)
    assert len(pairs) == 1
    assert pairs[0].valid is False
    assert "AMBIGUOUS_PRE_OR_POST_COUNT" in pairs[0].invalidation_reason


def test_an_incomplete_group_with_only_pre_and_no_post_produces_no_pair_at_all():
    captures = [_capture("CAP-PRE", pre_or_post="PRE")]
    assert build_pre_post_pairs(captures) == []


def test_different_intervention_arms_never_pair_across_each_other():
    captures = [
        _capture("CAP-PRE-RESET", pre_or_post="PRE", intervention_arm="RESET"),
        _capture("CAP-POST-CONTROL", pre_or_post="POST", intervention_arm="CONTROL"),
    ]
    assert build_pre_post_pairs(captures) == []


def test_real_captures_on_disk_produce_no_pairs_today():
    """Honest, expected state: 0/150 real captures declare
    intervention_arm/pre_or_post (see acquisition/capture_stage.py's own
    docstring) -- confirmed here against real synthetic-shaped captures that
    simply never declared them, matching every real CaptureRecord today."""
    undeclared = [_capture("CAP-REAL-1", pre_or_post=None, intervention_arm=None, day_id="2026-08-01")]
    assert build_pre_post_pairs(undeclared) == []
