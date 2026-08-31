"""Capture Stage against the real, already-completed BLE-IQ-e8edc49b59a0
capture (the same one Fase 1/Fase 2 of the BLE Offline Replay / Packet
Analysis Lab work verified end-to-end). No synthetic fixtures here -- if this
capture's real capture_manifest.json ever changes shape, this test is
supposed to fail loudly rather than keep passing against a mock.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.acquisition.capture_stage import CaptureStage, ExecutionIdRequiredError

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
REAL_CAPTURE_ID = "BLE-IQ-e8edc49b59a0"

pytestmark = pytest.mark.skipif(not (CAPTURE_ROOT / REAL_CAPTURE_ID).is_dir(), reason="real capture fixture not present in this environment")


@pytest.fixture
def stage():
    return CaptureStage(CAPTURE_ROOT)


def test_build_capture_record_from_real_capture(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01")

    assert capture.capture_id == REAL_CAPTURE_ID
    assert capture.session_id == "S001-POS"
    assert capture.execution_id == "BLE-HYBRID-20260724T121557Z-ea66fb"
    assert capture.physical_unit_id is None  # never populated at capture time, only via Evidence Stage
    assert capture.sample_rate_sps == 4_000_000
    assert capture.center_frequency_hz == 2_402_000_000
    assert capture.sample_count == 40_000_000
    assert capture.channel_count == 1
    assert capture.iq_sha256 == "751d880979196d709e9f03bcd30afc79d03be34ca747b383b672551df1473874"
    assert capture.sdr_serial == "E3R04Z1B2"
    assert capture.acquisition_quality == "PASSED"
    assert capture.discontinuities == 0
    assert capture.replay_status == "FULLY_PROCESSED"
    assert capture.software_commit == "6058f3cd73b9310e2cdd8e30e5074834943a5208"
    # day_id: point-2 correction (2026-08-08) -- primary source is the real
    # RF-acquisition start (b200_rf_started_at), not the acquisition job's
    # own start time; this real manifest never declared day_id explicitly.
    assert capture.day_id == "2026-07-24"
    assert capture.day_id_source == "B200_RF_STARTED_AT"
    # receiver_identity_id/qualified_acquisition_profile_hash: point-1
    # correction (2026-08-08) -- pure, per-manifest facts CaptureStage CAN
    # compute alone. receiver_epoch itself requires sequential knowledge of
    # this identity's OTHER captures (see StudioRepository.
    # _assign_receiver_epoch_if_needed) and stays None at this layer for a
    # manifest that never declared it explicitly -- never fabricated here.
    assert capture.receiver_identity_id is not None and capture.receiver_identity_id.startswith("identity-")
    assert capture.qualified_acquisition_profile_hash is not None and capture.qualified_acquisition_profile_hash.startswith("profile-")
    assert capture.receiver_epoch is None
    assert capture.receiver_epoch_boundary_reason is None
    # campaign_period/intervention_arm/packet_condition have no equivalent
    # fallback -- nothing else recorded implies a real intervention/arm, so
    # they correctly stay undeclared for a capture no paper campaign runner
    # ever ran.
    assert capture.campaign_period is None
    assert capture.intervention_arm is None
    assert capture.packet_condition is None


def test_receiver_identity_and_profile_hash_are_stable_across_two_builds_of_the_same_capture(stage):
    first = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="P1", campaign_id="C1")
    second = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="P1", campaign_id="C1")
    assert first.receiver_identity_id == second.receiver_identity_id
    assert first.qualified_acquisition_profile_hash == second.qualified_acquisition_profile_hash


def test_manifest_declared_day_id_and_receiver_epoch_take_precedence_over_the_fallback(tmp_path):
    capture_dir = tmp_path / "captures" / "BLE-IQ-DECLARED"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture_manifest.json").write_text(
        '{"capture_id":"BLE-IQ-DECLARED","experimental_metadata":{"session_id":"S999"},'
        '"sample_rate_sps":4000000,"sample_format":"cf32_le","sample_count":1,"center_frequency_hz":1,'
        '"bandwidth_hz":1,"bytes_per_cpu_sample":8,"actual_duration_seconds":1.0,"data_path":"x.sigmf-data",'
        '"actual_file_size_bytes":1,"file_size":1,"data_sha256":"abc","created_at_utc":"2026-01-01T00:00:00Z",'
        '"diagnostic_status":"PASSED","continuity_status":"PASSED","hash_status":"VERIFIED","capture_complete":true,'
        '"day_id":"OPERATOR-DECLARED-DAY-3","receiver_epoch":"OPERATOR-DECLARED-EPOCH-2"}',
        encoding="utf-8",
    )
    stage = CaptureStage(tmp_path / "captures")
    capture = stage.build_capture_record(capture_id="BLE-IQ-DECLARED", project_id="P1", campaign_id="C1", execution_id="EXEC-1")
    assert capture.day_id == "OPERATOR-DECLARED-DAY-3"
    assert capture.receiver_epoch == "OPERATOR-DECLARED-EPOCH-2"


def test_capture_record_round_trips_through_canonical_json(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01")
    from app.modules.ble_rffi_studio.contracts import CaptureRecord
    import json
    restored = CaptureRecord.model_validate(json.loads(capture.canonical_json()))
    assert restored == capture


def test_explicit_execution_id_overrides_inference(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="P1", campaign_id="C1", execution_id="EXPLICIT-OVERRIDE")
    assert capture.execution_id == "EXPLICIT-OVERRIDE"


def test_day_id_prefers_b200_rf_started_at_over_created_at_utc(tmp_path):
    """Point-2 correction (2026-08-08): day_id's primary source is the real
    RF-acquisition start, not the acquisition job's own start time. This
    fixture deliberately puts them on DIFFERENT calendar days (a job that
    started just before midnight UTC but didn't actually start sampling RF
    until after it) to prove the two are not silently interchangeable."""
    capture_dir = tmp_path / "captures" / "BLE-IQ-DAYSPLIT"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture_manifest.json").write_text(
        '{"capture_id":"BLE-IQ-DAYSPLIT","experimental_metadata":{"session_id":"S999"},'
        '"sample_rate_sps":4000000,"sample_format":"cf32_le","sample_count":1,"center_frequency_hz":1,'
        '"bandwidth_hz":1,"bytes_per_cpu_sample":8,"actual_duration_seconds":1.0,"data_path":"x.sigmf-data",'
        '"actual_file_size_bytes":1,"file_size":1,"data_sha256":"abc",'
        '"created_at_utc":"2026-08-01T23:59:55Z","b200_rf_started_at":"2026-08-02T00:00:03Z",'
        '"diagnostic_status":"PASSED","continuity_status":"PASSED","hash_status":"VERIFIED","capture_complete":true}',
        encoding="utf-8",
    )
    stage = CaptureStage(tmp_path / "captures")
    capture = stage.build_capture_record(capture_id="BLE-IQ-DAYSPLIT", project_id="P1", campaign_id="C1", execution_id="EXEC-1")
    assert capture.day_id == "2026-08-02"  # the real RF day, not the job-start day (2026-08-01)
    assert capture.day_id_source == "B200_RF_STARTED_AT"


def test_day_id_falls_back_to_created_at_utc_when_b200_rf_started_at_is_missing(tmp_path):
    capture_dir = tmp_path / "captures" / "BLE-IQ-NORFSTART"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture_manifest.json").write_text(
        '{"capture_id":"BLE-IQ-NORFSTART","experimental_metadata":{"session_id":"S999"},'
        '"sample_rate_sps":4000000,"sample_format":"cf32_le","sample_count":1,"center_frequency_hz":1,'
        '"bandwidth_hz":1,"bytes_per_cpu_sample":8,"actual_duration_seconds":1.0,"data_path":"x.sigmf-data",'
        '"actual_file_size_bytes":1,"file_size":1,"data_sha256":"abc","created_at_utc":"2026-08-01T12:00:00Z",'
        '"diagnostic_status":"PASSED","continuity_status":"PASSED","hash_status":"VERIFIED","capture_complete":true}',
        encoding="utf-8",
    )
    stage = CaptureStage(tmp_path / "captures")
    capture = stage.build_capture_record(capture_id="BLE-IQ-NORFSTART", project_id="P1", campaign_id="C1", execution_id="EXEC-1")
    assert capture.day_id == "2026-08-01"
    assert capture.day_id_source == "CREATED_AT_FALLBACK"


def test_missing_execution_id_and_no_replay_raises(tmp_path):
    # A capture directory with a manifest but no offline_replays/ at all, and
    # no explicit execution_id supplied -- must fail loudly, not fabricate one.
    capture_dir = tmp_path / "captures" / "BLE-IQ-FAKE"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture_manifest.json").write_text(
        '{"capture_id":"BLE-IQ-FAKE","experimental_metadata":{"session_id":"S999"},'
        '"sample_rate_sps":4000000,"sample_format":"cf32_le","sample_count":1,"center_frequency_hz":1,'
        '"bandwidth_hz":1,"bytes_per_cpu_sample":8,"actual_duration_seconds":1.0,"data_path":"x.sigmf-data",'
        '"actual_file_size_bytes":1,"file_size":1,"data_sha256":"abc","created_at_utc":"2026-01-01T00:00:00Z",'
        '"diagnostic_status":"PASSED","continuity_status":"PASSED","hash_status":"VERIFIED","capture_complete":true}',
        encoding="utf-8",
    )
    stage = CaptureStage(tmp_path / "captures")
    with pytest.raises(ExecutionIdRequiredError):
        stage.build_capture_record(capture_id="BLE-IQ-FAKE", project_id="P1", campaign_id="C1")
