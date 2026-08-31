"""Study Control Center, phase 08 (2026-08-11): rq2_benchmark.py drives the
real train_selected_models() orchestration -- tested here with a STUB
StudioRepository (never real training/hardware) whose train_selected_models
returns the real, un-stripped result shape (trained_models[i].evaluation/
score) confirmed by direct inspection of studio_repository.py. Proves the
branch-mapping/tie-break/PRIMARY-selection logic and that a real training
stop (quality gate, no accepted model) never produces a fabricated report.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.rq2_benchmark import Rq2BenchmarkError, map_training_result_to_rq2_branches, run_rq2_benchmark

PROJECT_ID = "P1"


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_split(repo, *, dataset_id: str, dataset_version: str, scientific_task: str) -> None:
    payload = {
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": dataset_id, "dataset_version": dataset_version,
        "scientific_task": scientific_task, "policy": "test-policy", "split_status": "READY",
        "assignments": [{"example_id": "ex-1", "physical_unit_id": "UNIT-A", "capture_id": "CAP-1", "session_id": "S1", "split": "VALIDATION", "split_reason": "test"}],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-11T00:00:00Z", "split_manifest_sha256": "real-split-hash",
    }
    path = repo.ble_root / "splits" / f"{dataset_id}__{dataset_version}__{scientific_task}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _trained_model(model_type: str, *, composite_score: float, balanced_accuracy: float, run_suffix: str) -> dict:
    return {
        "training_run_id": f"RUN-{run_suffix}", "model_type": model_type,
        "evaluation": {"evaluation_report": {"VALIDATION": {"balanced_accuracy": balanced_accuracy, "macro_f1": balanced_accuracy - 0.02, "recall_per_class": {"A": 0.9, "B": 0.8}}}},
        "score": {"composite_score": composite_score, "model_size_bytes": 12_345, "latency_ms": 4.2},
    }


class _StubStudioRepository:
    def __init__(self, result: dict, *, seed_variability: list[dict] | None = None) -> None:
        self.result = result
        self.calls: list[dict] = []
        self.seed_variability_calls: list[str] = []
        self._seed_variability = seed_variability if seed_variability is not None else []

    def train_selected_models(self, **kwargs):
        self.calls.append(kwargs)
        return self.result

    def train_seed_variability_analysis(self, *, training_run_id: str, seeds=None, progress=None):
        self.seed_variability_calls.append(training_run_id)
        return self._seed_variability

    def bootstrap_balanced_accuracy_ci(self, training_run_id: str, *, split: str = "VALIDATION", n_resamples: int = 2000, confidence_level: float = 0.95):
        return {"split": split, "point_estimate": 0.8, "ci_low": 0.7, "ci_high": 0.9, "n_resamples": n_resamples, "confidence_level": confidence_level}


def test_map_training_result_picks_the_best_model_per_branch_and_primary_by_composite_score():
    training_result = {"trained_models": [
        _trained_model("logistic_regression", composite_score=0.5, balanced_accuracy=0.7, run_suffix="LR"),
        _trained_model("svm_rbf", composite_score=0.6, balanced_accuracy=0.75, run_suffix="SVM"),  # best of engineered_rf
        _trained_model("random_forest", composite_score=0.55, balanced_accuracy=0.72, run_suffix="RF"),
        _trained_model("cnn1d", composite_score=0.9, balanced_accuracy=0.95, run_suffix="CNN1D"),  # highest overall -> PRIMARY
        _trained_model("cnn2d", composite_score=0.4, balanced_accuracy=0.6, run_suffix="CNN2D"),
    ]}
    branches, selection_rule = map_training_result_to_rq2_branches(training_result)
    by_branch = {b["branch"]: b for b in branches}

    assert by_branch["engineered_rf"]["model_type"] == "svm_rbf"  # highest composite among the 3 engineered_rf candidates
    assert by_branch["engineered_rf"]["analysis_role"] == "UNSELECTED"
    assert by_branch["raw_iq"]["analysis_role"] == "PRIMARY"
    assert by_branch["raw_iq"]["balanced_accuracy"] == 0.95
    assert by_branch["stft"]["analysis_role"] == "UNSELECTED"
    assert "coarse_morphology" not in by_branch  # no frozen_morphological_baseline was trained -- honestly absent
    assert selection_rule  # real descriptive string, not empty/None when a branch was selected


def test_map_training_result_is_empty_when_no_recognized_branch_trained():
    assert map_training_result_to_rq2_branches({"trained_models": []}) == ([], None)


def test_run_rq2_benchmark_persists_a_real_canonical_report(tmp_path):
    repo = _repo(tmp_path)
    _write_split(repo, dataset_id="DS1", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    training_result = {"trained_models": [_trained_model("cnn1d", composite_score=0.9, balanced_accuracy=0.95, run_suffix="CNN1D")], "skipped_models": []}
    studio = _StubStudioRepository(training_result)

    result = run_rq2_benchmark(studio_repository=studio, sci_repository=repo, paper_run_id="RUN-1", dataset_id="DS1", dataset_version="1.0.0")

    assert result["stopped_at"] is None
    assert result["rq2_report"]["branches"][0]["branch"] == "raw_iq"
    assert result["rq2_report"]["split_manifest_sha256"] == "real-split-hash"
    reloaded = repo.get_rq2_representation_comparison_report("RUN-1")
    assert reloaded == result["rq2_report"]


def test_run_rq2_benchmark_never_persists_when_training_stopped_at_a_real_gate(tmp_path):
    repo = _repo(tmp_path)
    studio = _StubStudioRepository({"stopped_at": "quality_gate", "stopped_reason": "El dataset no supero el control de calidad", "trained_models": []})

    result = run_rq2_benchmark(studio_repository=studio, sci_repository=repo, paper_run_id="RUN-1", dataset_id="DS1", dataset_version="1.0.0")

    assert result["stopped_at"] == "quality_gate"
    assert result["rq2_report"] is None
    assert repo.get_rq2_representation_comparison_report("RUN-1") is None


def test_run_rq2_benchmark_raises_without_a_studio_repository(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(Rq2BenchmarkError):
        run_rq2_benchmark(studio_repository=None, sci_repository=repo, paper_run_id="RUN-1", dataset_id="DS1", dataset_version="1.0.0")


def test_run_rq2_benchmark_wires_real_seed_variability_into_the_primary_branch_only(tmp_path):
    """Dashboard closure (2026-08-11), Case A: train_seed_variability_analysis
    is real and tested but was previously never called from RQ2 Benchmark --
    now wired for the PRIMARY branch only (bounded real compute cost), never
    for an UNSELECTED branch that never needed it for the paper."""
    repo = _repo(tmp_path)
    _write_split(repo, dataset_id="DS1", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    training_result = {"trained_models": [
        _trained_model("cnn1d", composite_score=0.9, balanced_accuracy=0.95, run_suffix="CNN1D"),
        _trained_model("logistic_regression", composite_score=0.5, balanced_accuracy=0.7, run_suffix="LR"),
    ], "skipped_models": []}
    seed_variability = [
        {"seed": 137, "training_run_id": "RUN-CNN1D-seed-137", "validation_accuracy": 0.93, "validation_balanced_accuracy": 0.94},
        {"seed": 2024, "training_run_id": "RUN-CNN1D-seed-2024", "validation_accuracy": 0.94, "validation_balanced_accuracy": 0.95},
    ]
    studio = _StubStudioRepository(training_result, seed_variability=seed_variability)

    result = run_rq2_benchmark(studio_repository=studio, sci_repository=repo, paper_run_id="RUN-1", dataset_id="DS1", dataset_version="1.0.0")

    assert studio.seed_variability_calls == ["RUN-CNN1D"]  # only the PRIMARY branch's training_run_id
    by_branch = {b["branch"]: b for b in result["rq2_report"]["branches"]}
    assert by_branch["raw_iq"]["analysis_role"] == "PRIMARY"
    assert by_branch["raw_iq"]["seed_variability"] == seed_variability
    assert "seed_variability" not in by_branch["engineered_rf"]  # UNSELECTED -- never fabricated


def test_run_rq2_benchmark_passes_all_model_types_by_default(tmp_path):
    repo = _repo(tmp_path)
    _write_split(repo, dataset_id="DS1", dataset_version="1.0.0", scientific_task="TARGET_VS_BACKGROUND")
    studio = _StubStudioRepository({"trained_models": [_trained_model("cnn1d", composite_score=0.9, balanced_accuracy=0.95, run_suffix="X")], "skipped_models": []})
    run_rq2_benchmark(studio_repository=studio, sci_repository=repo, paper_run_id="RUN-1", dataset_id="DS1", dataset_version="1.0.0")
    assert set(studio.calls[0]["model_types"]) == {"logistic_regression", "svm_rbf", "random_forest", "cnn1d", "cnn2d", "frozen_morphological_baseline"}
