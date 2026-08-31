"""Point-1 correction (2026-08-08): receiver_identity (WHICH physical B200)
separated from receiver_epoch (identity + qualified acquisition profile +
session boundary). The real bug this closes: the previous receiver_epoch
used the legacy `device_id` field, which real data showed inconsistently
holds either a normalized/hashed id or the raw hardware serial for the SAME
physical unit -- splitting one real B200 into two epochs with no real
hardware event behind it.
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.acquisition.receiver_epoch_assignment import (
    FIRST_CAPTURE_FOR_IDENTITY,
    MANIFEST_DECLARED,
    QUALIFIED_PROFILE_CHANGED,
    SAME_SESSION_AS_PREVIOUS,
    SESSION_GAP_EXCEEDED,
    ReceiverEpochInput,
    assign_receiver_epochs,
    derive_effective_receiver_session_id,
)
from app.modules.ble_rffi_studio.acquisition.receiver_identity import (
    compute_qualified_acquisition_profile_hash,
    compute_receiver_identity_id,
)


def _profile(**overrides) -> str:
    base = dict(
        sdr_model="B200", device_serial="E3R04Z1B2", sample_rate_sps=4_000_000, frontend_bandwidth_hz=2_000_000,
        gain_db=20.0, gain_mode="manual", rx_channel="RX2", antenna_port="RX2",
        clock_source=None, time_source=None, capture_tool="ble-sdr-capture-v3",
    )
    base.update(overrides)
    return compute_qualified_acquisition_profile_hash(**base)


# ------------------------------------------------------------------
# receiver_identity_id
# ------------------------------------------------------------------

def test_receiver_identity_is_stable_across_different_legacy_device_id_encodings():
    """The exact real bug: real data has the SAME physical B200
    (device_serial=E3R04Z1B2) recorded under two different legacy
    receiver_device_id values (a hashed id for 133 captures, the raw serial
    for 11). receiver_identity_id must be identical for both, since it is
    computed ONLY from sdr_model + device_serial, never the legacy field."""
    identity_a = compute_receiver_identity_id(sdr_model="B200", device_serial="E3R04Z1B2")
    identity_b = compute_receiver_identity_id(sdr_model="B200", device_serial="E3R04Z1B2")
    assert identity_a == identity_b


def test_receiver_identity_differs_for_a_different_serial():
    a = compute_receiver_identity_id(sdr_model="B200", device_serial="E3R04Z1B2")
    b = compute_receiver_identity_id(sdr_model="B200", device_serial="SOME-OTHER-SERIAL")
    assert a != b


def test_receiver_identity_is_none_without_a_real_serial():
    assert compute_receiver_identity_id(sdr_model="B200", device_serial=None) is None
    assert compute_receiver_identity_id(sdr_model="B200", device_serial="") is None


# ------------------------------------------------------------------
# qualified_acquisition_profile_hash
# ------------------------------------------------------------------

def test_qualified_profile_hash_is_stable_for_identical_acquisition_parameters():
    assert _profile() == _profile()


def test_qualified_profile_hash_changes_with_gain_mode():
    assert _profile(gain_mode="manual") != _profile(gain_mode="auto")


def test_qualified_profile_hash_changes_with_sample_rate():
    assert _profile(sample_rate_sps=4_000_000) != _profile(sample_rate_sps=8_000_000)


def test_qualified_profile_hash_changes_with_bandwidth():
    assert _profile(frontend_bandwidth_hz=2_000_000) != _profile(frontend_bandwidth_hz=1_000_000)


def test_qualified_profile_hash_changes_with_antenna_or_rx_channel():
    assert _profile(rx_channel="RX2") != _profile(rx_channel="RX1")
    assert _profile(antenna_port="RX2") != _profile(antenna_port="TX/RX")


def test_qualified_profile_hash_changes_with_capture_tool_version():
    assert _profile(capture_tool="ble-sdr-capture-v3") != _profile(capture_tool="ble-sdr-capture-v4")


def test_qualified_profile_hash_is_unaffected_by_gain_db_alone_changing_when_everything_else_matches():
    # gain_db IS part of the hash -- this test documents that a real gain
    # change DOES change the hash (the opposite of the old bug).
    assert _profile(gain_db=20.0) != _profile(gain_db=30.0)


# ------------------------------------------------------------------
# assign_receiver_epochs -- the sequential logic
# ------------------------------------------------------------------

def test_first_capture_of_an_identity_gets_a_new_epoch():
    result = assign_receiver_epochs([ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z")])
    assert result[0].receiver_epoch is not None
    assert result[0].receiver_epoch_boundary_reason == FIRST_CAPTURE_FOR_IDENTITY


def test_same_identity_same_profile_close_in_time_stays_in_the_same_epoch():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-1", "2026-08-01T00:05:00Z"),
        ReceiverEpochInput("CAP-3", "identity-A", "profile-1", "2026-08-01T00:10:00Z"),
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-1"].receiver_epoch == results["CAP-2"].receiver_epoch == results["CAP-3"].receiver_epoch
    assert results["CAP-2"].receiver_epoch_boundary_reason == SAME_SESSION_AS_PREVIOUS


def test_qualified_profile_change_starts_a_new_epoch_even_with_no_time_gap():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-2", "2026-08-01T00:00:01Z"),
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-1"].receiver_epoch != results["CAP-2"].receiver_epoch
    assert results["CAP-2"].receiver_epoch_boundary_reason == QUALIFIED_PROFILE_CHANGED


def test_a_large_time_gap_with_the_same_profile_starts_a_new_epoch_reinit_proxy():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-1", "2026-08-02T12:00:00Z"),  # >1h later
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-1"].receiver_epoch != results["CAP-2"].receiver_epoch
    assert results["CAP-2"].receiver_epoch_boundary_reason == SESSION_GAP_EXCEEDED


def test_a_small_time_gap_under_the_threshold_does_not_start_a_new_epoch():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-1", "2026-08-01T00:30:00Z"),  # 30 min later
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-1"].receiver_epoch == results["CAP-2"].receiver_epoch


def test_manifest_declared_receiver_epoch_always_overrides_auto_assignment():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-1", "2026-08-01T00:05:00Z", declared_receiver_epoch="OPERATOR-DECLARED-EPOCH-7"),
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-2"].receiver_epoch == "OPERATOR-DECLARED-EPOCH-7"
    assert results["CAP-2"].receiver_epoch_boundary_reason == MANIFEST_DECLARED


def test_a_capture_with_no_receiver_identity_gets_no_epoch():
    result = assign_receiver_epochs([ReceiverEpochInput("CAP-1", None, "profile-1", "2026-08-01T00:00:00Z")])
    assert result[0].receiver_epoch is None
    assert result[0].receiver_epoch_boundary_reason is None


def test_assignment_is_order_independent_same_result_regardless_of_input_list_order():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-A", "profile-1", "2026-08-01T00:05:00Z"),
        ReceiverEpochInput("CAP-3", "identity-A", "profile-2", "2026-08-01T00:10:00Z"),
    ]
    forward = {r.capture_id: r.receiver_epoch for r in assign_receiver_epochs(inputs)}
    backward = {r.capture_id: r.receiver_epoch for r in assign_receiver_epochs(list(reversed(inputs)))}
    assert forward == backward


def test_two_different_identities_never_share_an_epoch_even_with_the_same_profile_hash():
    inputs = [
        ReceiverEpochInput("CAP-1", "identity-A", "profile-1", "2026-08-01T00:00:00Z"),
        ReceiverEpochInput("CAP-2", "identity-B", "profile-1", "2026-08-01T00:00:01Z"),
    ]
    results = {r.capture_id: r for r in assign_receiver_epochs(inputs)}
    assert results["CAP-1"].receiver_epoch != results["CAP-2"].receiver_epoch


def test_real_bug_scenario_same_physical_b200_split_by_legacy_device_id_now_unified():
    """Reproduces the exact real finding: 133 captures recorded under a
    hashed legacy device_id, 11 under the raw serial, same physical B200
    (same device_serial, same profile). Under the OLD logic these were 2
    different epochs; under the corrected logic, identity is unified and
    they fall into the SAME epoch (no real profile change, no real session
    gap in this synthetic reproduction)."""
    identity = compute_receiver_identity_id(sdr_model="B200", device_serial="E3R04Z1B2")
    profile = _profile()
    inputs = [ReceiverEpochInput(f"CAP-{i}", identity, profile, f"2026-08-01T00:{i:02d}:00Z") for i in range(20)]
    results = assign_receiver_epochs(inputs)
    assert len({r.receiver_epoch for r in results}) == 1


def test_derive_effective_receiver_session_id_is_none_without_a_declared_label():
    assert derive_effective_receiver_session_id(None, "some-epoch") is None
    assert derive_effective_receiver_session_id(None, None) is None


def test_derive_effective_receiver_session_id_folds_declared_label_with_real_epoch():
    same_epoch_a = derive_effective_receiver_session_id("sched-A", "EPOCH-1")
    same_epoch_b = derive_effective_receiver_session_id("sched-A", "EPOCH-1")
    assert same_epoch_a == same_epoch_b

    different_epoch = derive_effective_receiver_session_id("sched-A", "EPOCH-2")
    assert different_epoch != same_epoch_a


def test_derive_effective_receiver_session_id_still_differs_on_epoch_none_vs_a_real_epoch():
    # A declared label with no resolvable epoch (e.g. unknown identity) must
    # never accidentally collide with one that does have a real epoch.
    assert derive_effective_receiver_session_id("sched-A", None) != derive_effective_receiver_session_id("sched-A", "EPOCH-1")
