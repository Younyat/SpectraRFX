"""CampaignOrchestrator wires together three EXISTING, separately-tested
mechanisms (BleHybridCampaignManager, BleCaptureJobManager's resumable
offline replay, SdrDeviceArbiter) -- these tests use fakes for all three so
the orchestration logic itself (session lifecycle, the offline-replay
resume-until-FULLY_PROCESSED loop, arbiter release-on-error) is covered
without touching real hardware or real decode workers.

The resume loop specifically guards against a real bug found via a live
B200 capture: a single offline-replay invocation can report job
state="completed" while its own exit_status is "PARTIAL" (time budget
exceeded, checkpointed, most of the capture still undecoded) -- treating
that "completed" as "done" would silently build evidence from a small
fraction of the capture.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from app.modules.ble_rffi_studio.campaign.campaign_orchestrator import (
    CampaignOrchestrator,
    CampaignSessionError,
    _MAX_CAPTURE_ATTEMPTS,
    _MAX_REPLAY_RESUMES,
)


class RaceThenSucceedsHybridManager:
    """Models the real, observed HYBRID_CAMPAIGN_ALREADY_RUNNING startup
    race: a just-finished attempt's background thread writes its terminal
    state and clears BleHybridCampaignManager's own `_active` flag as two
    separate steps, not atomically -- start() raises for the first
    `race_hits` calls (as if that cleanup hadn't landed yet), then
    succeeds."""
    def __init__(self, race_hits: int, capture_id: str = "BLE-IQ-fake") -> None:
        self.race_hits = race_hits
        self.capture_id = capture_id
        self.start_calls = 0

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.start_calls += 1
        if self.start_calls <= self.race_hits:
            raise RuntimeError("HYBRID_CAMPAIGN_ALREADY_RUNNING")
        return {"session_id": f"BLE-HYBRID-fake-{self.start_calls:04d}", "state": "completed", "capture_id": self.capture_id, "error": None}

    def get(self, session_id):  # pragma: no cover - not reached when start() is already terminal
        return {"session_id": session_id, "state": "completed", "capture_id": self.capture_id}


class FakeAcquireResult:
    def __init__(self, granted: bool, current_owner: str | None = None, current_operation_id: str | None = None) -> None:
        self.granted = granted
        self.current_owner = current_owner
        self.current_operation_id = current_operation_id


class FakeArbiter:
    def __init__(self, granted: bool = True) -> None:
        self.granted = granted
        self.acquired: list[tuple] = []
        self.released: list[tuple] = []

    def acquire(self, device_id, *, owner, operation_id, lease_seconds):
        self.acquired.append((device_id, owner, operation_id, lease_seconds))
        return FakeAcquireResult(self.granted, current_owner="someone_else", current_operation_id="op-x")

    def release(self, device_id, *, owner, operation_id):
        self.released.append((device_id, owner, operation_id))


class FakeHybridManager:
    def __init__(self, final_state: str = "completed", capture_id: str = "BLE-IQ-fake") -> None:
        self.final_state = final_state
        self.capture_id = capture_id
        self.started_payloads: list[dict[str, Any]] = []

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.started_payloads.append(payload)
        # Terminal immediately -- the orchestrator's polling loop body never
        # needs to run for these tests.
        return {"session_id": "BLE-HYBRID-fake-0001", "state": self.final_state, "capture_id": self.capture_id, "error": "boom" if self.final_state != "completed" else None}

    def get(self, session_id):  # pragma: no cover - not reached when start() is already terminal
        return {"session_id": session_id, "state": self.final_state, "capture_id": self.capture_id}


class FlakyThenSucceedsHybridManager:
    """Fails with the real, observed transient signature
    (error contains "CAPTURE_FAILED") for the first `failures_before_success`
    attempts, then succeeds -- models the real, measured ~46% single-attempt
    RF acquisition overflow rate this environment's B200 sees, which the
    orchestrator must absorb via retry rather than surface as an error."""
    def __init__(self, failures_before_success: int, capture_id: str = "BLE-IQ-fake") -> None:
        self.failures_before_success = failures_before_success
        self.capture_id = capture_id
        self.start_calls = 0

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.start_calls += 1
        session_id = f"BLE-HYBRID-fake-{self.start_calls:04d}"
        if self.start_calls <= self.failures_before_success:
            return {"session_id": session_id, "state": "failed", "capture_id": None, "error": "RuntimeError:CAPTURE_FAILED"}
        return {"session_id": session_id, "state": "completed", "capture_id": self.capture_id, "error": None}

    def get(self, session_id):  # pragma: no cover - not reached when start() is already terminal
        return {"session_id": session_id, "state": "completed", "capture_id": self.capture_id}


class FakeCaptureManager:
    def __init__(self, replay_chunks: list[dict[str, Any]]) -> None:
        # Each entry simulates the terminal job state a start/resume call's
        # first offline_replay_job() poll would observe.
        self.replay_chunks = list(replay_chunks)
        self.resume_calls: list[dict[str, Any] | None] = []

    def resolve_device_id(self, requested_device_id=None):
        return requested_device_id or "sdr-fake"

    def start_offline_replay(self, capture_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.resume_calls.append(payload)
        chunk = self.replay_chunks.pop(0)
        return {"replay_run_id": "BLE-RFFI-REPLAY-fake", **chunk}

    def offline_replay_job(self, capture_id: str, replay_run_id: str) -> dict[str, Any]:  # pragma: no cover - only reached if a chunk starts non-terminal
        raise AssertionError("test chunks should already be terminal on start_offline_replay")


class FakeRepository:
    def __init__(self) -> None:
        self.built_captures: list[dict[str, Any]] = []
        self.evidence_calls: list[dict[str, Any]] = []

    def build_capture(
        self, *, capture_id, project_id, campaign_id, execution_id=None, session_id=None,
        isolation_declared_physical_unit_id=None, capture_purpose=None, target_state=None,
        background_kind=None, target_reference_id=None, dataset_role=None,
    ):
        record = {
            "capture_id": capture_id, "project_id": project_id, "campaign_id": campaign_id, "execution_id": execution_id,
            "session_id": session_id, "isolation_declared_physical_unit_id": isolation_declared_physical_unit_id,
            "capture_purpose": capture_purpose, "target_state": target_state, "background_kind": background_kind,
            "target_reference_id": target_reference_id, "dataset_role": dataset_role,
        }
        self.built_captures.append(record)
        return record

    def get_capture(self, capture_id):
        return next((record for record in self.built_captures if record["capture_id"] == capture_id), None)

    def build_evidence(self, *, capture, project_id, ble_channel, replay_run_id=None, progress=None):
        self.evidence_calls.append({"capture": capture, "project_id": project_id, "ble_channel": ble_channel, "replay_run_id": replay_run_id})
        return {"eligible_examples": 5}


def _orchestrator(hybrid_manager=None, capture_manager=None, arbiter=None, repository=None) -> tuple[CampaignOrchestrator, dict[str, Any]]:
    fakes = {
        "hybrid_manager": hybrid_manager or FakeHybridManager(),
        "capture_manager": capture_manager or FakeCaptureManager([{"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}}]),
        "arbiter": arbiter or FakeArbiter(),
        "repository": repository or FakeRepository(),
    }
    return CampaignOrchestrator(**fakes), fakes


def _run(orchestrator: CampaignOrchestrator, **overrides) -> dict[str, Any]:
    kwargs = dict(
        ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="target on",
        physical_unit_id="UNIT-01", project_id="P1", campaign_id="C1", session_index=1,
    )
    kwargs.update(overrides)
    return orchestrator.run_session(**kwargs)


def test_run_session_succeeds_end_to_end_on_a_single_fully_processed_chunk():
    orchestrator, fakes = _orchestrator()
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert result["session_id"] == "BLE-HYBRID-fake-0001"
    assert result["evidence_summary"] == {"eligible_examples": 5}
    assert fakes["repository"].evidence_calls  # evidence was actually built
    assert fakes["arbiter"].acquired and fakes["arbiter"].released  # always released


def test_run_session_succeeds_when_replay_completes_with_failed_segments():
    """Real-hardware bug fix (2026-08-13): COMPLETED_WITH_FAILED_SEGMENTS is
    a real, documented terminal execution_status -- every segment was
    attempted, some individually failed decode/timeout (normal for real RF,
    e.g. one B200 qualification capture with a few CRC/timeout failures).
    Previously this raised OFFLINE_REPLAY_UNEXPECTED_EXIT_STATUS and evidence
    was never built, blocking every real capture with any failed segment."""
    capture_manager = FakeCaptureManager([{"state": "completed", "result": {"exit_status": "COMPLETED_WITH_FAILED_SEGMENTS"}}])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert fakes["repository"].evidence_calls  # evidence was still built


def test_run_session_resumes_a_partial_replay_until_fully_processed():
    capture_manager = FakeCaptureManager([
        {"state": "completed", "result": {"exit_status": "PARTIAL"}},
        {"state": "completed", "result": {"exit_status": "PARTIAL"}},
        {"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}},
    ])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    # First call starts fresh (no replay_run_id yet); the two resumes must
    # reference the SAME replay_run_id to actually continue from checkpoint.
    assert capture_manager.resume_calls[0].get("replay_run_id") is None
    assert capture_manager.resume_calls[1]["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert capture_manager.resume_calls[2]["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert len(capture_manager.resume_calls) == 3


def test_run_session_gives_up_after_max_resumes_without_building_evidence():
    always_partial = [{"state": "completed", "result": {"exit_status": "PARTIAL"}} for _ in range(_MAX_REPLAY_RESUMES + 1)]
    capture_manager = FakeCaptureManager(always_partial)
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    with pytest.raises(CampaignSessionError, match="OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED"):
        _run(orchestrator)

    assert not fakes["repository"].evidence_calls  # never built evidence from an incomplete decode
    assert fakes["arbiter"].released  # still released the device on failure


def test_run_session_raises_on_offline_replay_failure():
    capture_manager = FakeCaptureManager([{"state": "failed", "error": "decoder crashed"}])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    with pytest.raises(CampaignSessionError, match="OFFLINE_REPLAY_FAILED"):
        _run(orchestrator)
    assert not fakes["repository"].evidence_calls


def test_run_session_raises_on_hybrid_session_failure_and_still_releases_device():
    hybrid_manager = FakeHybridManager(final_state="failed")
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)
    assert fakes["arbiter"].released


def test_run_session_retries_automatically_on_transient_rf_overflow_and_succeeds():
    hybrid_manager = FlakyThenSucceedsHybridManager(failures_before_success=3)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert hybrid_manager.start_calls == 4  # 3 real, measured RF overflows absorbed, 4th succeeded
    assert fakes["arbiter"].acquired  # only acquired ONCE, not once per attempt
    assert len(fakes["arbiter"].acquired) == 1
    assert fakes["arbiter"].released


def test_run_session_gives_up_after_max_capture_attempts_of_transient_rf_overflow():
    hybrid_manager = FlakyThenSucceedsHybridManager(failures_before_success=_MAX_CAPTURE_ATTEMPTS + 5)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)

    assert hybrid_manager.start_calls == _MAX_CAPTURE_ATTEMPTS  # never retries beyond the cap
    assert fakes["arbiter"].released
    assert not fakes["repository"].built_captures  # never fabricated a capture from a failed acquisition


def test_start_hybrid_session_absorbs_the_already_running_startup_race_without_counting_it_as_a_capture_attempt(monkeypatch):
    import app.modules.ble_rffi_studio.campaign.campaign_orchestrator as campaign_orchestrator_module
    monkeypatch.setattr(campaign_orchestrator_module.time, "sleep", lambda seconds: None)

    hybrid_manager = RaceThenSucceedsHybridManager(race_hits=2)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert hybrid_manager.start_calls == 3  # 2 races absorbed, 3rd succeeded
    # The orchestrator's own real-RF-overflow retry budget was never touched
    # -- only ONE B200 arbiter acquisition, since this race is purely a
    # manager-internal startup timing gap, never a genuine RF acquisition attempt.
    assert len(fakes["arbiter"].acquired) == 1
    assert fakes["arbiter"].released


def test_start_hybrid_session_gives_up_once_the_race_persists_past_its_own_deadline(monkeypatch):
    import app.modules.ble_rffi_studio.campaign.campaign_orchestrator as campaign_orchestrator_module
    monkeypatch.setattr(campaign_orchestrator_module.time, "sleep", lambda seconds: None)
    fake_now = [0.0]
    def fake_time():
        fake_now[0] += 1.0  # advances past the 10s deadline after a few calls, without a real wall-clock wait
        return fake_now[0]
    monkeypatch.setattr(campaign_orchestrator_module.time, "time", fake_time)

    hybrid_manager = RaceThenSucceedsHybridManager(race_hits=10_000)  # never actually clears
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_CAMPAIGN_ALREADY_RUNNING"):
        _run(orchestrator)
    assert fakes["arbiter"].released


def test_run_session_does_not_retry_a_non_overflow_hybrid_failure():
    hybrid_manager = FakeHybridManager(final_state="failed")  # error="boom", not CAPTURE_FAILED
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)
    assert len(hybrid_manager.started_payloads) == 1  # not blindly retried -- a different, real problem


def test_run_session_raises_when_device_is_busy_and_never_calls_hybrid_manager():
    arbiter = FakeArbiter(granted=False)
    hybrid_manager = FakeHybridManager()
    orchestrator, fakes = _orchestrator(arbiter=arbiter, hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="B200_BUSY"):
        _run(orchestrator)
    assert not hybrid_manager.started_payloads
    assert not arbiter.released  # never acquired, so nothing to release


def test_every_session_uses_exploratory_target_search_regardless_of_declared_task():
    hybrid_manager = FakeHybridManager()
    orchestrator, _ = _orchestrator(hybrid_manager=hybrid_manager)
    _run(orchestrator)

    payload = hybrid_manager.started_payloads[0]
    assert payload["campaign_intent"] == "exploratory_target_search"
    assert payload["target"] == {"kind": "any"}


def test_isolation_declared_passes_the_physical_unit_id_through_to_build_capture():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id="UNIT-01", isolation_declared=True)

    assert fakes["repository"].built_captures[0]["isolation_declared_physical_unit_id"] == "UNIT-01"


def test_isolation_declared_false_never_sets_isolation_on_the_capture():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id="UNIT-01", isolation_declared=False)

    assert fakes["repository"].built_captures[0]["isolation_declared_physical_unit_id"] is None


def test_isolation_declared_without_a_physical_unit_id_is_rejected():
    # Isolation is only ever declared on a TARGET_DEVICE_ON capture (see
    # test_background_target_off_forces_isolation_off), which already
    # requires physical_unit_id -- so this is really the same guard as
    # test_target_device_on_without_a_physical_unit_id_is_rejected below.
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="TARGET_DEVICE_ON_REQUIRES_A_PHYSICAL_UNIT_ID"):
        _run(orchestrator, physical_unit_id=None, isolation_declared=True)
    assert not fakes["repository"].built_captures  # never even reached the capture stage
    assert not fakes["arbiter"].acquired  # fails fast, before touching the B200 at all


def test_target_device_on_without_a_physical_unit_id_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="TARGET_DEVICE_ON_REQUIRES_A_PHYSICAL_UNIT_ID"):
        _run(orchestrator, physical_unit_id=None, capture_purpose="TARGET_DEVICE_ON")
    assert not fakes["repository"].built_captures
    assert not fakes["arbiter"].acquired


def test_background_target_off_without_operator_confirmation_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="BACKGROUND_TARGET_OFF_REQUIRES_OPERATOR_CONFIRMATION"):
        _run(orchestrator, physical_unit_id=None, capture_purpose="BACKGROUND_TARGET_OFF", operator_confirmed_target_absent=False)
    assert not fakes["repository"].built_captures
    assert not fakes["arbiter"].acquired


def test_background_general_requires_no_physical_unit_id_or_confirmation():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id=None, capture_purpose="BACKGROUND_GENERAL")

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "BACKGROUND_GENERAL"
    assert built["target_state"] is None
    assert built["background_kind"] == "GENERAL_AMBIENT"
    assert built["dataset_role"] == "NEGATIVE_CANDIDATE"
    assert built["target_reference_id"] is None


def test_unknown_device_collection_requires_no_physical_unit_id_or_confirmation():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id=None, capture_purpose="UNKNOWN_DEVICE_COLLECTION")

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "UNKNOWN_DEVICE_COLLECTION"
    assert built["target_state"] is None
    assert built["background_kind"] is None
    assert built["dataset_role"] == "UNKNOWN_CANDIDATE"
    assert built["target_reference_id"] is None


def test_unknown_device_collection_forces_isolation_off_even_if_caller_requests_it():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id="UNIT-01", capture_purpose="UNKNOWN_DEVICE_COLLECTION", isolation_declared=True)

    built = fakes["repository"].built_captures[0]
    assert built["isolation_declared_physical_unit_id"] is None


def test_unknown_capture_purpose_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="UNKNOWN_CAPTURE_PURPOSE"):
        _run(orchestrator, capture_purpose="SOMETHING_ELSE")
    assert not fakes["arbiter"].acquired


def test_target_device_on_capture_records_powered_on_target_state_and_positive_dataset_role():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, capture_purpose="TARGET_DEVICE_ON")

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "TARGET_DEVICE_ON"
    assert built["target_state"] == "POWERED_ON"
    assert built["background_kind"] is None
    assert built["dataset_role"] == "POSITIVE_CANDIDATE"
    assert built["target_reference_id"] == "UNIT-01"


def test_background_target_off_capture_records_declared_absent_target_state_and_negative_dataset_role():
    orchestrator, fakes = _orchestrator()
    result = _run(
        orchestrator, physical_unit_id="UNIT-01", capture_purpose="BACKGROUND_TARGET_OFF",
        operator_confirmed_target_absent=True,
    )

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "BACKGROUND_TARGET_OFF"
    assert built["target_state"] == "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"
    assert built["background_kind"] == "TARGET_DECLARED_OFF_OR_REMOVED"
    assert built["dataset_role"] == "NEGATIVE_CANDIDATE"
    assert built["target_reference_id"] == "UNIT-01"  # documentary only -- never a positive ground truth
    assert result["capture_purpose"] == "BACKGROUND_TARGET_OFF"


def test_background_target_off_capture_allows_no_target_reference_id():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id=None, capture_purpose="BACKGROUND_TARGET_OFF", operator_confirmed_target_absent=True)

    built = fakes["repository"].built_captures[0]
    assert built["target_reference_id"] is None
    assert built["isolation_declared_physical_unit_id"] is None


def test_background_target_off_forces_isolation_off_even_if_caller_requests_it():
    orchestrator, fakes = _orchestrator()
    _run(
        orchestrator, physical_unit_id="UNIT-01", capture_purpose="BACKGROUND_TARGET_OFF",
        operator_confirmed_target_absent=True, isolation_declared=True,
    )

    built = fakes["repository"].built_captures[0]
    assert built["isolation_declared_physical_unit_id"] is None


# ------------------------------------------------------------------
# run_capture_only / run_replay_and_evidence_for_capture -- the
# deliberately separable "fast capture, slow decode later" split.
# ------------------------------------------------------------------

def test_run_capture_only_builds_the_capture_but_never_touches_replay_or_evidence():
    capture_manager = FakeCaptureManager([{"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}}])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    result = orchestrator.run_capture_only(
        ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="target on",
        physical_unit_id="UNIT-01", project_id="P1", campaign_id="C1", session_index=1,
    )

    assert result["capture_id"] == "BLE-IQ-fake"
    assert "replay_run_id" not in result
    assert "evidence_summary" not in result
    assert fakes["repository"].built_captures  # the CaptureRecord IS built
    assert not fakes["repository"].evidence_calls  # but evidence is not
    assert not capture_manager.resume_calls  # offline replay never started
    # The B200 lease is released as soon as the RF acquisition itself is
    # done -- not held through a decode that never even ran here.
    assert fakes["arbiter"].acquired and fakes["arbiter"].released


def test_run_capture_only_still_validates_capture_purpose_and_retries_transient_overflow():
    hybrid_manager = FlakyThenSucceedsHybridManager(failures_before_success=2)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="TARGET_DEVICE_ON_REQUIRES_A_PHYSICAL_UNIT_ID"):
        orchestrator.run_capture_only(
            ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="x",
            physical_unit_id=None, project_id="P1", campaign_id="C1", session_index=1,
        )
    assert not fakes["arbiter"].acquired  # fails fast, before touching the B200

    result = orchestrator.run_capture_only(
        ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="x",
        physical_unit_id="UNIT-01", project_id="P1", campaign_id="C1", session_index=1,
    )
    assert result["capture_id"] == "BLE-IQ-fake"
    assert hybrid_manager.start_calls == 3  # 2 real overflows absorbed, 3rd succeeded


def test_run_replay_and_evidence_for_capture_runs_the_resume_loop_and_builds_evidence():
    capture_manager = FakeCaptureManager([
        {"state": "completed", "result": {"exit_status": "PARTIAL"}},
        {"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}},
    ])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)
    fakes["repository"].built_captures.append({"capture_id": "BLE-IQ-preexisting", "project_id": "P1"})

    result = orchestrator.run_replay_and_evidence_for_capture(capture_id="BLE-IQ-preexisting", project_id="P1", ble_channel=37)

    assert result["capture_id"] == "BLE-IQ-preexisting"
    assert result["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert result["evidence_summary"] == {"eligible_examples": 5}
    assert len(capture_manager.resume_calls) == 2
    # Pure decode work on an already-recorded file -- never touches the B200
    # or its arbiter lease, so a live capture elsewhere is never blocked by
    # this running in the background.
    assert not fakes["arbiter"].acquired


def test_run_replay_and_evidence_for_capture_raises_a_clear_error_when_capture_was_never_built():
    orchestrator, _ = _orchestrator()
    with pytest.raises(CampaignSessionError, match="CAPTURE_NOT_BUILT_YET"):
        orchestrator.run_replay_and_evidence_for_capture(capture_id="BLE-IQ-never-built", project_id="P1", ble_channel=37)


def test_run_session_still_does_capture_and_replay_and_evidence_all_in_one_call():
    """The original all-in-one entry point must keep working identically
    after being refactored to share _acquire_capture/_run_replay_and_evidence
    with run_capture_only/run_replay_and_evidence_for_capture."""
    orchestrator, fakes = _orchestrator()
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert result["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert result["evidence_summary"] == {"eligible_examples": 5}
    assert fakes["repository"].evidence_calls


# ------------------------------------------------------------------
# Operator-requested cancellation (Stop button) -- a real user-reported
# need: a hung/misbehaving hardware action must be abortable without
# leaving the B200 arbiter lease stuck or the underlying session running
# unobserved. See scientific_results_job_manager.py's cancel_job().
# ------------------------------------------------------------------

class HangingThenStoppableHybridManager:
    """Never reaches a terminal state on its own -- models a capture that
    needs an explicit operator stop. stop() flips the session to
    "cancelled" the next time get() is polled, exactly like the real
    BleHybridCampaignManager.stop()/_run() interaction."""
    def __init__(self, capture_id: str = "BLE-IQ-fake") -> None:
        self.capture_id = capture_id
        self.stopped_sessions: list[str] = []
        self._state = "capturing"

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": "BLE-HYBRID-fake-0001", "state": self._state, "capture_id": self.capture_id, "error": None}

    def get(self, session_id):
        return {"session_id": session_id, "state": self._state, "capture_id": self.capture_id}

    def stop(self, session_id: str) -> None:
        self.stopped_sessions.append(session_id)
        self._state = "cancelled"


def test_run_session_never_starts_hardware_when_already_cancelled_before_launch():
    hybrid_manager = FakeHybridManager()
    cancel_event = threading.Event()
    cancel_event.set()
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="CANCELLED_BY_OPERATOR"):
        _run(orchestrator, cancel_event=cancel_event)

    assert not hybrid_manager.started_payloads  # never touched hardware for an already-cancelled request
    assert fakes["arbiter"].released  # lease still cleanly released


def test_run_session_stops_a_real_in_flight_capture_on_operator_cancel(monkeypatch):
    import app.modules.ble_rffi_studio.campaign.campaign_orchestrator as campaign_orchestrator_module
    monkeypatch.setattr(campaign_orchestrator_module.time, "sleep", lambda seconds: None)

    hybrid_manager = HangingThenStoppableHybridManager()
    cancel_event = threading.Event()
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    # Simulate the operator clicking "Detener" once the poll loop is running:
    # the FIRST get() call still sees the pre-cancel state; stop() flips it
    # to terminal only once actually invoked.
    original_get = hybrid_manager.get
    calls = {"n": 0}

    def get_then_cancel(session_id):
        calls["n"] += 1
        if calls["n"] == 1:
            cancel_event.set()
        return original_get(session_id)

    monkeypatch.setattr(hybrid_manager, "get", get_then_cancel)

    with pytest.raises(CampaignSessionError, match="CANCELLED_BY_OPERATOR"):
        _run(orchestrator, cancel_event=cancel_event)

    assert hybrid_manager.stopped_sessions == ["BLE-HYBRID-fake-0001"]  # real session actually stopped, not abandoned
    assert fakes["arbiter"].released  # B200 never left locked after a cancel


class SlowThenStoppableCaptureManager:
    """A replay job that never finishes on its own until cancel_offline_replay
    is called -- models the operator stopping a long decode instead of a
    long RF capture."""
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []
        self._state = "running"

    def resolve_device_id(self, requested_device_id=None):
        return requested_device_id or "sdr-fake"

    def start_offline_replay(self, capture_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"replay_run_id": "BLE-RFFI-REPLAY-fake", "state": self._state}

    def offline_replay_job(self, capture_id: str, replay_run_id: str) -> dict[str, Any]:
        return {"state": self._state}

    def cancel_offline_replay(self, capture_id: str, replay_run_id: str) -> dict[str, Any]:
        self.cancelled.append((capture_id, replay_run_id))
        self._state = "cancelled"
        return {"state": "cancelled"}


def test_run_session_stops_an_in_flight_replay_on_operator_cancel(monkeypatch):
    import app.modules.ble_rffi_studio.campaign.campaign_orchestrator as campaign_orchestrator_module
    monkeypatch.setattr(campaign_orchestrator_module.time, "sleep", lambda seconds: None)

    capture_manager = SlowThenStoppableCaptureManager()
    cancel_event = threading.Event()
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    calls = {"n": 0}
    original_poll = capture_manager.offline_replay_job

    def poll_then_cancel(capture_id, replay_run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            cancel_event.set()
        return original_poll(capture_id, replay_run_id)

    monkeypatch.setattr(capture_manager, "offline_replay_job", poll_then_cancel)

    with pytest.raises(CampaignSessionError, match="CANCELLED_BY_OPERATOR"):
        _run(orchestrator, cancel_event=cancel_event)

    assert capture_manager.cancelled == [("BLE-IQ-fake", "BLE-RFFI-REPLAY-fake")]
    assert fakes["arbiter"].released
    assert len(fakes["arbiter"].acquired) == 1 and fakes["arbiter"].released
