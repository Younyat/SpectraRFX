"""Scientific preflight: six independent, concretely-computed check
categories, never a single opaque pass/fail flag. Each category's `status`
must come from an actual comparison against on-disk `ble_rffi_studio`
artifacts (captures, evidence, datasets, splits, quality reports) --
mirroring the same discipline `LeakageCheckResult`/`DatasetQualityReport`
already use elsewhere in this codebase (status is never a hardcoded
literal, FAILED always carries the specific offending keys/ids).

Two-tier overall status, never one generic escalation step (design
correction, Fase 1 closure item A.1): a dataset can be internally coherent
(integrity/leakage/population/quality/design_completeness all real,
concrete PASSED checks) without the campaign it came from actually
satisfying everything AnalysisContract declares for the PAPER as a whole
(population, days, sessions, pre/post, reset/control, channels, content
variants, independent blocks, groups/holdouts, receiver profile, negative
controls). Reaching PAPER_CAMPAIGN_PREFLIGHT_PASSED requires BOTH tiers;
DATASET_STRUCTURAL_PREFLIGHT_PASSED alone must never be presented as "ready
for the paper".

No field anywhere in this module lets a caller force PASSED at either tier
without every relevant category actually passing -- there is deliberately
no override parameter on any of these contracts or on the repository
method that produces them (enforced structurally here, and checked by
`test_no_manual_override.py`).
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

PREFLIGHT_SCHEMA_VERSION = "ble-scientific-results-preflight-v1"

CheckCategoryStatus = Literal["PASSED", "BLOCKED"]
PreflightStatus = Literal["DATASET_STRUCTURAL_PREFLIGHT_PASSED", "PAPER_CAMPAIGN_PREFLIGHT_PASSED", "PREFLIGHT_BLOCKED"]


class IntegrityCheckResult(StudioContract):
    status: CheckCategoryStatus
    findings: list[str] = []
    checked_capture_count: int = 0


class LeakageCheckResult(StudioContract):
    status: CheckCategoryStatus
    findings: list[str] = []
    checked_split_ids: list[str] = []


class PopulationSeparationResult(StudioContract):
    status: CheckCategoryStatus
    findings: list[str] = []
    population_counts: dict[str, int] = {}


class QualityCheckResult(StudioContract):
    status: CheckCategoryStatus
    findings: list[str] = []
    checked_dataset_ids: list[str] = []


class DesignCompletenessResult(StudioContract):
    status: CheckCategoryStatus
    findings: list[str] = []


class PaperCampaignCompletenessResult(StudioContract):
    """Tier 2: everything AnalysisContract declares for the PAPER campaign
    as a whole -- population, days, sessions, pre/post, reset/control,
    channels, content variants, independent blocks, groups/holdouts,
    receiver profile, negative controls. `checked_requirements` always lists
    every requirement this run actually checked (even the ones that
    passed), so PASSED can never be read as "nothing was checked"."""

    status: CheckCategoryStatus
    findings: list[str] = []
    checked_requirements: list[str] = []


StructuralCheckResult = "IntegrityCheckResult | LeakageCheckResult | PopulationSeparationResult | QualityCheckResult | DesignCompletenessResult"


class ScientificPreflightReport(StudioContract):
    schema_version: str = PREFLIGHT_SCHEMA_VERSION
    paper_run_id: str
    protocol_id: str
    protocol_version: int
    generated_at: str

    integrity: IntegrityCheckResult
    leakage: LeakageCheckResult
    population_separation: PopulationSeparationResult
    quality: QualityCheckResult
    design_completeness: DesignCompletenessResult
    paper_campaign_completeness: PaperCampaignCompletenessResult

    overall_status: PreflightStatus

    @staticmethod
    def compute_overall_status(
        structural_categories: list,  # list[StructuralCheckResult], see module docstring for the tiering rule
        campaign_completeness: PaperCampaignCompletenessResult,
    ) -> PreflightStatus:
        if not all(category.status == "PASSED" for category in structural_categories):
            return "PREFLIGHT_BLOCKED"
        if campaign_completeness.status != "PASSED":
            return "DATASET_STRUCTURAL_PREFLIGHT_PASSED"
        return "PAPER_CAMPAIGN_PREFLIGHT_PASSED"
