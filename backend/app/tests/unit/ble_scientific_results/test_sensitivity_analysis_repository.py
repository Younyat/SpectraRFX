"""ScientificResultsRepository.run_sensitivity_analysis (2026-08-12,
Scientific Closure pass) -- real orchestration over a stub
studio_repository (never real training in this test; real training is
covered separately by test_offset_retaining_sensitivity.py).
"""
from __future__ import annotations

import json

import pytest

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_run_and_rq2_report(tmp_path, *, seed_variability=None) -> None:
    run_dir = tmp_path / "sci_results" / "RUN-1"
    (run_dir / "06_statistics").mkdir(parents=True)
    branch = {
        "branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION",
        "model_bundle_id": "BUNDLE-PRIMARY", "training_run_id": "TRAIN-RUN-1", "balanced_accuracy": 0.8,
    }
    if seed_variability is not None:
        branch["seed_variability"] = seed_variability
    (run_dir / "06_statistics" / "rq2_representation_comparison_report.json").write_text(json.dumps({"branches": [branch]}), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")


class _StubStudioRepository:
    def __init__(self, predictions, label_classes, offset_result) -> None:
        self._predictions = predictions
        self._label_classes = label_classes
        self._offset_result = offset_result
        self.offset_retaining_calls: list[str] = []

    def get_training_run_predictions(self, training_run_id, split):
        return self._predictions if split == "VALIDATION" else None

    def get_training_run(self, training_run_id):
        return {"label_classes": self._label_classes}

    def train_offset_retaining_sensitivity(self, *, training_run_id, progress=None):
        self.offset_retaining_calls.append(training_run_id)
        return self._offset_result


_PREDICTIONS = [
    {"example_id": "e1", "true_label": "UNIT-A", "predicted_label": "UNIT-A", "physical_unit_id": "UNIT-A"},
    {"example_id": "e2", "true_label": "UNIT-A", "predicted_label": "UNIT-B", "physical_unit_id": "UNIT-A"},
    {"example_id": "e3", "true_label": "UNIT-B", "predicted_label": "UNIT-B", "physical_unit_id": "UNIT-B"},
    {"example_id": "e4", "true_label": "UNIT-B", "predicted_label": "UNIT-B", "physical_unit_id": "UNIT-B"},
]


def test_run_sensitivity_analysis_persists_lodo_and_offset_retaining_and_reuses_seed_variability(tmp_path):
    seed_variability = [{"seed": 137, "training_run_id": "TRAIN-RUN-1-seed-137", "validation_accuracy": 0.79, "validation_balanced_accuracy": 0.78}]
    _write_run_and_rq2_report(tmp_path, seed_variability=seed_variability)
    repo = _repo(tmp_path)
    studio = _StubStudioRepository(
        _PREDICTIONS, ["UNIT-A", "UNIT-B"],
        {"training_run_id": "TRAIN-RUN-1-offset-retaining", "base_preprocessing_profile_id": "offset-retaining-v1", "validation_balanced_accuracy": 0.7, "coverage": None},
    )

    as_dict = repo.run_sensitivity_analysis(paper_run_id="RUN-1", studio_repository=studio)

    assert studio.offset_retaining_calls == ["TRAIN-RUN-1"]
    assert as_dict["primary"]["balanced_accuracy"] == 0.8
    lodo_by_unit = {r["omitted_physical_unit"]: r for r in as_dict["enrolled_population_class_exclusion_sensitivity"]["rows"]}
    assert set(lodo_by_unit.keys()) == {"UNIT-A", "UNIT-B"}
    assert lodo_by_unit["UNIT-A"]["delta_vs_full_set"] is not None
    assert as_dict["offset_retaining"]["analysis_role"] == "OFFSET_RETAINING_SENSITIVITY"
    assert as_dict["offset_retaining"]["estimate"] == 0.7
    assert as_dict["offset_retaining"]["delta_vs_primary"] == pytest.approx(0.7 - 0.8)
    assert as_dict["seed_variability"]["analysis_role"] == "SENSITIVITY"
    assert as_dict["seed_variability"]["rows"] == seed_variability  # REUSED verbatim, never recomputed

    reloaded = repo.get_sensitivity_report("RUN-1")
    assert reloaded == as_dict


def test_run_sensitivity_analysis_raises_without_a_studio_repository(tmp_path):
    _write_run_and_rq2_report(tmp_path)
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="NO_STUDIO_REPOSITORY_CONFIGURED"):
        repo.run_sensitivity_analysis(paper_run_id="RUN-1", studio_repository=None)


def test_run_sensitivity_analysis_raises_without_a_frozen_primary_rq2_branch(tmp_path):
    repo = _repo(tmp_path)
    run_dir = tmp_path / "sci_results" / "RUN-1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="NO_FROZEN_PRIMARY_RQ2_BRANCH"):
        repo.run_sensitivity_analysis(paper_run_id="RUN-1", studio_repository=_StubStudioRepository([], [], {}))


def test_run_sensitivity_analysis_omits_seed_variability_when_rq2_never_computed_it(tmp_path):
    _write_run_and_rq2_report(tmp_path, seed_variability=None)
    repo = _repo(tmp_path)
    studio = _StubStudioRepository(
        _PREDICTIONS, ["UNIT-A", "UNIT-B"],
        {"training_run_id": "TRAIN-RUN-1-offset-retaining", "base_preprocessing_profile_id": "offset-retaining-v1", "validation_balanced_accuracy": 0.7, "coverage": None},
    )
    as_dict = repo.run_sensitivity_analysis(paper_run_id="RUN-1", studio_repository=studio)
    assert as_dict["seed_variability"] is None
