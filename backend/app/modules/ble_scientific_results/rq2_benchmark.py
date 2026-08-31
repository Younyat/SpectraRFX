"""Study Control Center, phase 08 (2026-08-11): RUN RQ2 VALIDATION BENCHMARK.
Drives the SAME real training orchestration `StudioRepository.
train_selected_models()` already provides (VALIDATION-only, TEST never
opened) -- computes NO new science, only maps its real per-model VALIDATION
results onto the 4 real RQ2 branches (`_MODEL_TYPE_TO_RQ2_BRANCH`) and picks
PRIMARY via the already-existing `select_primary_rq2_branch_from_validation`
rule, then calls the untouched `persist_rq2_representation_comparison_report`.

RQ2 benchmark legitimately runs BEFORE protocol freeze (its result informs
`AnalysisContract.rq2_primary_branch`, which is frozen afterwards) -- so
protocol_id/protocol_version/contract_sha256 are genuinely optional here,
not a placeholder.
"""
from __future__ import annotations

from typing import Any, Callable

from app.modules.ble_rffi_studio.training.model_selector import (
    _MODEL_TYPE_TO_RQ2_BRANCH,
    select_primary_rq2_branch_from_validation,
)

ProgressHook = Callable[[str, float, str], None] | None

ALL_RQ2_MODEL_TYPES = tuple(_MODEL_TYPE_TO_RQ2_BRANCH.keys())


class Rq2BenchmarkError(Exception):
    pass


def map_training_result_to_rq2_branches(training_result: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Pure transform: `training_result` is the real dict
    `train_selected_models()`/`prepare_and_train()` return (with the FULL,
    un-stripped `trained_models[i]` entries -- `evaluation`/`score`, not the
    job-summary-stripped version). One entry per real RQ2 branch that had at
    least one successfully trained model_type; when 2+ model_types map to
    the same branch (only true for engineered_rf's 3 candidates), the one
    with the highest real VALIDATION composite_score represents that branch
    -- a real, deterministic, disclosed tie-break, never an average or a
    guess. Every optional metric a model's evaluation genuinely lacks stays
    absent, never a fabricated 0.

    Returns (branch_results, selection_rule) -- selection_rule is the real
    descriptive string select_primary_rq2_branch_from_validation() already
    computes (why the PRIMARY branch was chosen, VALIDATION-only), so the
    persisted report can state its own selection provenance instead of that
    text living only in code/docstrings. None when no branch trained at all
    (no primary to explain)."""
    trained = training_result.get("trained_models") or []
    best_by_branch: dict[str, dict[str, Any]] = {}
    for entry in trained:
        model_type = entry["model_type"]
        branch = _MODEL_TYPE_TO_RQ2_BRANCH.get(model_type)
        if branch is None:
            continue
        composite = entry["score"]["composite_score"]
        if branch not in best_by_branch or composite > best_by_branch[branch]["score"]["composite_score"]:
            best_by_branch[branch] = entry

    if not best_by_branch:
        return [], None

    composite_scores = {entry["model_type"]: entry["score"]["composite_score"] for entry in best_by_branch.values()}
    primary_branch, rule = select_primary_rq2_branch_from_validation(composite_scores)

    branch_results: list[dict[str, Any]] = []
    for branch, entry in sorted(best_by_branch.items()):
        validation_report = entry["evaluation"]["evaluation_report"].get("VALIDATION")
        branch_results.append({
            "branch": branch, "analysis_role": "PRIMARY" if branch == primary_branch else "UNSELECTED",
            "evaluation_domain": "VALIDATION", "model_type": entry["model_type"], "training_run_id": entry["training_run_id"],
            "balanced_accuracy": validation_report.get("balanced_accuracy") if validation_report else None,
            "macro_f1": validation_report.get("macro_f1") if validation_report else None,
            "classwise_recall": validation_report.get("recall_per_class") if validation_report else None,
            "serialized_model_size_bytes": entry["score"].get("model_size_bytes"),
            "inference_latency_ms": entry["score"].get("latency_ms"),
        })
    return branch_results, rule


def run_rq2_benchmark(
    *, studio_repository: Any, sci_repository: Any, paper_run_id: str, dataset_id: str, dataset_version: str,
    scientific_task: str = "TARGET_VS_BACKGROUND", model_types: list[str] | None = None, progress: ProgressHook = None,
) -> dict[str, Any]:
    if studio_repository is None:
        raise Rq2BenchmarkError("NO_STUDIO_REPOSITORY_CONFIGURED:RQ2 benchmark needs a real StudioRepository to run train_selected_models()")
    training_result = studio_repository.train_selected_models(
        dataset_id=dataset_id, dataset_version=dataset_version, model_types=list(model_types or ALL_RQ2_MODEL_TYPES),
        scientific_task=scientific_task, progress=progress,
    )
    if training_result.get("stopped_at"):
        # A real, honest stop (quality gate / infeasible split / no model
        # met acceptance criteria) -- never persist fabricated branch
        # results when training itself did not produce real ones.
        return {"stopped_at": training_result["stopped_at"], "stopped_reason": training_result.get("stopped_reason"), "rq2_report": None}

    branch_results, selection_rule = map_training_result_to_rq2_branches(training_result)
    if not branch_results:
        return {"stopped_at": "no_recognized_rq2_branch", "stopped_reason": "None of the trained model_types map to a known RQ2 branch", "rq2_report": None}

    # Dashboard closure (2026-08-11), Case A: train_seed_variability_analysis
    # is a real, tested, previously-unwired function (re-trains the SAME
    # configuration under each other frozen seed, VALIDATION-only, TEST
    # never opened) -- computed only for the PRIMARY branch (the one the
    # paper actually reports) to keep this job's real compute cost bounded;
    # never fabricated, never computed for a branch that never trained.
    if progress:
        progress("SEED_VARIABILITY", 0.9, "Re-training the PRIMARY branch under the other frozen seeds")
    for entry in branch_results:
        if entry["analysis_role"] == "PRIMARY":
            seed_results = studio_repository.train_seed_variability_analysis(training_run_id=entry["training_run_id"])
            if seed_results:
                entry["seed_variability"] = seed_results

    # Paper-representation pass (2026-08-17): a real, session-clustered
    # bootstrap CI on the SAME balanced_accuracy each branch already
    # reports -- cheap (pure resampling over already-persisted predictions,
    # no retraining) so computed for every branch, not only PRIMARY (unlike
    # seed_variability above, which retrains and stays PRIMARY-only for
    # cost reasons).
    if progress:
        progress("BOOTSTRAP_CI", 0.95, "Computing balanced-accuracy confidence intervals")
    for entry in branch_results:
        ci = studio_repository.bootstrap_balanced_accuracy_ci(entry["training_run_id"], split="VALIDATION")
        if ci:
            entry["balanced_accuracy_ci"] = {"ci_low": ci["ci_low"], "ci_high": ci["ci_high"]}

    split = sci_repository._load_split(dataset_id, dataset_version, scientific_task)
    study_status = sci_repository.get_study_status()
    rq2_report = sci_repository.persist_rq2_representation_comparison_report(
        paper_run_id=paper_run_id, protocol_id=study_status.get("protocol_id"), protocol_version=study_status.get("protocol_version"),
        contract_sha256=study_status.get("contract_sha256"), dataset_id=dataset_id, dataset_version=dataset_version,
        split_manifest_id=f"{dataset_id}__{dataset_version}__{scientific_task}", split_manifest_sha256=split.split_manifest_sha256 or "",
        branch_results=branch_results, selection_rule=selection_rule, selection_domain="VALIDATION",
    )
    return {"stopped_at": None, "stopped_reason": None, "rq2_report": rq2_report, "skipped_models": training_result.get("skipped_models") or []}
