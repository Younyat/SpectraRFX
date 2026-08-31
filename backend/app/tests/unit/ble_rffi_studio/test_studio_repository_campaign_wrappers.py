"""StudioRepository.run_campaign_session/run_replay_and_evidence are thin
routing wrappers over CampaignOrchestrator (already thoroughly tested in
test_campaign_orchestrator.py) -- these tests cover only what the wrapper
itself is responsible for: picking run_capture_only vs. run_session based on
capture_only, and the has_evidence-based idempotency skip in
run_replay_and_evidence. A fake orchestrator stands in so these don't need
the full hybrid/capture-manager fake wiring the orchestrator tests use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
REAL_CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
REAL_SESSION_ROOT = STORAGE_ROOT / "ble_lab" / "sessions"


class FakeOrchestrator:
    def __init__(self) -> None:
        self.run_capture_only_calls: list[dict[str, Any]] = []
        self.run_session_calls: list[dict[str, Any]] = []
        self.run_replay_and_evidence_calls: list[dict[str, Any]] = []

    def run_capture_only(self, *, progress=None, **kwargs: Any) -> dict[str, Any]:
        self.run_capture_only_calls.append(kwargs)
        return {"capture_id": "BLE-IQ-fake", "capture_only": True}

    def run_session(self, *, progress=None, **kwargs: Any) -> dict[str, Any]:
        self.run_session_calls.append(kwargs)
        return {"capture_id": "BLE-IQ-fake", "capture_only": False}

    def run_replay_and_evidence_for_capture(self, *, capture_id: str, project_id: str, ble_channel: int, progress=None) -> dict[str, Any]:
        self.run_replay_and_evidence_calls.append({"capture_id": capture_id, "project_id": project_id, "ble_channel": ble_channel})
        return {"capture_id": capture_id, "replay_run_id": "BLE-RFFI-REPLAY-fake", "evidence_summary": {"eligible_examples": 3}}


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(
        tmp_path / "studio", legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT,
        campaign_orchestrator=FakeOrchestrator(),
    )


def test_run_campaign_session_defaults_to_the_full_pipeline(repository):
    result = repository.run_campaign_session(ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="x", physical_unit_id="U1", project_id="P1", campaign_id="C1", session_index=1)
    assert result["capture_only"] is False
    assert repository.campaign_orchestrator.run_session_calls
    assert not repository.campaign_orchestrator.run_capture_only_calls


def test_run_campaign_session_with_capture_only_skips_replay_and_evidence(repository):
    result = repository.run_campaign_session(capture_only=True, ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="x", physical_unit_id="U1", project_id="P1", campaign_id="C1", session_index=1)
    assert result["capture_only"] is True
    assert repository.campaign_orchestrator.run_capture_only_calls
    assert not repository.campaign_orchestrator.run_session_calls


def test_run_campaign_session_without_an_orchestrator_raises_a_clear_error(tmp_path):
    bare_repository = StudioRepository(tmp_path / "studio", legacy_capture_root=REAL_CAPTURE_ROOT, legacy_session_root=REAL_SESSION_ROOT)
    with pytest.raises(RuntimeError, match="REAL_CAMPAIGN_NOT_AVAILABLE"):
        bare_repository.run_campaign_session(ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="x", physical_unit_id="U1", project_id="P1", campaign_id="C1", session_index=1)


def test_run_replay_and_evidence_runs_for_a_capture_with_no_evidence_yet(repository):
    result = repository.run_replay_and_evidence(capture_id="BLE-IQ-fake", project_id="P1", ble_channel=37)
    assert result["skipped"] is False
    assert result["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert repository.campaign_orchestrator.run_replay_and_evidence_calls


def test_run_replay_and_evidence_is_skipped_when_evidence_already_exists(repository):
    evidence_dir = repository.evidence_dir / "BLE-IQ-fake"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "examples.jsonl").write_text("", encoding="utf-8")

    result = repository.run_replay_and_evidence(capture_id="BLE-IQ-fake", project_id="P1", ble_channel=37)

    assert result == {"skipped": True, "reason": "ALREADY_HAS_EVIDENCE", "capture_id": "BLE-IQ-fake"}
    assert not repository.campaign_orchestrator.run_replay_and_evidence_calls  # never re-decoded


def test_run_replay_and_evidence_force_true_reruns_even_when_evidence_already_exists(repository):
    evidence_dir = repository.evidence_dir / "BLE-IQ-fake"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "examples.jsonl").write_text("", encoding="utf-8")

    result = repository.run_replay_and_evidence(capture_id="BLE-IQ-fake", project_id="P1", ble_channel=37, force=True)

    assert result["skipped"] is False
    assert repository.campaign_orchestrator.run_replay_and_evidence_calls
