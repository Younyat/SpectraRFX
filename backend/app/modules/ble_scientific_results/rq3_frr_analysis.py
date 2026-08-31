"""RQ3 real FRR (False Rejection Rate) pre/post analysis (2026-08-11) --
Scientific Dashboard Closure audit finding: RQ3's pair CONSTRUCTION was
real (`build_pre_post_pairs`), but the actual scientific estimand (FRR_pre,
FRR_post, D = FRR_post - FRR_pre) had no real producer. The frozen
inference pipeline that computes it (OfflineInferenceService.
run_decision_windows() -- the SAME frozen primary-branch bundle,
preprocessing, decision-window rule, minimum-evidence rule, and calibrated
operating threshold RQ1/RQ2 already use) was real and callable end-to-end,
just never called for RQ3. This module adds exactly that glue -- no new
methodology, no new metric:

- FRR follows `statistics/metrics.py::far_frr()`'s existing, already-tested
  ISO/IEC 19795-1 definition (FRR = false rejects / target trials).
- Ground truth follows the SAME single-source-of-truth convention
  `quality/split_builder.py::train_label_for()` already uses for every
  non-TARGET_VS_BACKGROUND scientific_task: the class label IS the real,
  declared `physical_unit_id`. A PRE/POST capture's every decision window
  genuinely belongs to its own declared physical_unit_id by construction
  of the RESET/CONTROL protocol (the unit is physically isolated during
  acquisition) -- so `y_true_is_target` is always `[True, ...]`, and a
  window is "accepted" iff the frozen model's `final_decision` correctly
  identifies that same unit.

Deliberately refuses to run under `scientific_task="TARGET_VS_BACKGROUND"`:
that task's label space is TARGET_DEVICE/BACKGROUND_ENVIRONMENT, not
per-unit identity, so comparing `predicted_class == physical_unit_id`
would silently report FRR=1.0 for every window -- a wrong number, not an
honest one.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from app.modules.ble_rffi_studio.campaign.pre_post_pairing import PrePostPair
from app.modules.ble_rffi_studio.contracts import ExampleRecord

from .statistics.inference import hierarchical_cluster_bootstrap
from .statistics.metrics import far_frr

_TARGET_VS_BACKGROUND = "TARGET_VS_BACKGROUND"


class Rq3FrrAnalysisError(Exception):
    pass


def _frr_for_capture(
    *, offline_inference_service: Any, bundle_id: str, examples: list[ExampleRecord], target_physical_unit_id: str,
    window_duration_s: float, minimum_eligible_bursts: int,
) -> dict[str, Any]:
    """Real per-capture FRR over the frozen decision-window pipeline.
    Returns n_windows=0/frr=None (never a fabricated value) when the
    capture has no real examples to score."""
    if not examples:
        return {"n_windows": 0, "frr": None}
    windows = offline_inference_service.run_decision_windows(
        bundle_id=bundle_id, examples=examples, window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
    )
    if not windows:
        return {"n_windows": 0, "frr": None}
    accepted = [w["final_decision"] == "IDENTIFIED" and w["predicted_class"] == target_physical_unit_id for w in windows]
    y_true_is_target = [True] * len(windows)
    result = far_frr(y_true_is_target, accepted)
    return {"n_windows": len(windows), "frr": None if math.isnan(result.frr) else result.frr}


def compute_rq3_pair_frr(
    pairs: list[PrePostPair], *, offline_inference_service: Any, bundle_id: str, scientific_task: str,
    examples_by_capture_id: dict[str, list[ExampleRecord]], window_duration_s: float, minimum_eligible_bursts: int,
) -> list[dict[str, Any]]:
    """Enriches real PrePostPair identity with real FRR_pre/FRR_post/D for
    every VALID pair. An invalid pair keeps its real invalidation_reason
    and never receives a fabricated FRR -- this function computes nothing
    for it."""
    if scientific_task == _TARGET_VS_BACKGROUND:
        raise Rq3FrrAnalysisError(
            "RQ3_REQUIRES_A_DEVICE_IDENTIFICATION_SCIENTIFIC_TASK:TARGET_VS_BACKGROUND's label space "
            "(TARGET_DEVICE/BACKGROUND_ENVIRONMENT) is not per-unit identity -- comparing predicted_class "
            "against physical_unit_id under that task would silently report a wrong FRR, never an honest one."
        )
    enriched: list[dict[str, Any]] = []
    for pair in pairs:
        row: dict[str, Any] = {
            "physical_unit_id": pair.physical_unit_id, "day_id": pair.day_id, "intervention_arm": pair.intervention_arm,
            "pre_capture_id": pair.pre_capture_id, "post_capture_id": pair.post_capture_id,
            "pre_receiver_epoch": pair.pre_receiver_epoch, "post_receiver_epoch": pair.post_receiver_epoch,
            "pre_receiver_session_id": pair.pre_receiver_session_id, "post_receiver_session_id": pair.post_receiver_session_id,
            "valid": pair.valid, "invalidation_reason": pair.invalidation_reason,
            "n_pre_windows": None, "n_post_windows": None, "pre_frr": None, "post_frr": None, "d": None,
        }
        if pair.valid:
            pre_result = _frr_for_capture(
                offline_inference_service=offline_inference_service, bundle_id=bundle_id,
                examples=examples_by_capture_id.get(pair.pre_capture_id, []), target_physical_unit_id=pair.physical_unit_id,
                window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
            )
            post_result = _frr_for_capture(
                offline_inference_service=offline_inference_service, bundle_id=bundle_id,
                examples=examples_by_capture_id.get(pair.post_capture_id, []), target_physical_unit_id=pair.physical_unit_id,
                window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
            )
            row["n_pre_windows"] = pre_result["n_windows"]
            row["n_post_windows"] = post_result["n_windows"]
            if pre_result["frr"] is not None and post_result["frr"] is not None:
                row["pre_frr"] = pre_result["frr"]
                row["post_frr"] = post_result["frr"]
                row["d"] = post_result["frr"] - pre_result["frr"]
        enriched.append(row)
    return enriched


def per_unit_mean_d(pairs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Real per-unit RESET/CONTROL mean D -- a plain mean over each valid
    pair's already-computed D, never a second statistic."""
    reset_by_unit: dict[str, list[float]] = {}
    control_by_unit: dict[str, list[float]] = {}
    for pair in pairs:
        if not pair["valid"] or pair["d"] is None:
            continue
        bucket = reset_by_unit if pair["intervention_arm"] == "RESET" else control_by_unit
        bucket.setdefault(pair["physical_unit_id"], []).append(pair["d"])
    return {
        "reset": {unit: sum(values) / len(values) for unit, values in reset_by_unit.items()},
        "control": {unit: sum(values) / len(values) for unit, values in control_by_unit.items()},
    }


def mean_d_with_ci(pairs: list[dict[str, Any]], *, intervention_arm: str, n_resamples: int = 5000, confidence_level: float = 0.95) -> dict[str, Any] | None:
    """Fast-closure pass (2026-08-12): a real CI on RQ3's own D statistic,
    required for the paper's "D / delta_cycle + CI" figure -- reuses
    hierarchical_cluster_bootstrap() verbatim (the SAME primitive
    bootstrap_accuracy_ci already uses elsewhere), clustered by
    physical_unit_id (never resamples individual pair D values across unit
    boundaries -- each unit is its own cluster, matching per_unit_mean_d's
    own grouping). Never a new statistical method. None (not a fabricated
    interval) when zero valid pairs exist for this arm."""
    by_unit: dict[str, list[float]] = {}
    for pair in pairs:
        if pair["valid"] and pair["d"] is not None and pair["intervention_arm"] == intervention_arm:
            by_unit.setdefault(pair["physical_unit_id"], []).append(pair["d"])
    if not by_unit:
        return None
    result = hierarchical_cluster_bootstrap(list(by_unit.values()), n_resamples=n_resamples, confidence_level=confidence_level)
    return dataclasses.asdict(result)


def device_day_values_for_permutation_test(pairs: list[dict[str, Any]]) -> tuple[dict[str, list[float]], dict[str, list[bool]]]:
    """Real per-unit, per-day D values + RESET/CONTROL flags, in the exact
    shape `stratified_crossover_permutation_test()` (via
    ScientificResultsRepository.run_confirmatory_statistical_plan's
    `rq3_device_day_values`/`rq3_device_day_is_reset` kwargs) already
    accepts -- reuses the untouched permutation-test engine, never a
    second statistical implementation. `_crossover_delta_cycle` requires
    EVERY included device to have at least one RESET and one CONTROL day
    (each device is its own control) -- a unit with only one arm so far is
    real, honest, in-progress data, excluded here rather than crashing the
    permutation engine with a divide-by-zero."""
    values: dict[str, list[float]] = {}
    is_reset: dict[str, list[bool]] = {}
    for pair in pairs:
        if not pair["valid"] or pair["d"] is None:
            continue
        values.setdefault(pair["physical_unit_id"], []).append(pair["d"])
        is_reset.setdefault(pair["physical_unit_id"], []).append(pair["intervention_arm"] == "RESET")
    complete_units = {unit for unit, labels in is_reset.items() if any(labels) and not all(labels)}
    return (
        {unit: values[unit] for unit in complete_units},
        {unit: is_reset[unit] for unit in complete_units},
    )
