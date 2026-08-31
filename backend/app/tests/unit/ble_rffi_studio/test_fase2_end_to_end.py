"""End-to-end Fase 2 demonstration against the real BLE-IQ-e8edc49b59a0
capture: capture -> evidence -> frozen dataset -> quality report -> split.

This capture has exactly ONE physical unit and ONE session (S001-POS), so
every scientific_task's split MUST come back NOT_FEASIBLE -- that is the
correct, honest behavior of the design (never fabricate a 3-way split from
one session), not a bug. The dataset-level quality gate (duplicates/overlap)
is independent of split feasibility and can still pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.acquisition.capture_stage import CaptureStage
from app.modules.ble_rffi_studio.contracts import LabelEvidenceItem
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.evidence.evidence_stage import EvidenceStage
from app.modules.ble_rffi_studio.quality import DatasetAnalyzer, SplitBuilder
from app.modules.ble_rffi_studio.registry import PhysicalDeviceRegistry

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
SESSION_ROOT = STORAGE_ROOT / "ble_lab" / "sessions"
REAL_CAPTURE_ID = "BLE-IQ-e8edc49b59a0"
PROJECT_ID = "BLE-RFFI-CC2650"

pytestmark = pytest.mark.skipif(not (CAPTURE_ROOT / REAL_CAPTURE_ID).is_dir(), reason="real capture fixture not present in this environment")


@pytest.fixture
def real_examples(tmp_path):
    capture = CaptureStage(CAPTURE_ROOT).build_capture_record(capture_id=REAL_CAPTURE_ID, project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01")
    registry = PhysicalDeviceRegistry(tmp_path / "registry")
    registry.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id=PROJECT_ID, device_family="TI_SENSOR_TAG", operator_declaration_id="decl-1", first_registered_at="2026-07-24T00:00:00Z")
    registry.declare_binding(
        project_id=PROJECT_ID, address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01",
        evidence=LabelEvidenceItem(source_type="OPERATOR_DECLARATION", artifact_id="decl-1", timestamp="2026-07-24T00:00:00Z", strength="DOCUMENTARY"),
        decided_at="2026-07-24T00:00:00Z",
    )
    stage = EvidenceStage(CAPTURE_ROOT, SESSION_ROOT, tmp_path / "packet_analysis_out", registry)
    pairs = stage.build_examples(capture=capture, project_id=PROJECT_ID, ble_channel=37)
    return [example for example, _ in pairs]


def test_real_capture_produces_a_valid_frozen_dataset(real_examples, tmp_path):
    builder = DatasetBuilder(tmp_path / "datasets")
    selected, excluded = builder.select_examples(real_examples)
    assert selected  # some examples really do pass Evidence Stage's quality gate
    draft = builder.build_draft(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01", examples=selected, data_origin="REAL_B200", creation_policy={"source": "real_capture_e2e_test"}, created_at="2026-07-26T00:00:00Z")
    frozen = builder.freeze(draft)
    assert frozen.frozen is True
    assert "CC2650-UNIT-01" in frozen.physical_units
    assert len(frozen.sessions) == 1  # only S001-POS


def test_real_capture_dataset_passes_the_quality_gate(real_examples, tmp_path):
    builder = DatasetBuilder(tmp_path / "datasets")
    selected, _ = builder.select_examples(real_examples)
    draft = builder.build_draft(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01", examples=selected, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    frozen = builder.freeze(draft)

    analyzer = DatasetAnalyzer()
    exact = analyzer.check_exact_duplicates(selected)
    overlap = analyzer.check_sample_overlap(selected)
    near = analyzer.check_near_duplicates(selected)  # no IQ paths -> NOT_EXECUTED, non-blocking
    report = analyzer.build_gate(frozen, exact, overlap, near, created_at="2026-07-26T00:00:00Z")

    assert exact.status == "PASSED"  # real evidence-identity fields are genuinely unique per packet
    assert overlap.status == "PASSED"
    assert report.gate_decision == "ACCEPTED_FOR_TRAINING"


@pytest.mark.parametrize("scientific_task", ["SAME_MODEL_UNIT_IDENTIFICATION", "TARGET_VS_BACKGROUND", "UNKNOWN_DEVICE_REJECTION", "MULTI_DEVICE_CLASSIFICATION"])
def test_real_capture_is_honestly_not_feasible_for_every_task_with_only_one_session(real_examples, tmp_path, scientific_task):
    """This capture has 1 physical unit and 1 session -- every task's
    minimum-evidence rule requires more than that, so split_status must be
    NOT_FEASIBLE with a specific reason, never a fabricated 3-way split."""
    builder = DatasetBuilder(tmp_path / "datasets")
    selected, _ = builder.select_examples(real_examples)
    draft = builder.build_draft(dataset_id="BLE-RFFI-CC2650-DS01", dataset_version="1.0.0", project_id=PROJECT_ID, campaign_id="CC2650-CAMPAIGN-01", examples=selected, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    frozen = builder.freeze(draft)

    split_manifest = SplitBuilder().build(dataset=frozen, examples=selected, scientific_task=scientific_task, created_at="2026-07-26T00:00:00Z")
    assert split_manifest.split_status == "NOT_FEASIBLE"
    assert split_manifest.infeasibility_reason
    assert split_manifest.assignments == []
