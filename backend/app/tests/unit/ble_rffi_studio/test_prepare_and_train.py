"""'Prepare dataset and train' guided orchestration: the whole
evidence->dataset->gate->split->train-all-candidates->evaluate->compare
chain behind one call, stopping cleanly with a human-readable reason at
whichever real gate fails -- never a fabricated success.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord

from ._helpers import write_synthetic_capture_iq, write_target_vs_background_fixture

PROJECT_ID = "SYN-PROJECT"


def _seed_captures_from_examples(repository: StudioRepository, tmp_path: Path, examples, iq_paths, capture_purpose_by_capture: dict[str, str] | None = None):
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
            execution_id=f"EXEC-{capture_id}", data_origin="SYNTHETIC_TEST_ONLY", receiver_device_id="synthetic", sdr_model="synthetic", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="synthetic", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
            capture_purpose=(capture_purpose_by_capture or {}).get(capture_id),
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

    return list(by_capture.keys())


def _seed_synthetic_capture(repository: StudioRepository, tmp_path: Path, **kwargs):
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_iq_dir, **kwargs)
    return _seed_captures_from_examples(repository, tmp_path, examples, iq_paths)


def _seed_target_vs_background_capture(repository: StudioRepository, tmp_path: Path, **kwargs):
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_target_vs_background_fixture(raw_iq_dir, **kwargs)
    capture_purpose_by_capture = {e.capture_id: e.capture_purpose for e in examples}
    return _seed_captures_from_examples(repository, tmp_path, examples, iq_paths, capture_purpose_by_capture)


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_prepare_and_train_succeeds_end_to_end_on_synthetic_multi_unit_data(repository, tmp_path):
    capture_ids = _seed_synthetic_capture(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    phases_seen = []

    def progress(phase, phase_progress, message):
        phases_seen.append(message)

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot", progress=progress,
    )

    assert result["stopped_at"] is None
    assert result["quality_report"].gate_decision == "ACCEPTED_FOR_TRAINING"
    assert result["split"].split_status == "READY"
    assert result["trained_models"]  # at least one model actually trained
    assert result["recommended_training_run_id"] is not None
    assert result["recommended_reason"]
    # quick_pilot never attempts CNNs.
    assert all(m["model_type"] not in ("cnn1d", "cnn2d") for m in result["trained_models"])
    assert any("1/9" in p for p in phases_seen)
    assert any("9/9" in p for p in phases_seen)

    # The recommended run is real and independently retrievable.
    stored = repository.get_training_run(result["recommended_training_run_id"])
    assert stored["status"] == "COMPLETED"
    evaluation = repository.get_evaluation(result["recommended_training_run_id"])
    assert evaluation is not None


def test_prepare_and_train_stops_at_split_with_a_human_explanation(repository, tmp_path):
    capture_ids = _seed_synthetic_capture(repository, tmp_path, units=1, sessions_per_unit=1, examples_per_session=10)

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-INSUFFICIENT-DS",
    )

    assert result["stopped_at"] == "split"
    assert result["split"].split_status == "NOT_FEASIBLE"
    assert "unidad" in result["stopped_reason"].lower()
    assert result["feasibility"]["feasible"] is False
    assert result["trained_models"] == []
    assert result["recommended_training_run_id"] is None


def test_prepare_and_train_reports_no_model_accepted_when_classes_are_indistinguishable(repository, tmp_path, monkeypatch):
    # A real near-chance classifier is inherently noisy on a small held-out
    # set (it can clear 0.5 by luck), so this pins the score deterministically
    # below the acceptance bar instead of fighting RNG variance -- the point
    # under test is prepare_and_train's refusal to recommend, not the
    # underlying classifier's separability.
    import app.modules.ble_rffi_studio.api.studio_repository as studio_repository_module

    def _always_below_acceptance_bar(evaluation_report, calibration, latency_ms, model_size_bytes):
        return {
            "macro_f1": 0.2, "balanced_accuracy_proxy": 0.2, "unknown_capability_penalty": 0.0,
            "latency_ms": latency_ms, "model_size_bytes": model_size_bytes, "composite_score": 0.1,
            "formula": "test override: pinned below the acceptance bar",
        }

    monkeypatch.setattr(studio_repository_module, "score_model", _always_below_acceptance_bar)

    capture_ids = _seed_synthetic_capture(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-NOISY-DS", speed_profile="quick_pilot",
    )

    assert result["stopped_at"] == "model_selection"
    assert "NO_MODEL_ACCEPTED" in result["stopped_reason"]
    assert result["recommended_training_run_id"] is None
    assert result["recommended_reason"] is None
    assert result["final_test_evaluation"] is None
    # Every candidate was still actually trained and scored -- this is a
    # deliberate refusal to recommend, not a training failure.
    assert result["trained_models"]


def test_prepare_and_train_skips_cnn_when_infeasible_but_still_trains_baselines(repository, tmp_path):
    # Enough sessions for a READY split, and enough examples for the
    # (genuinely separable) baselines to clear the acceptance bar, but still
    # too few per class in TRAIN for a CNN to be considered a real,
    # evaluable training run (CNN_MIN_TRAIN_EXAMPLES_PER_CLASS=15).
    capture_ids = _seed_synthetic_capture(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-SMALL-DS", speed_profile="normal",
    )

    assert result["stopped_at"] is None
    skipped_types = {m["model_type"] for m in result["skipped_models"]}
    assert {"cnn1d", "cnn2d"} <= skipped_types
    assert all("insuficiente" in m["reason"] for m in result["skipped_models"] if m["model_type"] in ("cnn1d", "cnn2d"))
    assert result["trained_models"]  # baselines still ran


def test_prepare_and_train_with_normal_profile_includes_the_frozen_reference_baseline(repository, tmp_path):
    """RQ2's 4th branch (2026-08-08): frozen_morphological_baseline is part
    of the real, guided pipeline's "normal" candidate set -- not a
    standalone capability nobody's flow actually exercises."""
    capture_ids = _seed_synthetic_capture(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-FROZEN-DS", speed_profile="normal",
    )

    assert result["stopped_at"] is None
    trained_types = {m["model_type"] for m in result["trained_models"]}
    assert "frozen_morphological_baseline" in trained_types
    frozen_run_id = next(m["training_run_id"] for m in result["trained_models"] if m["model_type"] == "frozen_morphological_baseline")
    stored = repository.get_training_run(frozen_run_id)
    assert stored["status"] == "COMPLETED"
    assert stored["representation_profile_id"] == "morphological_coarse_tf-v1"


def test_prepare_and_train_succeeds_end_to_end_on_synthetic_target_vs_background_data(repository, tmp_path):
    # The exact scenario the reviewer demanded be proven end-to-end: both
    # TARGET_DEVICE and BACKGROUND_ENVIRONMENT genuinely present and
    # separable, producing a real 2-class result -- not the old single-class
    # TRAIN bug (see split_builder.py's module docstring for the root cause).
    capture_ids = _seed_target_vs_background_capture(
        repository, tmp_path, target_sessions=3, background_sessions=3, examples_per_session=16,
    )

    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="TARGET_VS_BACKGROUND", dataset_id="SYN-TVB-DS", speed_profile="quick_pilot",
    )

    assert result["stopped_at"] is None
    assert result["split"].split_status == "READY"
    assert result["trained_models"]
    assert result["recommended_training_run_id"] is not None

    evaluation = repository.get_evaluation(result["recommended_training_run_id"])
    assert evaluation is not None
    test_report = evaluation["evaluation_report"]["TEST"]
    assert test_report["evaluation_validity"] == "VALID"
    assert set(test_report["confusion_matrix"].keys()) == {"TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"}
