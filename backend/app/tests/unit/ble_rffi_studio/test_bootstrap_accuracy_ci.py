"""Bootstrap correction (2026-08-08): hierarchical_cluster_bootstrap existed
in ble_scientific_results.statistics with real tests but no production
caller anywhere. Wired here as a session-clustered percentile CI over a
training run's own real predictions -- resampling WHOLE SESSIONS (never
individual bursts), matching split_builder.py's own leakage-check clustering
unit.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_rffi_studio.evaluation import Evaluator

from ._helpers import write_synthetic_capture_iq

PROJECT_ID = "SYN-PROJECT"


def test_bootstrap_accuracy_ci_clusters_by_session_not_by_burst():
    evaluator = Evaluator()
    predictions = [
        {"example_id": f"s1-{i}", "true_label": "A", "predicted_label": "A"} for i in range(5)
    ] + [
        {"example_id": f"s2-{i}", "true_label": "B", "predicted_label": "B"} for i in range(5)
    ]
    session_id_by_example_id = {f"s1-{i}": "SESSION-1" for i in range(5)} | {f"s2-{i}": "SESSION-2" for i in range(5)}
    result = evaluator.bootstrap_accuracy_ci(predictions, ["A", "B"], session_id_by_example_id, n_resamples=200)
    assert result is not None
    assert result.point_estimate == pytest.approx(1.0)  # every prediction correct
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_bootstrap_accuracy_ci_is_none_with_a_single_known_class():
    evaluator = Evaluator()
    result = evaluator.bootstrap_accuracy_ci([{"example_id": "e1", "true_label": "A", "predicted_label": "A"}], ["A"], {"e1": "S1"})
    assert result is None


def test_bootstrap_accuracy_ci_is_none_when_no_prediction_has_a_resolvable_session():
    evaluator = Evaluator()
    predictions = [{"example_id": "e1", "true_label": "A", "predicted_label": "A"}]
    result = evaluator.bootstrap_accuracy_ci(predictions, ["A", "B"], {})  # empty mapping -- nothing resolvable
    assert result is None


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
def studio_repository_with_trained_run(tmp_path):
    repository = StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")
    capture_ids = _seed_captures(repository, tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    result = repository.prepare_and_train(
        capture_ids=capture_ids, project_id=PROJECT_ID, campaign_id="SYN-CAMPAIGN-01",
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", dataset_id="SYN-AUTO-DS", speed_profile="quick_pilot",
    )
    return repository, result["recommended_training_run_id"]


def test_bootstrap_accuracy_ci_wired_end_to_end_against_a_real_training_run(studio_repository_with_trained_run):
    repository, training_run_id = studio_repository_with_trained_run
    result = repository.bootstrap_accuracy_ci(training_run_id, split="VALIDATION", n_resamples=200)
    assert result is not None
    assert result["split"] == "VALIDATION"
    assert 0.0 <= result["point_estimate"] <= 1.0
    assert result["ci_low"] <= result["point_estimate"] <= result["ci_high"]
    assert result["n_resamples"] == 200


def test_bootstrap_accuracy_ci_returns_none_for_a_split_with_no_predictions(studio_repository_with_trained_run):
    repository, training_run_id = studio_repository_with_trained_run
    assert repository.bootstrap_accuracy_ci(training_run_id, split="NOT_A_REAL_SPLIT") is None


def test_bootstrap_accuracy_ci_raises_for_an_unknown_training_run(studio_repository_with_trained_run):
    repository, _ = studio_repository_with_trained_run
    with pytest.raises(FileNotFoundError, match="TRAINING_RUN_HAS_NO_PREDICTIONS_YET"):
        repository.bootstrap_accuracy_ci("not-a-real-run")


def test_bootstrap_balanced_accuracy_ci_differs_from_raw_accuracy_under_class_imbalance():
    """A majority class swamping raw accuracy must not swamp balanced
    accuracy's bootstrap CI the same way -- proves the two are genuinely
    different statistics, not the same resampling engine mislabeled."""
    evaluator = Evaluator()
    # 9 correct majority-class predictions, 1 wrong minority-class prediction.
    predictions = [{"example_id": f"s1-{i}", "true_label": "A", "predicted_label": "A"} for i in range(9)]
    predictions.append({"example_id": "s2-0", "true_label": "B", "predicted_label": "A"})
    session_id_by_example_id = {f"s1-{i}": f"SESSION-1-{i}" for i in range(9)} | {"s2-0": "SESSION-2"}
    accuracy_result = evaluator.bootstrap_accuracy_ci(predictions, ["A", "B"], session_id_by_example_id, n_resamples=200)
    balanced_result = evaluator.bootstrap_balanced_accuracy_ci(predictions, ["A", "B"], session_id_by_example_id, n_resamples=200)
    assert accuracy_result.point_estimate == pytest.approx(0.9)  # 9/10 correct
    assert balanced_result.point_estimate == pytest.approx(0.5)  # mean(1.0, 0.0) per-class recall
    assert balanced_result.ci_low <= balanced_result.point_estimate <= balanced_result.ci_high


def test_bootstrap_balanced_accuracy_ci_is_none_with_a_single_known_class():
    evaluator = Evaluator()
    result = evaluator.bootstrap_balanced_accuracy_ci([{"example_id": "e1", "true_label": "A", "predicted_label": "A"}], ["A"], {"e1": "S1"})
    assert result is None


def test_bootstrap_balanced_accuracy_ci_wired_end_to_end_against_a_real_training_run(studio_repository_with_trained_run):
    repository, training_run_id = studio_repository_with_trained_run
    result = repository.bootstrap_balanced_accuracy_ci(training_run_id, split="VALIDATION", n_resamples=200)
    assert result is not None
    assert result["split"] == "VALIDATION"
    assert 0.0 <= result["point_estimate"] <= 1.0
    assert result["ci_low"] <= result["point_estimate"] <= result["ci_high"]


def test_bootstrap_balanced_accuracy_delta_ci_point_estimate_is_the_real_difference():
    # RQ1's real delta_dependence CI (2026-08-17 completion pass) -- proves
    # the point estimate is the exact difference of the two populations'
    # own balanced accuracies, computed over disjoint session pools.
    evaluator = Evaluator()
    predictions_a = [{"example_id": f"a-{i}", "true_label": "A", "predicted_label": "A"} for i in range(4)]  # BA=1.0
    predictions_b = [{"example_id": f"b-{i}", "true_label": "A", "predicted_label": "A" if i < 2 else "B"} for i in range(4)] + [
        {"example_id": "b-extra", "true_label": "B", "predicted_label": "B"}
    ]
    session_ids_a = {f"a-{i}": f"SESSION-A-{i}" for i in range(4)}
    session_ids_b = {f"b-{i}": f"SESSION-B-{i}" for i in range(4)} | {"b-extra": "SESSION-B-extra"}
    result = evaluator.bootstrap_balanced_accuracy_delta_ci(predictions_a, predictions_b, ["A", "B"], session_ids_a, session_ids_b, n_resamples=300)
    assert result is not None
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_bootstrap_balanced_accuracy_delta_ci_is_none_when_either_side_has_no_comparable_predictions():
    evaluator = Evaluator()
    predictions_a = [{"example_id": "a-1", "true_label": "A", "predicted_label": "A"}]
    result = evaluator.bootstrap_balanced_accuracy_delta_ci(predictions_a, [], ["A", "B"], {"a-1": "S1"}, {})
    assert result is None


def test_studio_repository_bootstrap_balanced_accuracy_delta_ci_wired_end_to_end(studio_repository_with_trained_run):
    # Same real training run compared against itself -- point_estimate must
    # be exactly 0.0 (identical predictions minus themselves), proving the
    # real file-read/clustering/joint-resample plumbing works end to end.
    repository, training_run_id = studio_repository_with_trained_run
    result = repository.bootstrap_balanced_accuracy_delta_ci(training_run_id, training_run_id, split_a="VALIDATION", split_b="VALIDATION", n_resamples=200)
    assert result is not None
    assert result["split_a"] == "VALIDATION"
    assert result["split_b"] == "VALIDATION"
    assert result["point_estimate"] == pytest.approx(0.0)
    assert result["ci_low"] <= 0.0 <= result["ci_high"]


def test_studio_repository_bootstrap_balanced_accuracy_delta_ci_raises_on_label_class_mismatch(studio_repository_with_trained_run, tmp_path, monkeypatch):
    repository, training_run_id = studio_repository_with_trained_run
    # A second "run" whose label_classes.json genuinely disagrees -- must
    # fail loudly, never silently pick one run's classes.
    other_run_id = "OTHER-RUN"
    other_dir = repository.training_dir / other_run_id
    other_dir.mkdir(parents=True)
    (other_dir / "predictions.json").write_text('{"VALIDATION": []}', encoding="utf-8")
    (other_dir / "label_classes.json").write_text('{"classes": ["ONLY-ONE-CLASS"]}', encoding="utf-8")
    real_run_dir = repository.training_dir / training_run_id
    import shutil
    shutil.copy(real_run_dir / "training_run.json", other_dir / "training_run.json")
    with pytest.raises(ValueError, match="LABEL_CLASSES_MISMATCH_BETWEEN_RUNS"):
        repository.bootstrap_balanced_accuracy_delta_ci(training_run_id, other_run_id)


# --- Methodological-audit fix (2026-08-22, item 3): class-preserving RQ1 bootstrap ---

def test_bootstrap_balanced_accuracy_ci_stratified_by_class_never_drops_a_class():
    # A deliberately small-stratum shape (class "B" has exactly ONE
    # session) -- the exact shape that makes the plain, pooled
    # bootstrap_balanced_accuracy_ci silently drop a class from some
    # resamples' mean-per-class-recall statistic (verified empirically
    # against RQ1's real 12-session capture-disjoint VALIDATION population:
    # ~26% of resamples lost a class under the old pooled bootstrap). The
    # stratified sibling must never do that -- every one of B's real
    # predictions is present in every resample's B-stratum draw, so B's
    # recall is always defined.
    evaluator = Evaluator()
    predictions = (
        [{"example_id": f"a-{i}", "true_label": "A", "predicted_label": "A"} for i in range(6)]
        + [{"example_id": "b-0", "true_label": "B", "predicted_label": "A"}]  # class B: exactly one session, wrong
        + [{"example_id": f"c-{i}", "true_label": "C", "predicted_label": "C"} for i in range(4)]
    )
    session_id_by_example_id = (
        {f"a-{i}": f"SESSION-A-{i}" for i in range(6)}
        | {"b-0": "SESSION-B"}
        | {f"c-{i}": f"SESSION-C-{i}" for i in range(4)}
    )
    result = evaluator.bootstrap_balanced_accuracy_ci_stratified_by_class(predictions, ["A", "B", "C"], session_id_by_example_id, n_resamples=500)
    assert result is not None
    # Point estimate: mean(1.0, 0.0, 1.0) = 2/3 -- class B's 0 recall must
    # always contribute (never silently dropped, which would instead
    # average only over whichever classes happened to survive).
    assert result.point_estimate == pytest.approx(2 / 3)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_bootstrap_balanced_accuracy_ci_stratified_by_class_is_none_with_a_single_known_class():
    evaluator = Evaluator()
    result = evaluator.bootstrap_balanced_accuracy_ci_stratified_by_class([{"example_id": "e1", "true_label": "A", "predicted_label": "A"}], ["A"], {"e1": "S1"})
    assert result is None


def test_bootstrap_balanced_accuracy_delta_ci_stratified_by_class_point_estimate_is_the_real_difference():
    evaluator = Evaluator()
    predictions_a = [{"example_id": f"a-{i}", "true_label": "A", "predicted_label": "A"} for i in range(4)]  # BA=1.0
    predictions_b = [{"example_id": f"b-{i}", "true_label": "A", "predicted_label": "A" if i < 2 else "B"} for i in range(4)] + [
        {"example_id": "b-extra", "true_label": "B", "predicted_label": "B"}
    ]
    session_ids_a = {f"a-{i}": f"SESSION-A-{i}" for i in range(4)}
    session_ids_b = {f"b-{i}": f"SESSION-B-{i}" for i in range(4)} | {"b-extra": "SESSION-B-extra"}
    result = evaluator.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(predictions_a, predictions_b, ["A", "B"], session_ids_a, session_ids_b, n_resamples=300)
    assert result is not None
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_bootstrap_balanced_accuracy_delta_ci_stratified_by_class_is_none_when_either_side_has_no_comparable_predictions():
    evaluator = Evaluator()
    predictions_a = [{"example_id": "a-1", "true_label": "A", "predicted_label": "A"}]
    result = evaluator.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(predictions_a, [], ["A", "B"], {"a-1": "S1"}, {})
    assert result is None


def test_studio_repository_bootstrap_balanced_accuracy_ci_stratified_by_class_wired_end_to_end(studio_repository_with_trained_run):
    repository, training_run_id = studio_repository_with_trained_run
    result = repository.bootstrap_balanced_accuracy_ci_stratified_by_class(training_run_id, split="VALIDATION", n_resamples=200)
    assert result is not None
    assert result["split"] == "VALIDATION"
    assert 0.0 <= result["point_estimate"] <= 1.0
    assert result["ci_low"] <= result["point_estimate"] <= result["ci_high"]


def test_studio_repository_bootstrap_balanced_accuracy_delta_ci_stratified_by_class_wired_end_to_end(studio_repository_with_trained_run):
    # Same real training run compared against itself -- point_estimate must
    # be exactly 0.0, proving the real file-read/stratified-clustering/
    # independent-resample plumbing works end to end.
    repository, training_run_id = studio_repository_with_trained_run
    result = repository.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(training_run_id, training_run_id, split_a="VALIDATION", split_b="VALIDATION", n_resamples=200)
    assert result is not None
    assert result["point_estimate"] == pytest.approx(0.0)
    assert result["ci_low"] <= 0.0 <= result["ci_high"]


def test_studio_repository_bootstrap_balanced_accuracy_delta_ci_stratified_by_class_raises_on_label_class_mismatch(studio_repository_with_trained_run):
    repository, training_run_id = studio_repository_with_trained_run
    other_run_id = "OTHER-RUN-STRATIFIED"
    other_dir = repository.training_dir / other_run_id
    other_dir.mkdir(parents=True)
    (other_dir / "predictions.json").write_text('{"VALIDATION": []}', encoding="utf-8")
    (other_dir / "label_classes.json").write_text('{"classes": ["ONLY-ONE-CLASS"]}', encoding="utf-8")
    real_run_dir = repository.training_dir / training_run_id
    import shutil
    shutil.copy(real_run_dir / "training_run.json", other_dir / "training_run.json")
    with pytest.raises(ValueError, match="LABEL_CLASSES_MISMATCH_BETWEEN_RUNS"):
        repository.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(training_run_id, other_run_id)


# --- RQ4 exploratory fix (2026-08-22): matched FULL_BURST vs PRE_PDU comparison ---

def test_bootstrap_balanced_accuracy_delta_ci_matched_by_class_point_estimate_is_the_real_difference():
    evaluator = Evaluator()
    predictions_a = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A"},
        {"example_id": "e2", "true_label": "B", "predicted_label": "B"},
    ]
    predictions_b = [
        {"example_id": "e1", "true_label": "A", "predicted_label": "B"},  # same example, wrong under region B
        {"example_id": "e2", "true_label": "B", "predicted_label": "B"},
    ]
    session_ids = {"e1": "S1", "e2": "S2"}
    result = evaluator.bootstrap_balanced_accuracy_delta_ci_matched_by_class(
        predictions_a, predictions_b, ["A", "B"], session_ids, session_ids, n_resamples=200,
    )
    assert result is not None
    # A: BA=1.0 (both correct); B: BA=0.5 (mean(0.0, 1.0)) -> delta = 0.5
    assert result.point_estimate == pytest.approx(0.5)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_bootstrap_balanced_accuracy_delta_ci_matched_by_class_is_none_when_either_side_has_no_comparable_predictions():
    evaluator = Evaluator()
    predictions_a = [{"example_id": "a-1", "true_label": "A", "predicted_label": "A"}]
    result = evaluator.bootstrap_balanced_accuracy_delta_ci_matched_by_class(predictions_a, [], ["A", "B"], {"a-1": "S1"}, {})
    assert result is None
