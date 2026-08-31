"""ExampleRecord identifies an RF fragment. ExampleAnnotation interprets it.

These are deliberately two different contracts. ExampleRecord has NO label
field anywhere in its schema -- that is not a style choice, it is the
structural guarantee that example_id (derived only from evidence-identity
fields) can never change because someone re-labeled the fragment. A label
change always produces a NEW ExampleAnnotation (new annotation_version),
never a mutation of the ExampleRecord or of a previous annotation.
"""
from __future__ import annotations

from typing import Literal

from .capture import BackgroundKind, CapturePurpose
from .common import StudioContract, identity_hash
from .evidence import LabelDecision, LabelEvidenceItem

EXAMPLE_SCHEMA_VERSION = "ble-rffi-studio-example-v1"
ANNOTATION_SCHEMA_VERSION = "ble-rffi-studio-annotation-v1"

AssociationStatus = Literal["STRONG", "AMBIGUOUS", "NONE", "CONFLICT", "PHYSICAL_ISOLATION_DECLARED"]
QualityStatus = Literal["PASSED", "FAILED", "INCOMPLETE"]
DatasetEligibility = Literal["ELIGIBLE", "INELIGIBLE", "QUARANTINED", "PENDING_ANALYSIS"]


class ExampleRecord(StudioContract):
    schema_version: Literal["ble-rffi-studio-example-v1"] = EXAMPLE_SCHEMA_VERSION
    example_id: str

    project_id: str
    campaign_id: str
    capture_id: str
    execution_id: str
    session_id: str
    candidate_id: str
    packet_id: str

    source_iq_sha256: str
    iq_start_sample: int
    iq_end_sample: int

    physical_unit_id: str | None = None
    logical_transmitter_id: str | None = None
    # Denormalized copy of the owning CaptureRecord's capture_purpose/
    # background_kind at the moment evidence was built (never part of
    # example_id -- purely interpretive, like physical_unit_id). Exists so
    # SplitBuilder/feasibility_explainer can tell "no address match"
    # (association_status NONE/CONFLICT, physical_unit_id=None) apart from
    # "operator confirmed this device was off/removed"
    # (capture_purpose=BACKGROUND_TARGET_OFF) without a separate capture
    # lookup -- only the latter (and BACKGROUND_GENERAL) is trustworthy
    # negative evidence for TARGET_VS_BACKGROUND; the former is just
    # inconclusive.
    capture_purpose: CapturePurpose | None = None
    background_kind: BackgroundKind | None = None

    # Three independent axes -- never conflated into one status field.
    association_status: AssociationStatus
    quality_status: QualityStatus
    dataset_eligibility: DatasetEligibility

    channel: int
    sample_rate_sps: int
    center_frequency_hz: int
    preprocessing_profile_id: str | None = None
    created_at: str

    @staticmethod
    def make_example_id(source_iq_sha256: str, iq_start_sample: int, iq_end_sample: int, candidate_id: str, packet_id: str) -> str:
        """Identity of the RF fragment itself. Deliberately excludes label,
        physical_unit_id, association_status, and every other interpretive
        field -- those can all change without the fragment becoming "a
        different example"."""
        return identity_hash(source_iq_sha256, iq_start_sample, iq_end_sample, candidate_id, packet_id, prefix="ex")


class ExampleAnnotation(StudioContract):
    schema_version: Literal["ble-rffi-studio-annotation-v1"] = ANNOTATION_SCHEMA_VERSION
    annotation_id: str
    example_id: str
    annotation_version: int  # monotonic, starts at 1

    label_evidence: list[LabelEvidenceItem]
    label_decision: LabelDecision

    # Full label history is kept -- never delete a prior annotation. A
    # promotion/demotion sets this on the annotation it replaces.
    superseded_by_annotation_id: str | None = None
    created_at: str

    @staticmethod
    def make_annotation_id(example_id: str, annotation_version: int) -> str:
        return identity_hash(example_id, annotation_version, prefix="ann")
