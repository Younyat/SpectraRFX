"""Evidence Stage against the real, already-replayed BLE-IQ-e8edc49b59a0
capture. Exercises the full real chain: BlePacketAnalysisService.analyze()
(Phase 2, reused unchanged) -> association/quality/eligibility separation ->
Physical Device Registry lookup -> ExampleRecord + ExampleAnnotation.

The real ledger for this capture has exactly 4 STRONG target associations,
539 CRC-valid packets total, and 0 CONFLICT rows (verified independently by
grep during Fase 1 design) -- this test asserts against those known real
numbers rather than a synthetic count, so a silent regression in any of the
reused Phase 2 code would fail it too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.acquisition.capture_stage import CaptureStage
from app.modules.ble_rffi_studio.contracts import LabelEvidenceItem
from app.modules.ble_rffi_studio.evidence.evidence_stage import EvidenceStage
from app.modules.ble_rffi_studio.registry import PhysicalDeviceRegistry

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
SESSION_ROOT = STORAGE_ROOT / "ble_lab" / "sessions"
REAL_CAPTURE_ID = "BLE-IQ-e8edc49b59a0"
TARGET_ADDRESS = "B0:B4:48:C0:36:06"
PROJECT_ID = "BLE-RFFI-CC2650"

pytestmark = pytest.mark.skipif(not (CAPTURE_ROOT / REAL_CAPTURE_ID).is_dir(), reason="real capture fixture not present in this environment")


@pytest.fixture
def capture():
    return CaptureStage(CAPTURE_ROOT).build_capture_record(capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01")


@pytest.fixture
def seeded_registry(tmp_path):
    registry = PhysicalDeviceRegistry(tmp_path / "registry")
    registry.register_physical_unit(
        physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG",
        manufacturer="Texas Instruments", model="CC2650", operator_declaration_id="decl-2026-07-24-001",
        first_registered_at="2026-07-24T00:00:00Z",
    )
    registry.declare_binding(
        project_id=PROJECT_ID, address=TARGET_ADDRESS, address_type="public", physical_unit_id="CC2650-UNIT-01",
        evidence=LabelEvidenceItem(source_type="OPERATOR_DECLARATION", artifact_id="decl-2026-07-24-001", timestamp="2026-07-24T00:00:00Z", strength="DOCUMENTARY", description="Operator-declared public address of CC2650-UNIT-01"),
        decided_at="2026-07-24T00:00:00Z",
    )
    return registry


@pytest.fixture
def stage(seeded_registry, tmp_path):
    return EvidenceStage(CAPTURE_ROOT, SESSION_ROOT, tmp_path / "packet_analysis_out", seeded_registry)


def test_build_examples_produces_one_pair_per_crc_valid_packet(stage, capture):
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    assert len(pairs) == 539


def test_build_examples_rejects_a_ble_channel_that_does_not_match_the_capture_frequency(stage, capture):
    """P0.5 correction (2026-08-08): this real capture was actually acquired
    at 2402000000 Hz (channel 37) -- claiming ble_channel=38 (2426000000 Hz)
    for it must be rejected outright, not silently stamped onto every
    resulting ExampleRecord."""
    with pytest.raises(ValueError, match="BLE_CHANNEL_FREQUENCY_MISMATCH"):
        stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=38)


def test_strong_target_matches_resolve_to_the_registered_physical_unit(stage, capture):
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    strong = [(ex, ann) for ex, ann in pairs if ex.association_status == "STRONG"]
    assert len(strong) == 4
    for example, annotation in strong:
        assert example.physical_unit_id == "CC2650-UNIT-01"
        assert example.quality_status == "PASSED"
        assert annotation.label_decision.label == "CC2650-UNIT-01"
        assert annotation.label_decision.decision_status == "CONFIRMED"
        assert len(annotation.label_evidence) == 2  # B200 packet + Windows corroboration
        assert {item.source_type for item in annotation.label_evidence} == {"B200_PACKET", "WINDOWS_OBSERVATION"}


def test_example_id_is_independent_of_the_assigned_label(stage, capture):
    """The whole point of the corrected contract: rerunning Evidence Stage
    with an EMPTY registry (nothing bound yet, so every label collapses to
    UNKNOWN_ENVIRONMENTAL_TRANSMITTER) must still produce the exact same
    example_id values -- identity comes only from evidence, never label."""
    with_labels = {ex.example_id: ex for ex, _ in stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)}

    empty_registry = PhysicalDeviceRegistry(stage.registry.root.parent / "empty_registry")
    unlabeled_stage = EvidenceStage(CAPTURE_ROOT, SESSION_ROOT, stage.service.analysis_root, empty_registry)
    without_labels = {ex.example_id: ex for ex, _ in unlabeled_stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)}

    assert set(with_labels.keys()) == set(without_labels.keys())
    strong_example_id = next(ex.example_id for ex in with_labels.values() if ex.association_status == "STRONG")
    assert with_labels[strong_example_id].physical_unit_id == "CC2650-UNIT-01"
    assert without_labels[strong_example_id].physical_unit_id is None
    # Same iq_start_sample/iq_end_sample/candidate_id/packet_id either way.
    assert with_labels[strong_example_id].iq_start_sample == without_labels[strong_example_id].iq_start_sample
    assert with_labels[strong_example_id].iq_end_sample == without_labels[strong_example_id].iq_end_sample


def test_iq_end_sample_is_after_iq_start_sample_for_every_example(stage, capture):
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    for example, _ in pairs:
        assert example.iq_end_sample > example.iq_start_sample


def test_no_example_is_auto_promoted_to_eligible(stage, capture):
    """Evidence Stage must never hand out ELIGIBLE itself -- that requires
    the Fase 2 Dataset Builder gate (leakage/duplicates/session-split)."""
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    assert all(ex.dataset_eligibility != "ELIGIBLE" for ex, _ in pairs)


def test_background_transmitters_are_not_labeled_as_the_target(stage, capture):
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    background = [(ex, ann) for ex, ann in pairs if ex.logical_transmitter_id and TARGET_ADDRESS.replace(":", "") not in ex.logical_transmitter_id]
    assert background  # the capture really does contain other transmitters
    for example, annotation in background:
        assert example.physical_unit_id is None
        assert annotation.label_decision.label == "UNKNOWN_ENVIRONMENTAL_TRANSMITTER"
        assert annotation.label_decision.decision_status in ("PROVISIONAL", "AMBIGUOUS")


def test_physical_isolation_declared_labels_every_packet_to_that_unit_regardless_of_address(seeded_registry):
    """Real BLE devices can rotate a radio-layer address that never matches
    what a native OS BLE stack resolves and displays -- address-based
    AddressBinding matching then structurally cannot label them (observed
    directly: 0/4 real capture sessions this project ran produced an address
    match, including one where the target was independently confirmed
    broadcasting seconds before capture). Physical isolation is the
    alternative ground truth: the operator declares only one unit was
    transmitting nearby for the whole capture, so every recovered packet is
    attributed to it -- not because its address matched, but because no
    other transmitter could plausibly be the source.
    """
    isolated_capture = CaptureStage(CAPTURE_ROOT).build_capture_record(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        isolation_declared_physical_unit_id="CC2650-UNIT-01",
    )
    stage = EvidenceStage(CAPTURE_ROOT, SESSION_ROOT, Path(seeded_registry.root).parent / "packet_analysis_out", seeded_registry)
    pairs = stage.build_examples(capture=isolated_capture, project_id=PROJECT_ID, ble_channel=37)

    assert len(pairs) == 539  # same real packets as the address-matched test above
    for example, annotation in pairs:
        assert example.association_status == "PHYSICAL_ISOLATION_DECLARED"
        assert example.physical_unit_id == "CC2650-UNIT-01"
        assert annotation.label_decision.label == "CC2650-UNIT-01"
        assert annotation.label_decision.decision_status == "CONFIRMED"
        assert any(item.source_type == "OPERATOR_DECLARATION" for item in annotation.label_evidence)
        # Never silently conflated with an address-corroborated STRONG match.
        assert "isolation" in annotation.label_decision.decision_reason.lower()


def test_background_environment_never_links_evidence_as_positive_for_the_declared_absent_target(stage):
    """The same 4 packets that address-match CC2650-UNIT-01 in
    test_strong_target_matches_resolve_to_the_registered_physical_unit are a
    real, honest contradiction here: the operator declared that unit
    off/removed for this whole capture, so an address match must never be
    silently trusted over that declaration to produce a positive example."""
    background_capture = CaptureStage(CAPTURE_ROOT).build_capture_record(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        target_reference_id="CC2650-UNIT-01", dataset_role="NEGATIVE_CANDIDATE",
    )
    pairs = stage.build_examples(capture=background_capture, project_id=PROJECT_ID, ble_channel=37)

    # Not just the 4 STRONG-association packets -- EVERY packet from the
    # declared-absent unit's bound address is a contradiction here, since
    # physical_unit_id resolves from the address binding regardless of
    # Windows-corroboration strength (see _build_example).
    contradictions = [(ex, ann) for ex, ann in pairs if ex.logical_transmitter_id and TARGET_ADDRESS.replace(":", "") in ex.logical_transmitter_id]
    assert len(contradictions) == 122
    contradiction_reasons = set()
    for example, annotation in contradictions:
        assert example.physical_unit_id is None
        assert example.association_status == "CONFLICT"
        assert example.dataset_eligibility == "QUARANTINED"
        assert annotation.label_decision.label == "UNKNOWN_ENVIRONMENTAL_TRANSMITTER"
        assert annotation.label_decision.decision_status == "AMBIGUOUS"
        contradiction_reasons.add(annotation.label_decision.decision_reason)
    # At least one of them is our new override (a real address match the
    # operator's declaration contradicts) rather than a pre-existing native
    # MULTIPLE_NATIVE_CALLBACKS conflict -- both are legitimately possible in
    # real data, but the override's own reason text must actually appear.
    assert any("contradiction" in reason.lower() for reason in contradiction_reasons)

    # Every other (genuinely background) packet in the capture is completely
    # unaffected by the override -- it only ever touches the declared unit.
    others = [(ex, ann) for ex, ann in pairs if (ex, ann) not in contradictions]
    assert others
    for example, _ in others:
        assert example.physical_unit_id is None
        assert example.association_status != "PHYSICAL_ISOLATION_DECLARED"


def test_background_environment_without_a_target_reference_id_is_unaffected(stage):
    """No unit was named as "the one that's off" -- e.g. a pure ambient/noise
    capture -- so there is nothing to contradict, and ordinary address-based
    association proceeds exactly like a legacy/TARGET_DEVICE capture would."""
    background_capture = CaptureStage(CAPTURE_ROOT).build_capture_record(
        capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        dataset_role="NEGATIVE_CANDIDATE",
    )
    pairs = stage.build_examples(capture=background_capture, project_id=PROJECT_ID, ble_channel=37)
    strong = [(ex, ann) for ex, ann in pairs if ex.association_status == "STRONG"]
    assert len(strong) == 4
    for example, _ in strong:
        assert example.physical_unit_id == "CC2650-UNIT-01"


def test_physical_isolation_declared_is_off_by_default(stage, capture):
    assert capture.isolation_declared_physical_unit_id is None
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    assert all(ex.association_status != "PHYSICAL_ISOLATION_DECLARED" for ex, _ in pairs)


def test_every_example_round_trips_through_canonical_json(stage, capture):
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    import json
    from app.modules.ble_rffi_studio.contracts import ExampleAnnotation, ExampleRecord
    for example, annotation in pairs[:20]:  # full 539 round-trip is redundant with the schema already verified in Fase 0
        assert ExampleRecord.model_validate(json.loads(example.canonical_json())) == example
        assert ExampleAnnotation.model_validate(json.loads(annotation.canonical_json())) == annotation
