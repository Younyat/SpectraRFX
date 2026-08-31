"""Protocol-freeze close-out, point 1 (2026-08-10): receiver_session_id must
not be a label the schedule can declare unchallenged -- the real, runtime
receiver_epoch assignment (StudioRepository.build_capture ->
_assign_receiver_epoch_if_needed) is the authority. This end-to-end test
reproduces exactly the scenario requested:

    PRE  (receiver_session_id_declared="sched-A") -> real B200
         reconnect/reinitialization (simulated here via a real, detected
         qualified-acquisition-profile change, the same mechanism
         receiver_epoch already uses) -> POST (receiver_session_id_declared
         still "sched-A", same schedule, unaware of the reconnect)

Expected: PRE and POST get DIFFERENT real receiver_epoch values (the
existing, already-tested epoch machinery), therefore DIFFERENT effective
receiver_session_id values despite the identical declared label, and
build_pre_post_pairs() rejects the pair.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.campaign.pre_post_pairing import build_pre_post_pairs

PROJECT_ID = "P1"


def _write_manifest(
    capture_dir: Path, *, capture_id: str, created_at_utc: str, device_serial: str = "E3R04Z1B2", gain_db: float = 20.0,
    receiver_session_id: str = "sched-A", day_id: str = "2026-08-10", pre_or_post: str, intervention_arm: str = "RESET",
) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "capture_id": capture_id, "experimental_metadata": {"session_id": f"S-{capture_id}"},
        "sample_rate_sps": 4_000_000, "sample_format": "cf32_le", "sample_count": 1, "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000, "bytes_per_cpu_sample": 8, "actual_duration_seconds": 1.0, "data_path": "x.sigmf-data",
        "actual_file_size_bytes": 1, "file_size": 1, "data_sha256": f"sha-{capture_id}",
        "created_at_utc": created_at_utc, "b200_rf_started_at": created_at_utc,
        "diagnostic_status": "PASSED", "continuity_status": "PASSED", "hash_status": "VERIFIED", "capture_complete": True,
        "device_serial": device_serial, "hardware": "B200", "antenna": "RX2",
        "gain_configuration": {"gain_db": gain_db, "mode": "manual"},
        "capture_software_revision": "ble-sdr-capture-v3",
        # What the (real) PaperCampaignRunner-driven capture would have
        # written -- the schedule declares the SAME receiver_session_id for
        # both PRE and POST, unaware of any reconnect that may happen
        # between them.
        "receiver_session_id": receiver_session_id, "day_id": day_id, "pre_or_post": pre_or_post, "intervention_arm": intervention_arm,
    }
    (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_same_declared_session_no_real_boundary_keeps_the_same_effective_session_id(repository, tmp_path):
    _write_manifest(repository.legacy_capture_root / "CAP-PRE", capture_id="CAP-PRE", created_at_utc="2026-08-10T00:00:00Z", pre_or_post="PRE")
    _write_manifest(repository.legacy_capture_root / "CAP-POST", capture_id="CAP-POST", created_at_utc="2026-08-10T00:05:00Z", pre_or_post="POST")

    pre = repository.build_capture(capture_id="CAP-PRE", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1", target_reference_id="UNIT-A")
    post = repository.build_capture(capture_id="CAP-POST", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2", target_reference_id="UNIT-A")

    assert pre.receiver_session_id_declared == post.receiver_session_id_declared == "sched-A"
    assert pre.receiver_epoch == post.receiver_epoch  # no real boundary detected (close in time, same profile)
    assert pre.receiver_session_id == post.receiver_session_id  # effective id agrees -- pair should stay valid

    pairs = build_pre_post_pairs([pre, post])
    assert len(pairs) == 1
    assert pairs[0].valid is True


def test_same_declared_session_but_real_reconnect_produces_different_effective_session_id_and_invalidates_the_pair(repository, tmp_path):
    # The schedule declares the SAME receiver_session_id ("sched-A") for
    # both PRE and POST -- it has no way to know a real reconnect happened.
    # The simulated reconnect is a real, detected qualified-acquisition-
    # profile change (gain 20.0 -> 30.0) between the two captures, the exact
    # same signal receiver_epoch already uses and that a genuine B200
    # re-initialization would plausibly produce (a fresh device open can
    # renegotiate gain/streaming parameters). This is the runtime path
    # overriding what the schedule alone declared.
    _write_manifest(repository.legacy_capture_root / "CAP-PRE", capture_id="CAP-PRE", created_at_utc="2026-08-10T00:00:00Z", gain_db=20.0, pre_or_post="PRE")
    _write_manifest(repository.legacy_capture_root / "CAP-POST", capture_id="CAP-POST", created_at_utc="2026-08-10T00:05:00Z", gain_db=30.0, pre_or_post="POST")

    pre = repository.build_capture(capture_id="CAP-PRE", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1", target_reference_id="UNIT-A")
    post = repository.build_capture(capture_id="CAP-POST", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2", target_reference_id="UNIT-A")

    assert pre.receiver_session_id_declared == post.receiver_session_id_declared == "sched-A"
    assert post.receiver_epoch_boundary_reason == "QUALIFIED_PROFILE_CHANGED"
    assert pre.receiver_epoch != post.receiver_epoch  # the real, runtime-detected boundary
    assert pre.receiver_session_id != post.receiver_session_id  # schedule could NOT mask it

    pairs = build_pre_post_pairs([pre, post])
    assert len(pairs) == 1
    assert pairs[0].valid is False
    # pre_post_pairing.py checks receiver_epoch before receiver_session_id,
    # so the more specific RECEIVER_EPOCH_CHANGED reason fires first here --
    # equally correct (both fields independently disagree), and this is the
    # more informative diagnosis of the two since it names the real boundary.
    assert "RECEIVER_EPOCH_CHANGED_BETWEEN_PRE_AND_POST" in pairs[0].invalidation_reason


def test_same_declared_session_and_epoch_but_session_attestation_missing_on_one_side_still_invalidates(repository, tmp_path):
    # Isolates the receiver_session_id-specific check: same real epoch on
    # both sides (no profile change, no gap), but one capture never got a
    # schedule attestation at all (e.g. it wasn't run through the paper
    # campaign runner) -- receiver_epoch alone would pass, but the missing
    # session attestation must still block the pair.
    _write_manifest(repository.legacy_capture_root / "CAP-PRE", capture_id="CAP-PRE", created_at_utc="2026-08-10T00:00:00Z", pre_or_post="PRE")
    capture_dir = repository.legacy_capture_root / "CAP-POST"
    _write_manifest(capture_dir, capture_id="CAP-POST", created_at_utc="2026-08-10T00:05:00Z", pre_or_post="POST")
    manifest_path = capture_dir / "capture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["receiver_session_id"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    pre = repository.build_capture(capture_id="CAP-PRE", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1", target_reference_id="UNIT-A")
    post = repository.build_capture(capture_id="CAP-POST", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2", target_reference_id="UNIT-A")

    assert pre.receiver_epoch == post.receiver_epoch  # no real boundary detected
    assert post.receiver_session_id_declared is None
    assert post.receiver_session_id is None

    pairs = build_pre_post_pairs([pre, post])
    assert pairs[0].valid is False
    assert "RECEIVER_SESSION_ID_NOT_DOCUMENTED_OR_CHANGED" in pairs[0].invalidation_reason


def test_same_declared_session_but_a_long_real_gap_also_invalidates_the_pair(repository, tmp_path):
    # A >1h session-gap boundary is the OTHER real signal receiver_epoch
    # already uses (SESSION_GAP_EXCEEDED) -- same runtime-authority effect.
    _write_manifest(repository.legacy_capture_root / "CAP-PRE", capture_id="CAP-PRE", created_at_utc="2026-08-10T00:00:00Z", pre_or_post="PRE")
    _write_manifest(repository.legacy_capture_root / "CAP-POST", capture_id="CAP-POST", created_at_utc="2026-08-10T03:00:00Z", pre_or_post="POST")

    pre = repository.build_capture(capture_id="CAP-PRE", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1", target_reference_id="UNIT-A")
    post = repository.build_capture(capture_id="CAP-POST", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2", target_reference_id="UNIT-A")

    assert post.receiver_epoch_boundary_reason == "SESSION_GAP_EXCEEDED"
    assert pre.receiver_session_id != post.receiver_session_id

    pairs = build_pre_post_pairs([pre, post])
    assert pairs[0].valid is False
