"""Sensitivity closure (2026-08-12): offset-retaining-v1 preprocessing
profile already existed (base_preprocessing_registry.py) but had zero real
callers. train_offset_retaining_sensitivity() re-trains the EXACT SAME
configuration as an already-completed run, varying ONLY
base_preprocessing_profile_id -- never a new model selection, never a new
threshold choice, never touching TEST. Mirrors
test_seed_variability.py's real end-to-end training fixture exactly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl

from ._helpers import write_synthetic_capture_iq

PROJECT_ID = "SYN-PROJECT"


def _seed_captures(repository: StudioRepository, tmp_path: Path, **kwargs) -> list[str]:
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_iq_dir, **kwargs)
    by_capture: dict[str, list] = {}
    for example in examples:
        by_capture.setdefault(example.capture_id, []).append(example)
    for capture_id, capture_examples in by_capture.items():
        capture_dir = repository.legacy_capture_root / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        dest = capture_dir / "iq.cf32"
        dest.write_bytes(iq_paths[capture_id].read_bytes())
        capture = CaptureRecord(
            project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01", capture_id=capture_id, session_id=capture_examples[0].session_id,
            execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", receiver_device_id="E3R04Z1B2", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])
    return list(by_capture.keys())


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


@pytest.fixture
def prepared_result(repository, tmp_path):
    capture_ids = _seed_captures(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    return repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )


def test_offset_retaining_sensitivity_retrains_the_same_configuration_and_never_touches_test(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    base_stored = repository.get_training_run(recommended_id)

    result = repository.train_offset_retaining_sensitivity(training_run_id=recommended_id)

    assert result["base_run_training_run_id"] == recommended_id
    assert result["base_preprocessing_profile_id"] == "offset-retaining-v1"
    assert result["validation_accuracy"] is not None
    assert result["coverage"] is None  # honest -- no calibrated-threshold path in this evaluation

    variant = repository.get_training_run(result["training_run_id"])
    assert variant["status"] == "COMPLETED"
    assert variant["base_preprocessing_profile_id"] == "offset-retaining-v1"
    # Same configuration otherwise -- never a new model selection.
    assert variant["model_type"] == base_stored["model_type"]
    assert variant["random_seed"] == base_stored["random_seed"]
    assert variant["dataset_id"] == base_stored["dataset_id"]
    # The load-bearing check: never opens TEST.
    assert variant["analysis_contract_protocol_id"] is None
    evaluation = repository.get_evaluation(result["training_run_id"])
    assert "TEST" not in (evaluation["evaluation_report"] or {})


def test_offset_retaining_sensitivity_raises_for_an_unknown_training_run_id(repository, prepared_result):
    with pytest.raises(FileNotFoundError, match="TRAINING_RUN_NOT_FOUND"):
        repository.train_offset_retaining_sensitivity(training_run_id="not-a-real-run-id")


def test_offset_retaining_sensitivity_raises_on_an_incomplete_training_run(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    base_stored = repository.get_training_run(recommended_id)
    base_stored["status"] = "QUEUED"
    from app.infrastructure.ble.capture.ble_offline_replay import write_json as _write_json
    _write_json(repository.training_dir / recommended_id / "training_run.json", base_stored)
    with pytest.raises(ValueError, match="CANNOT_RUN_OFFSET_RETAINING_SENSITIVITY_ON_AN_INCOMPLETE_TRAINING_RUN"):
        repository.train_offset_retaining_sensitivity(training_run_id=recommended_id)
