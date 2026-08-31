"""Pruebas A-D from the reviewer's follow-up: the capture-level decision
state machine (StudioRepository._capture_decision) must reach an honest
verdict immediately from a capture's OWN evidence, not discover a missing
class only later at dataset/training time. These write examples/annotations
directly (the same pattern test_studio_repository_capture_hygiene.py and
test_data_origin_gating.py already use) rather than running EvidenceStage
itself, since the point under test is the decision logic that CONSUMES
already-built evidence, not evidence construction.

Prueba E (a real, physical B200 campaign confirming both classes end to end)
is intentionally NOT here -- it requires the operator's own hardware action
and cannot be fabricated (see prepare_and_train's synthetic end-to-end test
in test_prepare_and_train.py for the software-pipeline-only equivalent,
explicitly labeled data_origin=SYNTHETIC_TEST_ONLY there).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import ExampleAnnotation, LabelDecision, LabelEvidenceItem

from ._helpers import make_example

PROJECT_ID = "BLE-RFFI-TEST"


def _write_manifest(capture_root: Path, capture_id: str) -> Path:
    capture_dir = capture_root / capture_id
    capture_dir.mkdir(parents=True)
    manifest = {
        "capture_id": capture_id, "created_at_utc": "2026-07-28T00:00:00Z",
        "overflow_count": 0, "discontinuity_count": 0, "short_read_count": 0, "write_error_count": 0,
        "hash_status": "VERIFIED", "metadata_status": "COMPLETE",
        "sample_rate_sps": 4_000_000, "actual_samples": 40_000_000, "actual_size_bytes": 320_000_000,
        "ble_channel": 37, "center_frequency_hz": 2_402_000_000, "bandwidth_hz": 2_000_000,
        "sample_count": 40_000_000, "data_path": "iq_data.cf32", "file_size": 512,
        "data_sha256": "0" * 64,
    }
    (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (capture_dir / "iq_data.cf32").write_bytes(b"\x00" * 64)
    return capture_dir


def _annotation_for(example, *, label: str, decision_status: str, reason: str) -> ExampleAnnotation:
    return ExampleAnnotation(
        annotation_id=ExampleAnnotation.make_annotation_id(example.example_id, 1),
        example_id=example.example_id, annotation_version=1,
        label_evidence=[LabelEvidenceItem(source_type="B200_PACKET", artifact_id=example.candidate_id, timestamp=example.created_at, strength="WEAK", description="test")],
        label_decision=LabelDecision(label=label, decision_status=decision_status, decision_reason=reason, decided_by="test", decided_at=example.created_at),
        created_at=example.created_at,
    )


def _seed_evidence(repository: StudioRepository, capture_id: str, examples, annotations=None) -> None:
    evidence_dir = repository.evidence_dir / capture_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in examples])
    write_jsonl(evidence_dir / "annotations.jsonl", [a.model_dump(mode="json") for a in (annotations or [])])


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "captures", legacy_session_root=tmp_path / "sessions")


def _row_for(repository, capture_id):
    listing = repository.list_legacy_captures()
    return next(row for row in listing["captures"] if row["capture_id"] == capture_id)


def test_prueba_a_background_target_off_with_target_absent_is_eligible_as_background_never_quarantined(repository):
    capture_id = "BLE-IQ-prueba-a"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-A", session_id="SESSION-A",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        target_reference_id="UNIT-01", dataset_role="NEGATIVE_CANDIDATE",
    )
    # Real ambient BLE fragments recovered, none of them the declared-off unit.
    examples = [make_example(example_index=i, physical_unit_id=None, session_id="SESSION-A", capture_id=capture_id, capture_purpose="BACKGROUND_TARGET_OFF") for i in range(5)]
    _seed_evidence(repository, capture_id, examples)

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "ELIGIBLE_AS_BACKGROUND"
    assert row["target_presence_status"] == "NOT_DETECTED"


def test_prueba_b_target_device_on_with_target_detected_is_eligible_as_positive(repository):
    capture_id = "BLE-IQ-prueba-b"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-B", session_id="SESSION-B",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        target_reference_id="UNIT-01", dataset_role="POSITIVE_CANDIDATE",
    )
    examples = [make_example(example_index=i, physical_unit_id="UNIT-01", session_id="SESSION-B", capture_id=capture_id, capture_purpose="TARGET_DEVICE_ON") for i in range(5)]
    _seed_evidence(repository, capture_id, examples)

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "ELIGIBLE_AS_POSITIVE"
    assert row["target_presence_status"] == "DETECTED"


def test_prueba_c_target_device_on_with_target_not_detected_needs_repetition_never_becomes_background(repository):
    capture_id = "BLE-IQ-prueba-c"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-C", session_id="SESSION-C",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        target_reference_id="UNIT-01", dataset_role="POSITIVE_CANDIDATE",
    )
    # Some ambient traffic recovered, but never the declared target unit.
    examples = [make_example(example_index=i, physical_unit_id=None, session_id="SESSION-C", capture_id=capture_id, capture_purpose="TARGET_DEVICE_ON") for i in range(5)]
    _seed_evidence(repository, capture_id, examples)

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "REPETITION_NEEDED"
    assert row["target_presence_status"] == "NOT_DETECTED"
    assert row["repair_guidance"]
    assert any(item["code"] == "TARGET_NOT_DETECTED" for item in row["repair_guidance"])


def test_target_device_on_with_native_correlation_ambiguity_is_quarantined_ambiguous_not_contradiction(repository):
    # The real bug this test guards against: a TARGET_DEVICE_ON capture has
    # no declared-absence claim to contradict at all, so a stray
    # MULTIPLE_NATIVE_CALLBACKS ambiguity (a busy RF environment, unrelated
    # to anything the operator declared) must never be labeled "QUARANTINED"
    # (which this module reserves for the one real, provable contradiction:
    # a BACKGROUND_TARGET_OFF capture whose declared-off target actually
    # showed up). It gets its own, honestly-named code instead.
    capture_id = "BLE-IQ-ambiguous-target"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-AMB", session_id="SESSION-AMB",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        target_reference_id="UNIT-01", dataset_role="POSITIVE_CANDIDATE",
    )
    # No positive match anywhere, and one example fell into the generic
    # native-scan-ambiguity bucket -- never the declared-off-target-detected
    # contradiction (this capture_purpose has no such concept).
    ambiguous = make_example(
        example_index=0, physical_unit_id=None, session_id="SESSION-AMB", capture_id=capture_id,
        capture_purpose="TARGET_DEVICE_ON", association_status="CONFLICT", dataset_eligibility="QUARANTINED",
    )
    annotation = _annotation_for(
        ambiguous, label="UNKNOWN_ENVIRONMENTAL_TRANSMITTER", decision_status="AMBIGUOUS",
        reason="Multiple native Windows callbacks fell inside the same association time window (MULTIPLE_NATIVE_CALLBACKS).",
    )
    clean = [make_example(example_index=i, physical_unit_id=None, session_id="SESSION-AMB", capture_id=capture_id, capture_purpose="TARGET_DEVICE_ON") for i in range(1, 6)]
    _seed_evidence(repository, capture_id, [ambiguous, *clean], [annotation])

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "QUARANTINED_AMBIGUOUS"
    assert row["target_presence_status"] == "INCONCLUSIVE"
    assert any(item["code"] == "NATIVE_CORRELATION_AMBIGUOUS" for item in row["repair_guidance"])


def test_prueba_d_background_target_off_with_target_detected_is_quarantined_for_contradiction(repository):
    capture_id = "BLE-IQ-prueba-d"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-D", session_id="SESSION-D",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        target_reference_id="UNIT-01", dataset_role="NEGATIVE_CANDIDATE",
    )
    # The declared-off unit was actually detected with strong evidence --
    # EvidenceStage would have overridden this to CONFLICT/quarantined and
    # written an annotation whose reason mentions the contradiction; that
    # override is reproduced directly here rather than re-running EvidenceStage.
    contradicted = make_example(
        example_index=0, physical_unit_id=None, session_id="SESSION-D", capture_id=capture_id,
        capture_purpose="BACKGROUND_TARGET_OFF", association_status="CONFLICT", dataset_eligibility="QUARANTINED",
    )
    annotation = _annotation_for(
        contradicted, label="UNKNOWN_ENVIRONMENTAL_TRANSMITTER", decision_status="AMBIGUOUS",
        reason="Address matched UNIT-01, but the operator declared that unit powered off/removed -- a contradiction.",
    )
    # Plenty of genuinely unrelated, clean background traffic elsewhere in
    # the same capture -- must NOT rescue the verdict; the contradiction
    # about THIS specific claim still quarantines the whole capture.
    clean = [make_example(example_index=i, physical_unit_id=None, session_id="SESSION-D", capture_id=capture_id, capture_purpose="BACKGROUND_TARGET_OFF") for i in range(1, 6)]
    _seed_evidence(repository, capture_id, [contradicted, *clean], [annotation])

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "QUARANTINED"
    assert row["target_presence_status"] == "DETECTED"


def test_background_target_off_with_technically_clean_but_insufficient_fragments_is_control_only(repository):
    capture_id = "BLE-IQ-control-only"
    _write_manifest(repository.legacy_capture_root, capture_id)
    repository.build_capture(
        capture_id=capture_id, project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-CO", session_id="SESSION-CO",
        capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
        target_reference_id="UNIT-01", dataset_role="NEGATIVE_CANDIDATE",
    )
    _seed_evidence(repository, capture_id, [])  # nothing recovered at all -- technically clean, just empty

    row = _row_for(repository, capture_id)
    assert row["capture_decision"] == "CONTROL_ONLY"
    assert row["target_presence_status"] == "NOT_DETECTED"
    assert any(item["code"] == "INSUFFICIENT_BLE_ACTIVITY" for item in row["repair_guidance"])
