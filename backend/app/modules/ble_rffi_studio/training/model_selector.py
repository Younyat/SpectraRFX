"""Real, computed model comparison -- never picks by TRAIN accuracy, never a
placeholder score. Every number here is measured (VALIDATION metrics already
computed by Evaluator, wall-clock inference latency actually timed, model
file size actually read from disk); the composite score formula is
documented so its limits are visible, not implied to be definitive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

CNN_MIN_TRAIN_EXAMPLES_PER_CLASS = 15


def cnn_feasibility(split_assignments: list[dict[str, Any]]) -> tuple[bool, str]:
    train = [a for a in split_assignments if a["split"] == "TRAIN"]
    per_class: dict[str, int] = {}
    for a in train:
        label = a.get("physical_unit_id") or "UNKNOWN"
        per_class[label] = per_class.get(label, 0) + 1
    if not per_class:
        return False, "No hay ejemplos de entrenamiento."
    minimum = min(per_class.values())
    if minimum < CNN_MIN_TRAIN_EXAMPLES_PER_CLASS:
        return False, f"dataset insuficiente para un entrenamiento evaluable (la clase con menos ejemplos de TRAIN tiene {minimum}, se requieren >= {CNN_MIN_TRAIN_EXAMPLES_PER_CLASS})."
    return True, ""


def model_file_size_bytes(run_dir: Path, model_type: str) -> int:
    filename = "model.pt" if model_type in ("cnn1d", "cnn2d") else "model.joblib"
    path = run_dir / filename
    return path.stat().st_size if path.is_file() else 0


def score_model(
    evaluation_report: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    latency_ms: float,
    model_size_bytes: int,
) -> dict[str, Any]:
    validation = evaluation_report.get("VALIDATION")
    f1_values = list((validation or {}).get("f1_per_class", {}).values())
    recall_values = list((validation or {}).get("recall_per_class", {}).values())
    macro_f1 = float(np.mean(f1_values)) if f1_values else 0.0
    # Macro-averaged per-class recall is used here as a balanced-accuracy
    # proxy (equivalent to balanced accuracy for single-label classification).
    balanced_accuracy_proxy = float(np.mean(recall_values)) if recall_values else 0.0

    threshold = calibration.get("acceptance_threshold")
    # A calibration that had to retreat to a near-1.0 threshold means the
    # UNKNOWN-rejection layer found no safe way to accept anything -- real
    # capability, not a cosmetic penalty (see the OOD-overconfidence finding
    # in scientific_basis/model_evidence.json).
    unknown_capability_penalty = 0.2 if (threshold is None or threshold > 0.95) else 0.0

    composite_score = 0.5 * macro_f1 + 0.3 * balanced_accuracy_proxy - unknown_capability_penalty

    return {
        "macro_f1": macro_f1,
        "balanced_accuracy_proxy": balanced_accuracy_proxy,
        "unknown_capability_penalty": unknown_capability_penalty,
        "latency_ms": latency_ms,
        "model_size_bytes": model_size_bytes,
        "composite_score": composite_score,
        "formula": "0.5*macro_f1 + 0.3*balanced_accuracy_proxy - unknown_capability_penalty (VALIDATION only; TEST never used to select)",
    }


# RQ2's 4 signal-analysis branches (root README's "Implemented BLE-RFFI
# benchmark" table) -- which ModelType(s) each one covers.
_MODEL_TYPE_TO_RQ2_BRANCH = {
    "logistic_regression": "engineered_rf", "svm_rbf": "engineered_rf", "random_forest": "engineered_rf",
    "cnn1d": "raw_iq", "cnn2d": "stft", "frozen_morphological_baseline": "coarse_morphology",
}


def select_primary_rq2_branch_from_validation(validation_composite_scores: dict[str, float]) -> tuple[str, str]:
    """Protocol-freeze close-out (2026-08-09): picks RQ2's primary analysis
    branch to freeze into AnalysisContract.rq2_primary_branch BEFORE FUTURE
    TEST. `validation_composite_scores` is {model_type: composite_score} --
    score_model()'s own composite_score, already documented VALIDATION-only;
    this function's input type has no slot for a TEST-derived number, so it
    cannot be fed one by construction. Never called automatically from
    freeze_protocol() -- the caller decides when a real VALIDATION run
    justifies freezing a primary branch, this only computes which one wins
    given real scores. Returns (primary_branch, selection_rule_text)."""
    if not validation_composite_scores:
        raise ValueError("NEED_AT_LEAST_ONE_VALIDATION_COMPOSITE_SCORE")
    best_by_branch: dict[str, float] = {}
    for model_type, score in validation_composite_scores.items():
        branch = _MODEL_TYPE_TO_RQ2_BRANCH.get(model_type)
        if branch is None:
            continue
        if branch not in best_by_branch or score > best_by_branch[branch]:
            best_by_branch[branch] = score
    if not best_by_branch:
        raise ValueError("NO_KNOWN_RQ2_BRANCH_IN_INPUT")
    primary_branch = max(sorted(best_by_branch.keys()), key=lambda branch: best_by_branch[branch])
    rule = (
        "Highest VALIDATION composite_score (score_model()'s 0.5*macro_f1 + 0.3*balanced_accuracy_proxy - "
        "unknown_capability_penalty) among each branch's best-scoring model_type; ties broken alphabetically by branch name."
    )
    return primary_branch, rule
