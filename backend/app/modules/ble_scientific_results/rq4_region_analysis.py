"""RQ4 region-specific fitting -- canonical per-matched-block report producer
(2026-08-12, RQ4 scientific closure). rq4_primary_analysis=
REGION_SPECIFIC_FITTING_AND_EVALUATION (recorded via record_scientist_decision):
the SAME frozen PRIMARY branch RQ2 already selected is fitted independently
per analytical_region (FULL_BURST/ADVA_EXCLUDED/PRE_PDU) -- see
ble_rffi_studio.api.studio_repository.train_region_specific_variant for the
fitting side. This module is purely the scoring/reporting glue, mirroring
rq3_frr_analysis.py's own pattern:

- Decision windows come from OfflineInferenceService.run_decision_windows()
  -- the SAME frozen decision-window rule/calibrated-threshold pipeline
  RQ1-3 already use, never a second scoring path.
- eligible_windows/decided_windows/abstained_windows/coverage reuse
  coverage_analysis.py's own real definitions verbatim (never a second
  abstention/coverage definition) -- point 9 of the RQ4 closure explicitly
  requires this so a better recall is never confused with more abstention.
- The "protocol-defined performance quantity" (recall / accept-rate) reuses
  statistics/metrics.py::far_frr(), the SAME primitive RQ3's FRR analysis
  uses: accept-rate = 1 - FRR, computed over ALL eligible windows (so an
  abstained window still counts as a reject, never silently dropped from
  the denominator).

matched_region_block_id = (physical_unit_id, day_id, packet_condition): the
real, already-declared CaptureRecord identity that groups every capture of
the SAME physical unit acquired the same day under the same
packet_condition -- deliberately a DIFFERENT dimension from
analytical_region (point 6 of the RQ4 closure: packet_condition describes
what was physically transmitted, analytical_region describes which derived
sample region of an already-captured burst is analyzed). A block
contributes to a region-pair contrast only when BOTH regions have a real
recall value for it (point 5's comparability requirement) -- never a
fabricated pairing.

PRIMARY contrast is FULL_BURST vs PRE_PDU (per the paper's own definition
of PRE_PDU as the primary limited-content region, point 11). SECONDARY is
FULL_BURST vs ADVA_EXCLUDED -- diagnostic only, deliberately never fed into
the Holm-corrected confirmatory hypothesis family (point 12: NI margin,
alpha, hypothesis family, and Holm correction are untouched by this
module -- only rq4_scores_a/rq4_scores_b, the PRIMARY contrast, are ever
handed to run_confirmatory_statistical_plan).
"""
from __future__ import annotations

import math
from typing import Any

from app.modules.ble_rffi_studio.contracts import CaptureRecord, ExampleRecord

from .coverage_analysis import CoverageRow, compute_coverage_summary
from .statistics.metrics import far_frr

ANALYTICAL_REGIONS: tuple[str, ...] = ("FULL_BURST", "ADVA_EXCLUDED", "PRE_PDU")
PRIMARY_CONTRAST: tuple[str, str] = ("FULL_BURST", "PRE_PDU")
SECONDARY_CONTRAST: tuple[str, str] = ("FULL_BURST", "ADVA_EXCLUDED")


class Rq4RegionAnalysisError(Exception):
    pass


def matched_region_block_id(capture: CaptureRecord) -> str | None:
    """None when a capture lacks the real identity RQ4 needs to place it in
    a matched block (unknown physical_unit_id/day_id/packet_condition) --
    such captures are honestly excluded, never guessed into a block."""
    if capture.physical_unit_id is None or capture.day_id is None or capture.packet_condition is None:
        return None
    return f"{capture.physical_unit_id}|{capture.day_id}|{capture.packet_condition}"


def build_matched_region_blocks(captures: list[CaptureRecord]) -> dict[str, list[CaptureRecord]]:
    blocks: dict[str, list[CaptureRecord]] = {}
    for capture in captures:
        block_id = matched_region_block_id(capture)
        if block_id is None:
            continue
        blocks.setdefault(block_id, []).append(capture)
    return blocks


def _region_result_for_block(
    *, block_captures: list[CaptureRecord], analytical_region: str, target_physical_unit_id: str,
    offline_inference_service: Any, bundle_id: str, examples_by_capture_id: dict[str, list[ExampleRecord]],
    eligible_example_ids: set[str], window_duration_s: float, minimum_eligible_bursts: int,
) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    for capture in block_captures:
        examples = [e for e in examples_by_capture_id.get(capture.capture_id, []) if e.example_id in eligible_example_ids]
        if not examples:
            continue
        windows.extend(offline_inference_service.run_decision_windows(
            bundle_id=bundle_id, examples=examples, window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
        ))
    if not windows:
        return {
            "analytical_region": analytical_region, "eligible_windows": 0, "decided_windows": 0,
            "abstained_windows": 0, "coverage": None, "recall": None,
        }

    rows = [
        CoverageRow(
            decided=(w["final_decision"] != "INSUFFICIENT_EVIDENCE"),
            correct=(w["final_decision"] == "IDENTIFIED" and w["predicted_class"] == target_physical_unit_id) if w["final_decision"] != "INSUFFICIENT_EVIDENCE" else None,
            branch=analytical_region, physical_unit_id=target_physical_unit_id, abstention_reason=w.get("abstention_reason"),
        )
        for w in windows
    ]
    summary = compute_coverage_summary(rows)["overall"] or {}

    # Recall/accept-rate follows RQ3's own far_frr()-based convention:
    # every eligible window is a target trial (this block genuinely belongs
    # to target_physical_unit_id by construction), "accepted" iff the
    # frozen model both decided AND decided correctly -- an abstained
    # window counts as a reject too, so a higher recall here can never be
    # explained away by higher abstention (point 9).
    accepted = [w["final_decision"] == "IDENTIFIED" and w["predicted_class"] == target_physical_unit_id for w in windows]
    y_true_is_target = [True] * len(windows)
    far_frr_result = far_frr(y_true_is_target, accepted)
    recall = None if math.isnan(far_frr_result.frr) else 1.0 - far_frr_result.frr

    return {
        "analytical_region": analytical_region,
        "eligible_windows": summary.get("eligible_windows", len(windows)),
        "decided_windows": summary.get("decided_windows"),
        "abstained_windows": summary.get("abstained_windows"),
        "coverage": summary.get("coverage"),
        "recall": recall,
    }


def compute_rq4_region_report(
    *, blocks: dict[str, list[CaptureRecord]], examples_by_capture_id: dict[str, list[ExampleRecord]],
    eligible_example_ids_by_region: dict[str, set[str]], inference_services: dict[str, Any | None],
    bundle_ids: dict[str, str | None], window_duration_s: float, minimum_eligible_bursts: int,
) -> dict[str, Any]:
    """Real per-matched-block, per-region report (point 10 of the RQ4
    closure). A region with no inference_service/bundle_id for this run
    (e.g. 0 examples eligible for ADVA_EXCLUDED in this project) reports
    every block's region result as None for that region -- never a
    fabricated recall."""
    rows: list[dict[str, Any]] = []
    for block_id, captures in sorted(blocks.items()):
        physical_unit_id = captures[0].physical_unit_id
        region_results: dict[str, dict[str, Any] | None] = {}
        for region in ANALYTICAL_REGIONS:
            service = inference_services.get(region)
            bundle_id = bundle_ids.get(region)
            if service is None or bundle_id is None:
                region_results[region] = None
                continue
            region_results[region] = _region_result_for_block(
                block_captures=captures, analytical_region=region, target_physical_unit_id=physical_unit_id,
                offline_inference_service=service, bundle_id=bundle_id, examples_by_capture_id=examples_by_capture_id,
                eligible_example_ids=eligible_example_ids_by_region.get(region) or set(),
                window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
            )
        rows.append({
            "matched_region_block_id": block_id, "physical_unit_id": physical_unit_id,
            "day_id": captures[0].day_id, "packet_condition": captures[0].packet_condition,
            "capture_ids": [c.capture_id for c in captures], "regions": region_results,
        })

    def _paired_scores(a_region: str, b_region: str) -> tuple[list[float], list[float], int]:
        scores_a: list[float] = []
        scores_b: list[float] = []
        for row in rows:
            a, b = row["regions"].get(a_region), row["regions"].get(b_region)
            if a and b and a["recall"] is not None and b["recall"] is not None:
                scores_a.append(a["recall"])
                scores_b.append(b["recall"])
        return scores_a, scores_b, len(scores_a)

    primary_a, primary_b, n_primary = _paired_scores(*PRIMARY_CONTRAST)
    secondary_a, secondary_b, n_secondary = _paired_scores(*SECONDARY_CONTRAST)

    return {
        "schema_version": "ble-scientific-results-rq4-region-analysis-v1",
        "matched_region_blocks": rows,
        "bundle_ids": bundle_ids,
        "primary_contrast": {"a_region": PRIMARY_CONTRAST[0], "b_region": PRIMARY_CONTRAST[1], "n_matched_blocks": n_primary},
        "primary_contrast_scores_a": primary_a, "primary_contrast_scores_b": primary_b,
        "secondary_contrast": {"a_region": SECONDARY_CONTRAST[0], "b_region": SECONDARY_CONTRAST[1], "n_matched_blocks": n_secondary},
        "secondary_contrast_scores_a": secondary_a, "secondary_contrast_scores_b": secondary_b,
    }
