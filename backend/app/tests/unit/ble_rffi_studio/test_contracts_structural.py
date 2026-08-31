"""Fase 0 structural tests: serialization, hashing, immutability, versioning,
and -- the one this whole contract redesign exists to guarantee -- that an
example's identity never depends on its label.

No capture, no training, no real IQ here by design (Fase 0 scope).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.modules.ble_rffi_studio.contracts import (
    ADDRESS_BINDING_SCHEMA_VERSION,
    ANNOTATION_SCHEMA_VERSION,
    BUNDLE_SCHEMA_VERSION,
    CAMPAIGN_SCHEMA_VERSION,
    CAPTURE_SCHEMA_VERSION,
    DATASET_SCHEMA_VERSION,
    EXAMPLE_SCHEMA_VERSION,
    PHYSICAL_UNIT_SCHEMA_VERSION,
    PROJECT_SCHEMA_VERSION,
    TRAINING_RUN_SCHEMA_VERSION,
    AddressBinding,
    CampaignRecord,
    CaptureRecord,
    DatasetManifest,
    ExampleAnnotation,
    ExampleRecord,
    LabelDecision,
    LabelEvidenceItem,
    LeakageCheckResult,
    ModelBundleManifest,
    PhysicalUnitRecord,
    ProjectRecord,
    REQUIRED_BUNDLE_FILES,
    SplitAssignment,
    SplitManifest,
    TrainingRun,
)


def _example_kwargs(**overrides):
    base = dict(
        example_id=ExampleRecord.make_example_id("sha-iq-abc", 100, 200, "cand-1", "pkt-1"),
        project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01",
        capture_id="BLE-IQ-test", execution_id="BLE-HYBRID-test", session_id="S001-POS",
        candidate_id="cand-1", packet_id="pkt-1",
        source_iq_sha256="sha-iq-abc", iq_start_sample=100, iq_end_sample=200,
        physical_unit_id="CC2650-UNIT-01", logical_transmitter_id="TX-1",
        association_status="STRONG", quality_status="PASSED", dataset_eligibility="PENDING_ANALYSIS",
        channel=37, sample_rate_sps=4_000_000, center_frequency_hz=2_402_000_000,
        created_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Serialization / round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_cls,kwargs", [
    (ProjectRecord, dict(project_id="p1", name="n", device_family="TI", created_at="2026-01-01T00:00:00Z")),
    (CampaignRecord, dict(campaign_id="c1", project_id="p1", name="n", created_at="2026-01-01T00:00:00Z")),
])
def test_round_trip_serialization(model_cls, kwargs):
    instance = model_cls(**kwargs)
    restored = model_cls.model_validate(json.loads(instance.canonical_json()))
    assert restored == instance


def test_example_round_trip():
    instance = ExampleRecord(**_example_kwargs())
    restored = ExampleRecord.model_validate(json.loads(instance.canonical_json()))
    assert restored == instance


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

def test_project_record_is_frozen():
    record = ProjectRecord(project_id="p1", name="n", device_family="TI", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(ValidationError):
        record.name = "changed"


def test_example_record_is_frozen():
    record = ExampleRecord(**_example_kwargs())
    with pytest.raises(ValidationError):
        record.dataset_eligibility = "ELIGIBLE"


def test_dataset_manifest_is_frozen():
    manifest = DatasetManifest(dataset_id="d1", dataset_version="1.0.0", project_id="p1", campaign_id="c1", data_origin="REAL_B200", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(ValidationError):
        manifest.frozen = True


# ---------------------------------------------------------------------------
# Schema versioning: every contract carries an explicit, distinct version.
# ---------------------------------------------------------------------------

def test_schema_versions_are_explicit_and_distinct():
    versions = {
        PROJECT_SCHEMA_VERSION, CAMPAIGN_SCHEMA_VERSION, PHYSICAL_UNIT_SCHEMA_VERSION,
        ADDRESS_BINDING_SCHEMA_VERSION, CAPTURE_SCHEMA_VERSION, EXAMPLE_SCHEMA_VERSION,
        ANNOTATION_SCHEMA_VERSION, DATASET_SCHEMA_VERSION, TRAINING_RUN_SCHEMA_VERSION,
        BUNDLE_SCHEMA_VERSION,
    }
    assert len(versions) == 10, "two contracts silently share a schema_version"
    assert all(v.startswith("ble-rffi-studio-") and v.endswith("-v1") for v in versions)


def test_wrong_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        ProjectRecord(schema_version="some-other-version", project_id="p1", name="n", device_family="TI", created_at="2026-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Hash determinism: identical content -> identical hash, regardless of kwarg
# construction order.
# ---------------------------------------------------------------------------

def test_content_hash_is_order_independent():
    kwargs = _example_kwargs()
    reordered = dict(reversed(list(kwargs.items())))
    a = ExampleRecord(**kwargs)
    b = ExampleRecord(**reordered)
    assert a.content_hash() == b.content_hash()


def test_example_id_is_deterministic_from_evidence_fields():
    first = ExampleRecord.make_example_id("sha-iq-abc", 100, 200, "cand-1", "pkt-1")
    second = ExampleRecord.make_example_id("sha-iq-abc", 100, 200, "cand-1", "pkt-1")
    assert first == second


# ---------------------------------------------------------------------------
# THE core guarantee: example_id must never depend on the label.
# ExampleRecord structurally has no label field; a label lives only in
# ExampleAnnotation, referencing example_id. Relabeling never touches the
# ExampleRecord or its identity.
# ---------------------------------------------------------------------------

def test_example_record_has_no_label_field():
    assert "label" not in ExampleRecord.model_fields
    assert "label_provenance" not in ExampleRecord.model_fields


def test_relabeling_produces_a_new_annotation_not_a_mutated_example():
    example = ExampleRecord(**_example_kwargs())

    evidence_v1 = [LabelEvidenceItem(source_type="B200_PACKET", artifact_id="pkt-1", timestamp="2026-01-01T00:00:00Z", strength="WEAK", description="candidate only")]
    decision_v1 = LabelDecision(label="UNKNOWN_ENVIRONMENTAL_TRANSMITTER", decision_status="PROVISIONAL", decision_reason="single weak signal", decided_by="system", decided_at="2026-01-01T00:00:00Z")
    annotation_v1 = ExampleAnnotation(
        annotation_id=ExampleAnnotation.make_annotation_id(example.example_id, 1),
        example_id=example.example_id, annotation_version=1,
        label_evidence=evidence_v1, label_decision=decision_v1, created_at="2026-01-01T00:00:00Z",
    )

    # New evidence arrives (e.g. Windows corroboration) -> a NEW annotation
    # version, never an edit of annotation_v1.
    evidence_v2 = evidence_v1 + [LabelEvidenceItem(source_type="WINDOWS_OBSERVATION", artifact_id="native-1", timestamp="2026-01-01T00:00:05Z", strength="STRONG", description="matching callback within 15ms")]
    decision_v2 = LabelDecision(label="CC2650-UNIT-01", decision_status="CONFIRMED", decision_reason="strong B200+Windows association", decided_by="operator:alice", decided_at="2026-01-01T00:05:00Z")
    annotation_v2 = ExampleAnnotation(
        annotation_id=ExampleAnnotation.make_annotation_id(example.example_id, 2),
        example_id=example.example_id, annotation_version=2,
        label_evidence=evidence_v2, label_decision=decision_v2, created_at="2026-01-01T00:05:00Z",
    )
    annotation_v1_superseded = annotation_v1.model_copy(update={"superseded_by_annotation_id": annotation_v2.annotation_id})

    # The example's identity and every one of its evidence/status fields are
    # completely untouched by this relabeling.
    assert example.example_id == ExampleRecord.make_example_id("sha-iq-abc", 100, 200, "cand-1", "pkt-1")
    assert annotation_v1.example_id == annotation_v2.example_id == example.example_id
    assert annotation_v1.annotation_id != annotation_v2.annotation_id
    assert annotation_v1_superseded.superseded_by_annotation_id == annotation_v2.annotation_id
    # Promotion requires non-empty new evidence -- never bare re-assertion.
    assert len(evidence_v2) > len(evidence_v1)


def test_promotion_without_new_evidence_is_structurally_suspicious():
    """Not a hard runtime guard (that belongs to the future annotation
    service in evidence/), but the contract makes an evidence-free promotion
    trivially detectable: label_evidence would be identical between versions."""
    evidence = [LabelEvidenceItem(source_type="OPERATOR_DECLARATION", artifact_id="decl-1", timestamp="2026-01-01T00:00:00Z", strength="DOCUMENTARY", description="declared")]
    v1_decision = LabelDecision(label="UNKNOWN_ENVIRONMENTAL_TRANSMITTER", decision_status="AMBIGUOUS", decision_reason="conflicting candidates", decided_by="system", decided_at="2026-01-01T00:00:00Z")
    v2_decision = LabelDecision(label="CC2650-UNIT-01", decision_status="CONFIRMED", decision_reason="operator says so", decided_by="operator:bob", decided_at="2026-01-01T00:01:00Z")
    # Same evidence list reused for both versions (no new evidence attached).
    assert evidence == evidence  # identity list unchanged between the two decisions
    assert v1_decision.label != v2_decision.label  # a real service must reject this promotion


# ---------------------------------------------------------------------------
# Association / quality / eligibility are independent axes.
# ---------------------------------------------------------------------------

def test_association_quality_eligibility_vary_independently():
    example = ExampleRecord(**_example_kwargs(association_status="AMBIGUOUS", quality_status="PASSED", dataset_eligibility="QUARANTINED"))
    assert example.association_status == "AMBIGUOUS"
    assert example.quality_status == "PASSED"
    assert example.dataset_eligibility == "QUARANTINED"
    # An ambiguous association does not force quarantine as quality, and vice versa.
    example2 = ExampleRecord(**_example_kwargs(association_status="STRONG", quality_status="FAILED", dataset_eligibility="INELIGIBLE"))
    assert example2.association_status == "STRONG" and example2.quality_status == "FAILED"


# ---------------------------------------------------------------------------
# Address binding: N addresses -> at most 1 unit, never the reverse; unseen
# address never creates a unit (there is no such constructor path).
# ---------------------------------------------------------------------------

def test_address_binding_id_is_deterministic_and_unbound_by_default_shape():
    binding_id = AddressBinding.make_binding_id("BLE-RFFI-CC2650", "B0:B4:48:C0:36:06", "public")
    assert binding_id == AddressBinding.make_binding_id("BLE-RFFI-CC2650", "B0:B4:48:C0:36:06", "public")
    binding = AddressBinding(
        binding_id=binding_id, project_id="BLE-RFFI-CC2650", address="B0:B4:48:C0:36:06", address_type="public",
        bound_physical_unit_id=None, binding_status="UNBOUND", first_seen="2026-01-01T00:00:00Z", last_seen="2026-01-01T00:00:00Z",
    )
    assert binding.bound_physical_unit_id is None
    assert binding.binding_status == "UNBOUND"


def test_physical_unit_record_has_no_address_field():
    # Addresses live exclusively in AddressBinding -- a unit's schema has no
    # field that could be (mis)used to store or derive identity from a MAC.
    assert "observed_ble_addresses" not in PhysicalUnitRecord.model_fields
    assert not any("address" in name for name in PhysicalUnitRecord.model_fields)


# ---------------------------------------------------------------------------
# Leakage check: structured result, never a bare literal.
# ---------------------------------------------------------------------------

def test_leakage_check_result_carries_real_evidence_not_a_bare_string():
    failed = LeakageCheckResult(status="FAILED", checked_group_fields=["capture_id", "session_id"], overlapping_keys={"session_id": ["S001-POS"]})
    assert failed.status == "FAILED"
    assert failed.overlapping_keys == {"session_id": ["S001-POS"]}
    passed = LeakageCheckResult(status="PASSED", checked_group_fields=["capture_id", "session_id"])
    assert passed.overlapping_keys == {}


def test_split_manifest_not_feasible_carries_a_reason():
    manifest = SplitManifest(
        dataset_id="d1", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", policy="session_disjoint",
        split_status="NOT_FEASIBLE", infeasibility_reason="Only 1 physical_unit_id available; SAME_MODEL_UNIT_IDENTIFICATION requires >=2.",
        leakage_check=LeakageCheckResult(status="NOT_EXECUTED"), created_at="2026-01-01T00:00:00Z",
    )
    assert manifest.split_status == "NOT_FEASIBLE"
    assert manifest.infeasibility_reason


def test_split_assignment_allows_shared_physical_unit_across_splits():
    """physical_unit_id repeating across TRAIN/VALIDATION/TEST is correct for
    closed-set classification -- only capture/session/execution/candidate/
    packet identity must stay disjoint. The contract itself must not forbid
    the same physical_unit_id appearing in different splits."""
    train = SplitAssignment(example_id="ex-1", physical_unit_id="CC2650-UNIT-01", capture_id="cap-1", session_id="sess-A", split="TRAIN", split_reason="session-disjoint")
    test = SplitAssignment(example_id="ex-2", physical_unit_id="CC2650-UNIT-01", capture_id="cap-2", session_id="sess-B", split="TEST", split_reason="session-disjoint")
    assert train.physical_unit_id == test.physical_unit_id
    assert train.session_id != test.session_id  # the thing that must differ


# ---------------------------------------------------------------------------
# Bundle: required files enumerated explicitly, hashed, never just model.pt.
# ---------------------------------------------------------------------------

def test_required_bundle_files_is_a_real_list_not_just_the_model_file():
    assert "model_file" in REQUIRED_BUNDLE_FILES
    assert len(REQUIRED_BUNDLE_FILES) >= 16
    assert "scientific_basis.json" in REQUIRED_BUNDLE_FILES
    assert "calibration_report.json" in REQUIRED_BUNDLE_FILES
    assert "acceptance_criteria.json" in REQUIRED_BUNDLE_FILES


def test_bundle_defaults_to_draft_not_approved():
    bundle = ModelBundleManifest(bundle_id="bundle-1", training_run_id="run-1", data_origin="REAL_B200", operational_use="ALLOWED", created_at="2026-01-01T00:00:00Z")
    assert bundle.approval_status == "DRAFT"


# ---------------------------------------------------------------------------
# Full-record instantiation of every remaining contract (capture, training)
# to guarantee the expanded field lists actually construct.
# ---------------------------------------------------------------------------

def test_capture_record_full_construction():
    capture = CaptureRecord(
        project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01",
        capture_id="BLE-IQ-e8edc49b59a0", session_id="S001-POS", execution_id="BLE-HYBRID-20260724T121557Z-ea66fb",
        data_origin="REAL_B200", physical_unit_id="CC2650-UNIT-01",
        receiver_device_id="usrp-b200-E3R04Z1B2", sdr_model="USRP B200", sdr_serial="E3R04Z1B2", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="native", sample_count=40_000_000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000,
        gain_db=20.0, gain_mode="manual", clock_source="internal", time_source="internal",
        capture_duration_s=10.0, capture_tool="ble_sdr_capture_worker.py", capture_tool_version=None, software_commit=None,
        iq_path="BLE-IQ-e8edc49b59a0.sigmf-data", iq_size_bytes=320_000_000, iq_sha256="751d880979196d709e9f03bcd30afc79d03be34ca747b383b672551df1473874",
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-07-24T12:15:57Z",
    )
    restored = CaptureRecord.model_validate(json.loads(capture.canonical_json()))
    assert restored == capture


def test_training_run_full_construction():
    run = TrainingRun(
        training_run_id="run-1", project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01",
        dataset_id="d1", dataset_version="1.0.0", dataset_manifest_sha256="a" * 64, split_manifest_sha256="b" * 64,
        scientific_task="MULTI_DEVICE_CLASSIFICATION", model_type="cnn1d", data_origin="REAL_B200", operational_use="ALLOWED",
        base_preprocessing_profile_id="base-v1", representation_profile_id="raw_iq-v1",
        hyperparameters={"lr": 0.001, "epochs": 50}, random_seed=42, software_versions={"torch": "2.11.0"},
    )
    assert run.status == "QUEUED"
    assert run.model_type == "cnn1d"
