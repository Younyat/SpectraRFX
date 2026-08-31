from __future__ import annotations

from typing import Literal

from .common import StudioContract

SPLIT_SCHEMA_VERSION = "ble-rffi-studio-split-v1"

ScientificTask = Literal[
    "TARGET_VS_BACKGROUND",
    "MULTI_DEVICE_CLASSIFICATION",
    "SAME_MODEL_UNIT_IDENTIFICATION",
    "UNKNOWN_DEVICE_REJECTION",
]
SplitName = Literal["TRAIN", "VALIDATION", "TEST"]
SplitStatus = Literal["READY", "NOT_FEASIBLE"]
LeakageCheckStatus = Literal["NOT_EXECUTED", "RUNNING", "PASSED", "FAILED", "INCOMPLETE"]

# RQ1 needs to deliberately measure acquisition-dependence optimism, which
# means deliberately violating capture-disjointness for one, clearly-marked,
# non-confirmatory split -- never the default and never reachable from
# SplitBuilder.build(). Any split_purpose other than CONFIRMATORY must never
# be used to select a model, calibrate a threshold, or report a paper result.
#
# RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC (2026-08-18 correction):
# RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC splits by ExampleRecord hash-order,
# which can place TRAIN-role and held-out-role bursts inside the exact SAME
# real 10-second decision window -- scientifically defensible at the
# ExampleRecord unit RQ1 was originally built for, but not a valid
# "capture-dependent" diagnostic at 10-second decision-window granularity.
# This purpose is for SplitBuilder.build_rq1_window_level_dependence_diagnostic():
# same capture=YES, same real decision window=NO, shared bursts=NO -- whole,
# non-overlapping real decision windows reserved deterministically for
# fitting vs. diagnostic roles, never by result.
SplitPurpose = Literal["CONFIRMATORY", "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC", "RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC"]


class SplitAssignment(StudioContract):
    example_id: str
    physical_unit_id: str | None
    capture_id: str
    session_id: str
    split: SplitName
    split_reason: str


class LeakageCheckResult(StudioContract):
    """Never a hardcoded literal -- status must come from an actual computed
    check, and FAILED must carry the exact overlapping keys, not a string."""

    status: LeakageCheckStatus
    checked_group_fields: list[str] = []  # e.g. ["capture_id","session_id","execution_id","candidate_id","packet_id"]
    overlapping_keys: dict[str, list[str]] = {}  # field -> list of values found in more than one split
    evidence: str = ""


class SplitManifest(StudioContract):
    schema_version: Literal["ble-rffi-studio-split-v1"] = SPLIT_SCHEMA_VERSION
    dataset_id: str
    dataset_version: str
    scientific_task: ScientificTask
    policy: str

    split_status: SplitStatus
    infeasibility_reason: str | None = None

    assignments: list[SplitAssignment] = []
    leakage_check: LeakageCheckResult
    split_manifest_sha256: str | None = None
    created_at: str

    # Split-policy correction (2026-08-08): example_ids excluded before
    # splitting because they fall outside this task's declared channel scope
    # (main benchmark is channel 37 only -- see split_builder.py module
    # docstring). Recorded even on a NOT_FEASIBLE outcome so a channel-scope
    # exclusion is always auditable from the manifest, never silent.
    channel_scope_excluded_example_ids: list[str] = []

    # Set only by SplitBuilder.build_rq1_dependence_diagnostic(); every split
    # produced by the normal build() stays CONFIRMATORY/non_confirmatory=False.
    split_purpose: SplitPurpose = "CONFIRMATORY"
    non_confirmatory: bool = False
