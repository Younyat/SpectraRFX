"""Study Control Center, Phase 1 (2026-08-11): orchestration-level tests
for run_real_hardware_qualification, using a STUB CampaignOrchestrator (same
pattern as test_guided_validation_hardware_actions.py's _StubOrchestrator)
-- this NEVER touches real hardware. Verifies the real gate-derivation
wiring (CaptureRecord fields -> preflight gates), that a real acquisition
failure is reported honestly (NOT_READY, not a crash), that a deliberate
operator cancellation propagates rather than being swallowed into a fake
result, and the Eq.(6)-(7) smoke-test glue's two real outcomes.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.modules.ble_rffi_studio.contracts import CaptureRecord, ExampleRecord
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.hardware_qualification import (
    HardwareQualificationError,
    _run_eq6_7_smoke_test,
    run_real_hardware_qualification,
)

PROJECT_ID = "P1"


class _StubOrchestrator:
    def __init__(self, session_result: dict | None = None, raise_error: Exception | None = None) -> None:
        self.session_result = session_result
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def run_session(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return self.session_result


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_capture_record(repo, *, capture_id: str, receiver_identity_id: str | None, qualified_acquisition_profile_hash: str | None,
                           discontinuities: int, acquisition_quality: str, iq_sha256: str) -> None:
    capture = CaptureRecord(
        project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256=iq_sha256,
        acquisition_quality=acquisition_quality, discontinuities=discontinuities, replay_status="FULLY_PROCESSED", created_at="2026-08-11T00:00:00Z",
        receiver_identity_id=receiver_identity_id, qualified_acquisition_profile_hash=qualified_acquisition_profile_hash,
    )
    path = repo.ble_root / "captures" / f"{capture_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(capture.model_dump(mode="json")), encoding="utf-8")


def test_raises_without_a_campaign_orchestrator(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(HardwareQualificationError):
        run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=None, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)


def test_a_real_acquisition_failure_is_reported_honestly_never_a_crash(tmp_path):
    repo = _repo(tmp_path)
    orchestrator = _StubOrchestrator(raise_error=RuntimeError("B200_BUSY:held_by=other-op"))
    result = run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=orchestrator, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)
    assert result["capture_id"] is None
    assert "B200_BUSY" in result["acquisition_error"]
    assert result["preflight_report"]["items"]["b200_detected"]["status"] == "NOT_READY"
    assert result["preflight_report"]["overall_status"] == "NOT_READY"


def test_operator_cancellation_propagates_instead_of_being_swallowed(tmp_path):
    repo = _repo(tmp_path)
    orchestrator = _StubOrchestrator(raise_error=RuntimeError("CANCELLED_BY_OPERATOR"))
    with pytest.raises(RuntimeError, match="CANCELLED_BY_OPERATOR"):
        run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=orchestrator, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)


def test_missing_capture_record_after_a_reported_success_raises(tmp_path):
    repo = _repo(tmp_path)
    orchestrator = _StubOrchestrator({"capture_id": "CAP-GHOST", "session_id": "SESSION-1"})
    with pytest.raises(HardwareQualificationError, match="CAPTURE_RECORD_NOT_FOUND_AFTER_REAL_SESSION"):
        run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=orchestrator, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)


def test_happy_path_wires_real_capture_fields_into_the_real_gates(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-QUAL-1"
    _write_capture_record(
        repo, capture_id=capture_id, receiver_identity_id="B200-SERIAL-123", qualified_acquisition_profile_hash="profile-hash-1",
        discontinuities=0, acquisition_quality="PASSED", iq_sha256="real-iq-sha",
    )
    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": "SESSION-1"})

    result = run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=orchestrator, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)

    assert orchestrator.calls[0]["physical_unit_id"] == "UNIT-A"
    assert orchestrator.calls[0]["capture_purpose"] == "TARGET_DEVICE_ON"
    report = result["preflight_report"]
    assert report["items"]["b200_detected"]["status"] == "READY"
    assert report["items"]["receiver_identity"]["status"] == "READY"
    assert report["items"]["qualified_acquisition_profile"]["status"] == "READY"
    assert report["items"]["capture_continuity_and_quality_summary"]["status"] == "READY"
    assert report["items"]["source_iq_digest"]["status"] == "READY"
    # No admitted example exists for this capture -- the Eq(6)-(7) smoke
    # test gate stays honestly NOT_CHECKED, never a fabricated pass.
    assert report["items"]["eq6_7_smoke_test_on_real_iq"]["status"] == "NOT_CHECKED"
    # No calibration campaign has frozen an association policy yet -- real,
    # current, honest NOT_READY, never forced by a single fresh capture.
    assert report["items"]["association_state"]["status"] == "NOT_READY"
    assert report["overall_status"] == "NOT_READY"


def test_discontinuous_capture_produces_a_real_not_ready_continuity_gate(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-QUAL-2"
    _write_capture_record(
        repo, capture_id=capture_id, receiver_identity_id="B200-SERIAL-123", qualified_acquisition_profile_hash="profile-hash-1",
        discontinuities=3, acquisition_quality="PASSED", iq_sha256="real-iq-sha",
    )
    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": "SESSION-1"})
    result = run_real_hardware_qualification(sci_repository=repo, campaign_orchestrator=orchestrator, physical_unit_id="UNIT-A", channel=37, duration_seconds=5.0)
    assert result["preflight_report"]["items"]["capture_continuity_and_quality_summary"]["status"] == "NOT_READY"


# --- Eq.(6)-(7) smoke-test glue, tested directly ---

def _example_record(*, capture_id: str, source_iq_sha256: str) -> ExampleRecord:
    example_id = ExampleRecord.make_example_id(source_iq_sha256, 0, 512, "cand-1", "pkt-1")
    return ExampleRecord(
        example_id=example_id, project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, execution_id="E1", session_id="S1",
        candidate_id="cand-1", packet_id="pkt-1", source_iq_sha256=source_iq_sha256, iq_start_sample=0, iq_end_sample=512,
        physical_unit_id="UNIT-A", association_status="STRONG", quality_status="PASSED", dataset_eligibility="ELIGIBLE",
        channel=37, sample_rate_sps=4_000_000, center_frequency_hz=2_402_000_000, created_at="2026-08-11T00:00:00Z",
    )


def test_eq6_7_smoke_test_is_not_checked_when_no_admitted_example_exists(tmp_path):
    repo = _repo(tmp_path)
    capture = CaptureRecord.model_validate(json.loads((_write_and_return_capture(repo, "CAP-NO-EX"))))
    assert _run_eq6_7_smoke_test(repo, capture) is None


def _write_and_return_capture(repo, capture_id: str) -> str:
    capture = CaptureRecord(
        project_id=PROJECT_ID, campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256="real-iq-sha",
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-11T00:00:00Z",
    )
    path = repo.ble_root / "captures" / f"{capture_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(capture.model_dump(mode="json"))
    path.write_text(payload, encoding="utf-8")
    return payload


def test_eq6_7_smoke_test_applies_the_real_compensation_on_a_real_admitted_example(tmp_path):
    repo = _repo(tmp_path)
    capture_id = "CAP-WITH-EX"
    capture_payload = _write_and_return_capture(repo, capture_id)
    capture = CaptureRecord.model_validate(json.loads(capture_payload))

    example = _example_record(capture_id=capture_id, source_iq_sha256="real-iq-sha")
    (repo.ble_root / "evidence" / capture_id).mkdir(parents=True)
    (repo.ble_root / "evidence" / capture_id / "examples.jsonl").write_text(json.dumps(example.model_dump(mode="json")) + "\n", encoding="utf-8")

    # A real (synthetic-content, real-format) complex64 .cf32 file long
    # enough for the frozen Eq.(6)-(7) reference index set -- TEST-only
    # content, never written to production storage.
    iq_path = repo._resolve_iq_path(capture)
    iq_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    samples = (rng.standard_normal(2000) + 1j * rng.standard_normal(2000)).astype(np.complex64)
    samples.tofile(iq_path)

    assert _run_eq6_7_smoke_test(repo, capture) is True
