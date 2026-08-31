"""Fixed seed-set correction (2026-08-08): a real, explicit, frozen SET of
random seeds for the paper's optimization-variability analysis -- how much a
candidate's VALIDATION performance moves across independent training runs of
the exact same configuration. Previously a single, bare random_seed=42
literal, hardcoded at two call sites, with no variability analysis at all.
train_seed_variability_analysis() must never touch TEST for any re-trained
seed variant.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.api.studio_repository import FROZEN_TRAINING_SEEDS
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


def test_frozen_training_seeds_is_a_real_fixed_set_of_more_than_one_seed():
    assert len(FROZEN_TRAINING_SEEDS) >= 2
    assert len(set(FROZEN_TRAINING_SEEDS)) == len(FROZEN_TRAINING_SEEDS)  # no duplicates


def test_prepare_and_train_uses_the_frozen_sets_primary_seed(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    stored = repository.get_training_run(recommended_id)
    assert stored["random_seed"] == FROZEN_TRAINING_SEEDS[0]


def test_seed_variability_analysis_retrains_with_every_other_frozen_seed_and_never_touches_test(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    results = repository.train_seed_variability_analysis(training_run_id=recommended_id)

    expected_seeds = {s for s in FROZEN_TRAINING_SEEDS if s != FROZEN_TRAINING_SEEDS[0]}
    assert {r["seed"] for r in results} == expected_seeds
    for r in results:
        assert r["validation_accuracy"] is not None
        stored = repository.get_training_run(r["training_run_id"])
        assert stored["status"] == "COMPLETED"
        assert stored["random_seed"] == r["seed"]
        # The load-bearing check: no seed-variability run ever opens TEST.
        assert stored["analysis_contract_protocol_id"] is None
        evaluation = repository.get_evaluation(r["training_run_id"])
        assert "TEST" not in (evaluation["evaluation_report"] or {})


def test_seed_variability_analysis_rejects_a_seed_outside_the_frozen_set(repository, prepared_result):
    recommended_id = prepared_result["recommended_training_run_id"]
    with pytest.raises(ValueError, match="SEEDS_MUST_BE_FROM_THE_FROZEN_SET"):
        repository.train_seed_variability_analysis(training_run_id=recommended_id, seeds=(999999,))


def test_seed_variability_analysis_raises_for_an_unknown_training_run_id(repository, prepared_result):
    with pytest.raises(FileNotFoundError, match="TRAINING_RUN_NOT_FOUND"):
        repository.train_seed_variability_analysis(training_run_id="not-a-real-run-id")
