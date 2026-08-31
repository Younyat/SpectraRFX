"""Result contracts for the Guided BLE Scientific Validation flow. This is
a REPORTING layer only -- every number here is read from records/artifacts
that build_records()/select_association_policy()/etc. already produced.
Nothing here computes a scientific result of its own.
"""
from __future__ import annotations

from typing import Any, Literal

from ..contracts import StudioContract

GUIDED_VALIDATION_SCHEMA_VERSION = "ble-scientific-results-guided-validation-v1"

GuidedValidationStageStatus = Literal[
    "NOT_STARTED", "RUNNING", "PASSED", "PARTIALLY_SUPPORTED", "BLOCKED", "REQUIRES_PHYSICAL_ACTION", "COMPLETED",
]


class GuidedValidationStage(StudioContract):
    schema_version: str = GUIDED_VALIDATION_SCHEMA_VERSION
    stage_id: str
    label: str
    status: GuidedValidationStageStatus
    plain_explanation: str
    technical_details: dict[str, Any] = {}
    evidence_artifacts: list[str] = []
    next_action: str | None = None


class CapabilityFlag(StudioContract):
    schema_version: str = GUIDED_VALIDATION_SCHEMA_VERSION
    capability: str
    supported: bool
    plain_explanation: str


class GuidedValidationSummary(StudioContract):
    schema_version: str = GUIDED_VALIDATION_SCHEMA_VERSION
    run_id: str
    generated_at: str
    overall_status: str

    stages: list[GuidedValidationStage] = []
    capability_flags: list[CapabilityFlag] = []

    device_summary: dict[str, Any] = {}
    capture_totals: dict[str, Any] = {}
    association_summary: dict[str, Any] = {}
    target_absence_summary: dict[str, Any] = {}
    association_policy_summary: dict[str, Any] | None = None

    simplified_conclusion: str = ""
    next_required_action: str = ""
    artifact_index: dict[str, Any] = {}
