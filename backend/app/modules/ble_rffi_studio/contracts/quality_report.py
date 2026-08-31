"""Fase 2 addition: the Dataset Analyzer's output. Never a hardcoded verdict
-- every field here is the result of an actual computed check over a
concrete DatasetManifest, and a FAILED/blocked check always carries the
specific example_ids or keys involved, never just a string like "PASSED"."""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

QUALITY_REPORT_SCHEMA_VERSION = "ble-rffi-studio-quality-report-v1"

CheckStatus = Literal["PASSED", "FAILED", "NOT_EXECUTED"]
GateDecision = Literal["ACCEPTED_FOR_TRAINING", "ACCEPTED_WITH_LIMITATIONS", "NOT_ACCEPTED_FOR_TRAINING"]


class ExactDuplicatesResult(StudioContract):
    status: CheckStatus
    duplicate_groups: list[list[str]] = []  # groups of example_id sharing identical (source_iq_sha256, start, end)


class SampleOverlapPairDetail(StudioContract):
    """Everything an operator needs to judge one FAILED sample_overlap pair
    without reading source code: which two examples, which capture(s), the
    exact sample ranges, how much they overlap, and -- since the extractor
    never generates overlapping windows intentionally -- a concrete,
    evidence-based reason two examples were produced this close together.
    split_a/split_b/cross_partition are filled in later, only where a
    SplitManifest is available (dataset_training_preview), since
    check_sample_overlap() itself runs before any split is chosen."""

    example_id_a: str
    example_id_b: str
    capture_id_a: str
    capture_id_b: str
    iq_start_sample_a: int
    iq_end_sample_a: int
    iq_start_sample_b: int
    iq_end_sample_b: int
    overlap_samples: int
    overlap_fraction_of_smaller_window: float
    reason: str
    split_a: str | None = None
    split_b: str | None = None
    cross_partition: bool = False


class SampleOverlapResult(StudioContract):
    status: CheckStatus
    overlapping_pairs: list[list[str]] = []  # [example_id_a, example_id_b] with overlapping (not identical) ranges
    pair_details: list[SampleOverlapPairDetail] = []


class NearDuplicateResult(StudioContract):
    """DIAGNOSTIC_CHECK only -- per design correction #12, never a blocking
    gate until metric/threshold/phase-and-time invariance/false-positive-rate
    are validated. Always NOT_EXECUTED or a non-blocking informational status;
    this contract structurally has no FAILED state to prevent it from being
    mistaken for a gate."""

    status: Literal["DIAGNOSTIC_CHECK", "NOT_EXECUTED"]
    similarity_metric: str = ""
    similarity_threshold: float | None = None
    flagged_pairs: list[list[str]] = []
    note: str = ""


class DatasetQualityReport(StudioContract):
    schema_version: Literal["ble-rffi-studio-quality-report-v1"] = QUALITY_REPORT_SCHEMA_VERSION
    dataset_id: str
    dataset_version: str

    exact_duplicates: ExactDuplicatesResult
    sample_overlap: SampleOverlapResult
    near_duplicates: NearDuplicateResult

    gate_decision: GateDecision
    gate_reasons: list[str] = []
    created_at: str
