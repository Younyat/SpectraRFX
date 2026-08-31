"""Shared evidence primitives reused by address bindings AND example
annotations -- one vocabulary for "why do we believe this", not two."""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

SourceType = Literal[
    "B200_PACKET",
    "WINDOWS_OBSERVATION",
    "OPERATOR_DECLARATION",
    "MANUFACTURER_DOCUMENTATION",
    "CONTROLLED_EXPERIMENT_PROTOCOL",
]
EvidenceStrength = Literal["STRONG", "WEAK", "DOCUMENTARY"]
DecisionStatus = Literal["CONFIRMED", "PROVISIONAL", "AMBIGUOUS", "REJECTED"]


class LabelEvidenceItem(StudioContract):
    source_type: SourceType
    artifact_id: str
    observation_id: str | None = None
    timestamp: str
    strength: EvidenceStrength
    description: str = ""


class LabelDecision(StudioContract):
    label: str
    decision_status: DecisionStatus
    decision_reason: str
    decided_by: str
    decided_at: str
