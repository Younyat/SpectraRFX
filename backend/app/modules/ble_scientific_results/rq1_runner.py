"""Minimal orchestration for RQ1 (acquisition-dependence diagnostic) --
wires three already-existing, untouched functions together. No new formula,
split rule, or statistic; see each function's own module for the real
science this file only calls:
  SplitBuilder.build_rq1_dependence_diagnostic()
    (app/modules/ble_rffi_studio/quality/split_builder.py)
  evaluate_rq1_acquisition_dependence()
    (app/modules/ble_rffi_studio/evaluation/rq1_acquisition_dependence.py)
  ScientificResultsRepository.persist_rq1_acquisition_dependence_report()
    (api/scientific_results_repository.py)

This module exists because nothing in the codebase called the first two
together before now (confirmed: build_rq1_dependence_diagnostic had zero
real callers outside its own definition) -- RQ1 had the calculation but no
orchestration. What this file adds:

  1. Builds the RQ1 diagnostic split (train=first half / validation=second
     half of the SAME session, deliberately capture-dependent -- the whole
     point of RQ1) from the already-frozen CONFIRMATORY split.
  2. Trains exactly ONE model -- the SAME model_type StudioRepository.
     prepare_and_train() already recommended from VALIDATION on the normal
     split -- directly against the diagnostic split's in-memory
     assignments, via TrainingService.run_baseline/run_cnn/
     run_frozen_reference_baseline: the SAME functions StudioRepository.
     run_training() calls internally, just supplied the diagnostic split
     object directly instead of one fetched by
     (dataset_id, dataset_version, scientific_task) -- fetching by that key
     would silently return (and persisting the diagnostic split under it
     would silently overwrite) the real CONFIRMATORY split, since
     SplitManifest storage is keyed by that triple, not by split_purpose.
  3. Reuses the ALREADY-COMPUTED VALIDATION evaluation of the recommended
     training run as capture_report -- no retraining, no re-evaluation of
     that model.
  4. Combines both into evaluate_rq1_acquisition_dependence() and persists
     via persist_rq1_acquisition_dependence_report(), untouched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.modules.ble_rffi_studio.api import studio_repository as studio_repository_module
from app.modules.ble_rffi_studio.contracts.training import TrainingRun
from app.modules.ble_rffi_studio.evaluation import SplitEvaluationReport, evaluate_rq1_acquisition_dependence
from app.modules.ble_rffi_studio.preprocessing import resolve_preprocessing_profile
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

ProgressHook = Callable[[str, float, str], None] | None

_REPRESENTATION_BY_MODEL = {
    "logistic_regression": "feature_vector-v1", "svm_rbf": "feature_vector-v1", "random_forest": "feature_vector-v1",
    "cnn1d": "raw_iq-v1", "cnn2d": "spectrogram-v1", "frozen_morphological_baseline": "morphological_coarse_tf-v1",
}


class Rq1RunnerError(Exception):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _train_on_split(studio_repository: Any, training_run: TrainingRun, split: Any, examples_by_id: dict) -> None:
    """Same real training call StudioRepository.run_training() makes
    internally (TrainingService.run_baseline/run_cnn/
    run_frozen_reference_baseline, then _persist_training_artifacts) --
    reused verbatim, just given the diagnostic split object directly rather
    than letting run_training() re-fetch a split by
    (dataset_id, dataset_version, scientific_task), which would resolve to
    the real CONFIRMATORY split instead."""
    run_dir = studio_repository.training_dir / training_run.training_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    from app.infrastructure.ble.capture.ble_offline_replay import write_json  # same helper run_training() uses
    write_json(run_dir / "training_run.json", training_run.model_dump(mode="json"))

    dataset = studio_repository._require_dataset(training_run.dataset_id, training_run.dataset_version)
    iq_paths = studio_repository.capture_iq_paths_for(dataset.captures)
    service = TrainingService(iq_paths, resolve_preprocessing_profile(training_run.base_preprocessing_profile_id))
    # RQ1's diagnostic split is intentionally capture-leaking by design (see
    # build_rq1_dependence_diagnostic's docstring) -- this opt-in is scoped by
    # TrainingService itself to split_purpose=RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC
    # only, so it cannot loosen the leakage gate for any other real split.
    if training_run.model_type in studio_repository_module._TORCH_MODEL_TYPES:
        artifacts = service.run_cnn(training_run=training_run, split=split, examples_by_id=examples_by_id, allow_intentional_diagnostic_leakage=True)
    elif training_run.model_type == "frozen_morphological_baseline":
        artifacts = service.run_frozen_reference_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id, allow_intentional_diagnostic_leakage=True)
    else:
        artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id, allow_intentional_diagnostic_leakage=True)
    studio_repository._persist_training_artifacts(run_dir, artifacts)


def run_rq1_acquisition_dependence(
    *, studio_repository: Any, sci_repository: Any, paper_run_id: str, dataset_id: str, dataset_version: str,
    recommended_training_run_id: str, scientific_task: str = "TARGET_VS_BACKGROUND", progress: ProgressHook = None,
) -> dict[str, Any]:
    if studio_repository is None:
        raise Rq1RunnerError("NO_STUDIO_REPOSITORY_CONFIGURED:RQ1 needs a real StudioRepository")

    def report(stage: str, fraction: float, message: str) -> None:
        if progress:
            progress(stage, fraction, message)

    report("LOAD", 0.05, "Loading dataset, confirmatory split, and recommended training run")
    dataset = studio_repository._require_dataset(dataset_id, dataset_version)
    examples = studio_repository._dataset_examples(dataset)
    examples_by_id = {e.example_id: e for e in examples}
    confirmatory_split = studio_repository.get_split(dataset_id, dataset_version, scientific_task)
    if confirmatory_split is None or confirmatory_split.split_status != "READY":
        raise Rq1RunnerError(f"CONFIRMATORY_SPLIT_NOT_READY:{dataset_id}:{dataset_version}:{scientific_task}")

    recommended_run = studio_repository.get_training_run(recommended_training_run_id)
    if recommended_run is None:
        raise Rq1RunnerError(f"RECOMMENDED_TRAINING_RUN_NOT_FOUND:{recommended_training_run_id}")
    model_type = recommended_run["model_type"]

    report("BUILD_DIAGNOSTIC_SPLIT", 0.15, "Building the RQ1 acquisition-dependence diagnostic split")
    builder = SplitBuilder()
    diagnostic_split = builder.build_rq1_dependence_diagnostic(
        dataset=dataset, examples=examples, scientific_task=scientific_task,
        confirmatory_split=confirmatory_split, created_at=_utc_now(),
    )
    if diagnostic_split.split_status != "READY":
        raise Rq1RunnerError(f"RQ1_DIAGNOSTIC_SPLIT_NOT_FEASIBLE:{diagnostic_split.infeasibility_reason}")

    report("TRAIN_DIAGNOSTIC_MODEL", 0.3, f"Training {model_type} on the RQ1 diagnostic split (for ba_window)")
    diag_run_id = f"RQ1DIAG-{dataset_id}-{model_type}-{uuid.uuid4().hex[:8]}"
    diag_training_run = TrainingRun(
        training_run_id=diag_run_id, project_id=dataset.project_id, campaign_id=f"RQ1-DIAGNOSTIC-{dataset_id}",
        dataset_id=dataset_id, dataset_version=dataset_version, dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "",
        split_manifest_sha256=diagnostic_split.split_manifest_sha256 or "", scientific_task=scientific_task, model_type=model_type,
        data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
        base_preprocessing_profile_id="base-v1", representation_profile_id=_REPRESENTATION_BY_MODEL[model_type],
        random_seed=studio_repository_module.FROZEN_TRAINING_SEEDS[0],
    )
    _train_on_split(studio_repository, diag_training_run, diagnostic_split, examples_by_id)

    report("EVALUATE_WINDOW", 0.6, "Evaluating the diagnostic model's VALIDATION role (ba_window)")
    window_eval = studio_repository.evaluate_training_run(diag_run_id, include_test=False)
    window_report = SplitEvaluationReport(**window_eval["evaluation_report"]["VALIDATION"])

    report("REUSE_CAPTURE_REPORT", 0.7, "Reusing the already-computed VALIDATION evaluation of the recommended model (no retraining)")
    capture_eval = studio_repository.evaluate_training_run(recommended_training_run_id, include_test=False)
    capture_report = SplitEvaluationReport(**capture_eval["evaluation_report"]["VALIDATION"])

    report("COMPUTE", 0.85, "evaluate_rq1_acquisition_dependence()")
    rq1_result = evaluate_rq1_acquisition_dependence(
        scientific_task=scientific_task, window_report=window_report, capture_report=capture_report, future_report=None,
    )

    # Real, session-clustered bootstrap CI on ba_capture -- the confirmatory
    # (capture-disjoint) number, computed against the recommended model's
    # ALREADY-PERSISTED VALIDATION predictions (no retraining, same
    # zero-new-computation rule this whole module follows). Never computed
    # for ba_window: that domain is intentionally capture-leaking by design
    # (see build_rq1_dependence_diagnostic's own docstring), so a CI on it
    # would describe uncertainty of a deliberately non-confirmatory number.
    report("UNCERTAINTY", 0.9, "Computing bootstrap confidence intervals on ba_capture, ba_window, and delta_dependence")
    # Methodological-audit fix (2026-08-22, item 3): switched from
    # bootstrap_balanced_accuracy_ci/_delta_ci to the class-stratified
    # siblings -- RQ1's own BA is defined as mean recall over the 4 fixed
    # physical classes, so a resample that (by chance) draws zero sessions
    # from one class must never silently redefine BA over only the classes
    # still present. Stratifying within each true class (session-clustered,
    # same resampling unit as before) removes that failure mode entirely.
    # bootstrap_balanced_accuracy_ci/_delta_ci themselves stay unchanged for
    # other real callers (RQ2 branch CIs, etc.) not audited for this issue.
    ba_capture_ci = studio_repository.bootstrap_balanced_accuracy_ci_stratified_by_class(recommended_training_run_id, split="VALIDATION")
    # RQ1 completion pass (2026-08-17): ba_window now ALSO gets its own real
    # CI -- ba_window is a deliberately leakage-optimistic diagnostic, not a
    # confirmatory estimator, but its own resampling uncertainty is still a
    # real, reportable quantity (never fabricated, never omitted just
    # because the point estimate itself is intentionally optimistic).
    ba_window_ci = studio_repository.bootstrap_balanced_accuracy_ci_stratified_by_class(diag_run_id, split="VALIDATION")
    # delta_dependence's CI comes from independently, class-stratified
    # resampling both domains and differencing per replicate -- NEVER a
    # "paired" bootstrap (there is no physical pairing between the
    # capture-dependent domain's sessions and the capture-disjoint domain's
    # sessions -- see independent_domain_bootstrap_delta_ci's own
    # docstring), and never subtracting the two marginal CIs above (see the
    # same docstring for why that would be invalid regardless).
    delta_dependence_ci = studio_repository.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(
        diag_run_id, recommended_training_run_id, split_a="VALIDATION", split_b="VALIDATION",
    )
    uncertainty_ci = {
        "ba_capture_ci": {"ci_low": ba_capture_ci["ci_low"], "ci_high": ba_capture_ci["ci_high"]} if ba_capture_ci else None,
        "ba_window_ci": {"ci_low": ba_window_ci["ci_low"], "ci_high": ba_window_ci["ci_high"]} if ba_window_ci else None,
        "delta_dependence_ci": {
            "ci_low": delta_dependence_ci["ci_low"], "ci_high": delta_dependence_ci["ci_high"],
            "method": "independent_domain_bootstrap_delta_ci (independent, class-stratified resample of each domain, "
                      "per-replicate difference; NOT paired -- no physical pairing exists between capture-dependent "
                      "and capture-disjoint sessions; NOT ci_window - ci_capture)",
        } if delta_dependence_ci else None,
    } if (ba_capture_ci or ba_window_ci or delta_dependence_ci) else None

    # Real cross-reference against the SAME already-computed decision-window
    # counts coverage_analysis_report.json carries (2026-08-17 investigation
    # finding) -- reused verbatim, never a second aggregation. None when
    # Coverage Analysis has not been run yet for this paper_run_id.
    coverage_report = sci_repository.get_coverage_analysis_report(paper_run_id)
    decision_window_cross_reference = None
    if coverage_report:
        window_level_by_branch = coverage_report.get("window_level_evaluation") or {}
        # PRIMARY branch's own decision-window evaluation when present, else
        # whichever real branch was evaluated -- never assumes a fixed
        # branch name.
        branch_evaluation = window_level_by_branch.get("engineered_rf") or next(iter(window_level_by_branch.values()), {})
        by_domain = branch_evaluation.get("by_evaluation_domain") or {}
        if by_domain:
            decision_window_cross_reference = {
                "source_artifact": "06_statistics/coverage_analysis_report.json", "window_duration_s": coverage_report.get("window_duration_s"),
                "note": "RQ1's own ba_window/ba_capture are ExampleRecord-level (see evaluation_unit above) -- these decision-window counts are a SEPARATE, real cross-reference, not RQ1's evaluation unit.",
                "by_evaluation_domain": {domain: {"n_decision_windows": data.get("n_comparable")} for domain, data in by_domain.items()},
            }

    report("PERSIST", 0.95, "persist_rq1_acquisition_dependence_report()")
    study_status = sci_repository.get_study_status()
    # Real bundle lookup -- model_bundle_sha256 must be the exported model
    # bundle's own hash, never the dataset's hash (a real mislabeling bug
    # found and fixed here 2026-08-17); None, honestly, when no bundle was
    # ever exported for this training run rather than a wrong value.
    bundle_info = sci_repository._find_bundle_for_training_run(recommended_training_run_id)
    persisted = sci_repository.persist_rq1_acquisition_dependence_report(
        paper_run_id=paper_run_id, protocol_id=study_status.get("protocol_id"), protocol_version=study_status.get("protocol_version"),
        contract_sha256=study_status.get("contract_sha256"), rq1_report=rq1_result,
        model_bundle_id=(bundle_info or {}).get("bundle_id"), model_bundle_sha256=(bundle_info or {}).get("bundle_sha256"),
        dataset_manifest_sha256=recommended_run.get("dataset_manifest_sha256"),
        confirmatory_split_manifest_id=f"{dataset_id}__{dataset_version}__{scientific_task}",
        confirmatory_split_manifest_sha256=confirmatory_split.split_manifest_sha256 or "",
        diagnostic_split_manifest_id=diag_run_id, diagnostic_split_manifest_sha256=diagnostic_split.split_manifest_sha256 or "",
        source_evaluation_domains={
            "window": "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC:VALIDATION", "capture": f"{scientific_task}:VALIDATION",
        },
        uncertainty_ci=uncertainty_ci,
        coverage=None, confusion_matrix_capture=capture_report.confusion_matrix, confusion_matrix_future=None, per_unit_recall=None,
        evaluation_unit="EXAMPLE_RECORD", decision_window_cross_reference=decision_window_cross_reference,
    )
    return {"rq1_report": persisted, "diagnostic_training_run_id": diag_run_id}
