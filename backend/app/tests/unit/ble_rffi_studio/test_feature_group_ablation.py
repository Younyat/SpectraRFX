"""Feature-group ablation (exploratory, 2026-08-24):
train_feature_subset_variant() re-trains the EXACT SAME configuration as an
already-completed random_forest run, restricting the engineered feature
matrix to a column subset (feature_indices) -- never a new model selection,
never a new threshold choice, never touching TEST, never changing which
TRAIN/VALIDATION examples participate. Mirrors
test_rq4_region_specific_fitting.py's real end-to-end training fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord

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
def random_forest_run_id(repository, tmp_path):
    capture_ids = _seed_captures(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )
    # prepare_and_train's own VALIDATION-selected "recommended" candidate is
    # not guaranteed to be random_forest -- this ablation is explicitly
    # random_forest-only, so pick the real completed random_forest candidate
    # from this run's own real candidate pool instead of assuming the
    # recommendation matches.
    rf_runs = [r for r in repository.list_training_runs() if r.get("model_type") == "random_forest" and r.get("status") == "COMPLETED"]
    assert rf_runs, "expected at least one real completed random_forest candidate from prepare_and_train"
    return rf_runs[0]["training_run_id"]


def test_train_feature_subset_variant_trains_and_exports_a_real_bundle(repository, random_forest_run_id):
    base_stored = repository.get_training_run(random_forest_run_id)

    result = repository.train_feature_subset_variant(
        training_run_id=random_forest_run_id, feature_group="POWER_AMPLITUDE_LEVEL", feature_indices=[0, 1, 2, 3],
    )

    assert result["base_run_training_run_id"] == random_forest_run_id
    assert result["feature_group"] == "POWER_AMPLITUDE_LEVEL"
    assert result["feature_indices"] == [0, 1, 2, 3]
    assert result["validation_accuracy"] is not None
    assert result["approval_status"] == "TEST_NOT_EXECUTED"

    variant = repository.get_training_run(result["training_run_id"])
    assert variant["status"] == "COMPLETED"
    # Same frozen configuration otherwise -- never a new model selection.
    assert variant["model_type"] == base_stored["model_type"] == "random_forest"
    assert variant["random_seed"] == base_stored["random_seed"]
    assert variant["dataset_id"] == base_stored["dataset_id"]
    assert variant["base_preprocessing_profile_id"] == base_stored["base_preprocessing_profile_id"]
    assert variant["hyperparameters"] == base_stored["hyperparameters"]
    # Never opens TEST.
    assert variant["analysis_contract_protocol_id"] is None
    evaluation = repository.get_evaluation(result["training_run_id"])
    assert "TEST" not in (evaluation["evaluation_report"] or {})

    # Persisted feature_names.json reflects only the 4 selected columns.
    run_dir = repository.training_dir / result["training_run_id"]
    feature_names = __import__("json").loads((run_dir / "feature_names.json").read_text(encoding="utf-8"))["names"]
    assert feature_names == ["mean_power_dbfs", "std_power_db", "mean_abs_amplitude", "std_abs_amplitude"]

    # A real, OfflineInferenceService-usable bundle was exported.
    bundle = repository.get_bundle(result["bundle_id"])
    assert bundle is not None

    # The base (PRIMARY-equivalent) run is byte-for-byte untouched.
    assert repository.get_training_run(random_forest_run_id) == base_stored


def test_train_feature_subset_variant_train_and_validation_ids_match_the_base_run(repository, random_forest_run_id):
    base_predictions = __import__("json").loads((repository.training_dir / random_forest_run_id / "predictions.json").read_text(encoding="utf-8"))
    result = repository.train_feature_subset_variant(
        training_run_id=random_forest_run_id, feature_group="REMAINING_SIX", feature_indices=[4, 5, 6, 7, 8, 9],
    )
    variant_predictions = __import__("json").loads((repository.training_dir / result["training_run_id"] / "predictions.json").read_text(encoding="utf-8"))
    for split in ("TRAIN", "VALIDATION"):
        base_ids = [p["example_id"] for p in base_predictions[split]]
        variant_ids = [p["example_id"] for p in variant_predictions[split]]
        assert base_ids == variant_ids, f"{split} example_id set/order must be identical to the base run"


def test_train_feature_subset_variant_rejects_unknown_feature_group(repository, random_forest_run_id):
    with pytest.raises(ValueError, match="FEATURE_SUBSET_ABLATION_ONLY_SUPPORTS_POWER_AMPLITUDE_LEVEL_OR_REMAINING_SIX"):
        repository.train_feature_subset_variant(training_run_id=random_forest_run_id, feature_group="NOT_A_GROUP", feature_indices=[0])


def test_train_feature_subset_variant_raises_for_an_unknown_training_run_id(repository, random_forest_run_id):
    with pytest.raises(FileNotFoundError, match="TRAINING_RUN_NOT_FOUND"):
        repository.train_feature_subset_variant(training_run_id="not-a-real-run-id", feature_group="POWER_AMPLITUDE_LEVEL", feature_indices=[0, 1, 2, 3])


def test_train_feature_subset_variant_raises_on_an_incomplete_training_run(repository, random_forest_run_id):
    base_stored = repository.get_training_run(random_forest_run_id)
    base_stored["status"] = "QUEUED"
    write_json(repository.training_dir / random_forest_run_id / "training_run.json", base_stored)
    with pytest.raises(ValueError, match="CANNOT_RUN_FEATURE_SUBSET_ABLATION_ON_AN_INCOMPLETE_TRAINING_RUN"):
        repository.train_feature_subset_variant(training_run_id=random_forest_run_id, feature_group="POWER_AMPLITUDE_LEVEL", feature_indices=[0, 1, 2, 3])


def test_train_feature_subset_variant_rejects_non_random_forest_base_run(repository, tmp_path):
    capture_ids = _seed_captures(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )
    non_rf_runs = [r for r in repository.list_training_runs() if r.get("model_type") != "random_forest" and r.get("status") == "COMPLETED"]
    if not non_rf_runs:
        pytest.skip("no non-random_forest candidate produced by this synthetic run")
    with pytest.raises(ValueError, match="FEATURE_SUBSET_ABLATION_ONLY_SUPPORTS_RANDOM_FOREST_TODAY"):
        repository.train_feature_subset_variant(training_run_id=non_rf_runs[0]["training_run_id"], feature_group="POWER_AMPLITUDE_LEVEL", feature_indices=[0, 1, 2, 3])
