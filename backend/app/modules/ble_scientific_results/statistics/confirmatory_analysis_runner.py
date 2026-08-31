"""Real, callable connection point for the paper's statistical-analysis
plan (2026-08-09 protocol-freeze close-out). Every method below already
existed as a real, tested primitive in this package (or, for leave-one-
device-out, is added alongside this module) -- what was missing was a
single real caller reachable from the actual scientific-analysis path
instead of only from a unit test. See
ScientificResultsRepository.run_confirmatory_statistical_plan for the
production entrypoint that persists this report.

VALIDATION-only by construction: every argument this function accepts is
already-scored VALIDATION data the caller assembled -- there is no
parameter through which TEST/FUTURE_TEST data could flow in, and this
module never touches ScientificResultsRepository.read_group() or any
holdout-gated artifact itself.

Never fabricates a result: any method whose real input isn't supplied is
reported SKIPPED_NO_DATA with the reason, not a placeholder number. As of
this pass, most methods legitimately have no real RQ2/RQ3/RQ4 confirmatory
data yet (0 real PRE/POST pairs, no common RQ2 benchmark run, no RQ4
paired comparison run) -- SKIPPED_NO_DATA is the honest, expected state for
those, not a bug.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .inference import (
    BootstrapCiResult,
    HolmResult,
    NonInferiorityResult,
    PairedContrast,
    StratifiedCrossoverTestResult,
    exact_randomization_test,
    hierarchical_cluster_bootstrap,
    holm_correction,
    non_inferiority_test,
    paired_contrast,
    stratified_crossover_permutation_test,
)
from .metrics import coverage
from .sensitivity import ClassExclusionSensitivityResult, enrolled_population_class_exclusion_sensitivity


@dataclass
class MethodResult:
    status: str  # "EXECUTED" | "SKIPPED_NO_DATA"
    detail: str | None = None
    value: Any = None


@dataclass
class ConfirmatoryStatisticalPlanReport:
    hierarchical_cluster_bootstrap: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    balanced_accuracy: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    macro_f1_and_classwise_recall: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    coverage: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    risk_coverage: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    rq3_within_device_permutation_test: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    rq4_paired_comparison: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    non_inferiority: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    holm_correction: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    enrolled_population_class_exclusion_sensitivity: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))
    fixed_seed_variability: MethodResult = field(default_factory=lambda: MethodResult(status="SKIPPED_NO_DATA"))


def run_confirmatory_statistical_plan(
    *,
    split_evaluation_report: Any = None,  # evaluation.SplitEvaluationReport, VALIDATION only
    session_id_by_example_id: dict[str, str] | None = None,
    predictions: list[dict[str, Any]] | None = None,
    known_classes: Sequence[str] | None = None,
    window_decisions: list[dict[str, Any]] | None = None,
    rq3_device_day_values: dict[str, Sequence[float]] | None = None,
    rq3_device_day_is_reset: dict[str, Sequence[bool]] | None = None,
    rq4_scores_a: Sequence[float] | None = None,
    rq4_scores_b: Sequence[float] | None = None,
    non_inferiority_differences: Sequence[float] | None = None,
    non_inferiority_margin: float | None = None,
    device_id_by_example_id: dict[str, str] | None = None,
    seed_variability_results: list[dict[str, Any]] | None = None,
) -> ConfirmatoryStatisticalPlanReport:
    report = ConfirmatoryStatisticalPlanReport()
    p_values_for_holm: list[float] = []

    if split_evaluation_report is not None:
        report.balanced_accuracy = MethodResult(status="EXECUTED", value=split_evaluation_report.balanced_accuracy)
        report.macro_f1_and_classwise_recall = MethodResult(
            status="EXECUTED", value={"macro_f1": split_evaluation_report.macro_f1, "recall_per_class": split_evaluation_report.recall_per_class},
        )
        report.risk_coverage = MethodResult(status="EXECUTED", value=split_evaluation_report.risk_coverage)
    else:
        report.balanced_accuracy.detail = "no split_evaluation_report supplied"
        report.macro_f1_and_classwise_recall.detail = "no split_evaluation_report supplied"
        report.risk_coverage.detail = "no split_evaluation_report supplied"

    if predictions and known_classes and session_id_by_example_id:
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        by_session: dict[str, list[float]] = {}
        for prediction in comparable:
            session_id = session_id_by_example_id.get(prediction["example_id"])
            if session_id is None:
                continue
            by_session.setdefault(session_id, []).append(1.0 if prediction["predicted_label"] == prediction["true_label"] else 0.0)
        if by_session:
            result: BootstrapCiResult = hierarchical_cluster_bootstrap(list(by_session.values()), statistic=lambda values: sum(values) / len(values))
            report.hierarchical_cluster_bootstrap = MethodResult(status="EXECUTED", value=result)
        else:
            report.hierarchical_cluster_bootstrap.detail = "no comparable prediction maps to a real session_id"
    else:
        report.hierarchical_cluster_bootstrap.detail = "predictions/known_classes/session_id_by_example_id not supplied"

    if window_decisions:
        report.coverage = MethodResult(status="EXECUTED", value=coverage(len(window_decisions), sum(1 for d in window_decisions if d["final_decision"] == "INSUFFICIENT_EVIDENCE")))
    else:
        report.coverage.detail = "no window_decisions supplied"

    if rq3_device_day_values and rq3_device_day_is_reset:
        rq3_result: StratifiedCrossoverTestResult = stratified_crossover_permutation_test(rq3_device_day_values, rq3_device_day_is_reset)
        report.rq3_within_device_permutation_test = MethodResult(status="EXECUTED", value=rq3_result)
        p_values_for_holm.append(rq3_result.p_value)
    else:
        report.rq3_within_device_permutation_test.detail = "no real RQ3 device/day paired scores supplied (0 real PRE/POST pairs as of this pass)"

    if rq4_scores_a and rq4_scores_b:
        contrast: PairedContrast = paired_contrast(rq4_scores_a, rq4_scores_b)
        randomization = exact_randomization_test(contrast.differences)
        report.rq4_paired_comparison = MethodResult(status="EXECUTED", value={"contrast": contrast, "randomization_test": randomization})
        p_values_for_holm.append(randomization.p_value)
    else:
        report.rq4_paired_comparison.detail = "no real per-device FULL_BURST/ADVA_EXCLUDED/PRE_PDU paired scores supplied"

    if non_inferiority_differences and non_inferiority_margin is not None:
        ni_result: NonInferiorityResult = non_inferiority_test(non_inferiority_differences, margin=non_inferiority_margin)
        report.non_inferiority = MethodResult(status="EXECUTED", value=ni_result)
    else:
        report.non_inferiority.detail = "non_inferiority_differences and/or non_inferiority_margin not supplied"

    if p_values_for_holm:
        holm_result: HolmResult = holm_correction(p_values_for_holm)
        report.holm_correction = MethodResult(status="EXECUTED", value=holm_result)
    else:
        report.holm_correction.detail = "no real p-values produced by the tests above to correct"

    if predictions and device_id_by_example_id and known_classes:
        class_exclusion_results: list[ClassExclusionSensitivityResult] = enrolled_population_class_exclusion_sensitivity(predictions, device_id_by_example_id, known_classes)
        if class_exclusion_results:
            report.enrolled_population_class_exclusion_sensitivity = MethodResult(status="EXECUTED", value=class_exclusion_results)
        else:
            report.enrolled_population_class_exclusion_sensitivity.detail = "no prediction maps to a known device_id"
    else:
        report.enrolled_population_class_exclusion_sensitivity.detail = "predictions/device_id_by_example_id/known_classes not supplied"

    if seed_variability_results:
        report.fixed_seed_variability = MethodResult(status="EXECUTED", value=seed_variability_results)
    else:
        report.fixed_seed_variability.detail = "no train_seed_variability_analysis() results supplied (retraining is not triggered implicitly by this report)"

    return report


def confirmatory_statistical_plan_to_dict(report: ConfirmatoryStatisticalPlanReport) -> dict[str, Any]:
    def _method(result: MethodResult) -> dict[str, Any]:
        # Serialization-completeness correction (2026-08-12, RQ4 closure):
        # _dataclass_or_value already recurses correctly through
        # dataclass/dict/list/tuple/plain values -- the old hand-rolled
        # gating above never routed a DICT-shaped value (e.g.
        # rq4_paired_comparison's {"contrast": PairedContrast(...),
        # "randomization_test": ...}) through it at all, so any dataclass
        # nested inside a dict value was left unconverted and broke
        # json.dump. Invisible until now because no real caller had ever
        # fed real rq4_scores_a/rq4_scores_b through this path.
        return {"status": result.status, "detail": result.detail, "value": _dataclass_or_value(result.value)}

    return {
        "hierarchical_cluster_bootstrap": _method(report.hierarchical_cluster_bootstrap),
        "balanced_accuracy": _method(report.balanced_accuracy),
        "macro_f1_and_classwise_recall": _method(report.macro_f1_and_classwise_recall),
        "coverage": _method(report.coverage),
        "risk_coverage": _method(report.risk_coverage),
        "rq3_within_device_permutation_test": _method(report.rq3_within_device_permutation_test),
        "rq4_paired_comparison": _method(report.rq4_paired_comparison),
        "non_inferiority": _method(report.non_inferiority),
        "holm_correction": _method(report.holm_correction),
        "enrolled_population_class_exclusion_sensitivity": _method(report.enrolled_population_class_exclusion_sensitivity),
        "fixed_seed_variability": _method(report.fixed_seed_variability),
    }


def _dataclass_or_value(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {k: _dataclass_or_value(getattr(value, k)) for k in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {k: _dataclass_or_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dataclass_or_value(v) for v in value]
    return value
