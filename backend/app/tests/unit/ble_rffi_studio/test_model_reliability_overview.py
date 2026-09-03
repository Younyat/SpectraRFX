"""get_model_reliability_overview(): a review surface over every bundle ever
exported, real full TEST-split evaluation attached -- unlike
list_live_selectable_bundles() (which silently drops anything not
APPROVED_FOR_LIVE_PILOT), this must show the bad bundles too.

Deliberately a separate file from test_studio_repository_integration.py:
that file's module-level pytestmark skips everything when a specific real
capture fixture isn't present on this machine, which would hide this test
in every environment without that fixture even though it needs nothing but
the synthetic capture seeding path (mirrors that file's own
_seed_synthetic_capture helper exactly).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import read_json, sha256_file, utc_now, write_json, write_jsonl
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.contracts import CaptureRecord, TrainingRun

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def synthetic_repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def _seed_synthetic_capture(repository: StudioRepository, tmp_path: Path):
    raw_iq_dir = tmp_path / "raw_iq"
    raw_iq_dir.mkdir(parents=True, exist_ok=True)
    examples, iq_paths = write_synthetic_capture_iq(raw_iq_dir, units=2, sessions_per_unit=3, examples_per_session=10)
    by_capture: dict[str, list] = {}
    for example in examples:
        by_capture.setdefault(example.capture_id, []).append(example)

    for capture_id, capture_examples in by_capture.items():
        capture_dir = repository.legacy_capture_root / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        src = iq_paths[capture_id]
        dest = capture_dir / "iq.cf32"
        dest.write_bytes(src.read_bytes())
        capture = CaptureRecord(
            project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01", capture_id=capture_id, session_id=capture_examples[0].session_id,
            execution_id=f"EXEC-{capture_id}", data_origin="SYNTHETIC_TEST_ONLY", receiver_device_id="synthetic", sdr_model="synthetic", rx_channel="RX2", antenna_port="RX2",
            sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1_000_000, channel_count=1,
            center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
            capture_duration_s=1.0, capture_tool="synthetic", iq_path="iq.cf32", iq_size_bytes=dest.stat().st_size, iq_sha256=sha256_file(dest),
            acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at=utc_now(),
        )
        write_json(repository.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        capture_evidence_dir = repository.evidence_dir / capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [e.model_dump(mode="json") for e in capture_examples])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [])

    return list(by_capture.keys())


def test_model_reliability_overview_surfaces_real_test_evaluation_for_every_bundle(synthetic_repository, tmp_path):
    repository = synthetic_repository
    capture_ids = _seed_synthetic_capture(repository, tmp_path)
    repository.build_dataset(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01", capture_ids=capture_ids)
    repository.build_quality_report(dataset_id="SYN-DS", dataset_version="1.0.0")
    split = repository.build_split(dataset_id="SYN-DS", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION")
    training_run = TrainingRun(
        training_run_id="run-syn-overview", project_id="SYN-PROJECT", campaign_id="SYN-CAMPAIGN-01",
        dataset_id="SYN-DS", dataset_version="1.0.0", dataset_manifest_sha256="x", split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="SYNTHETIC_TEST_ONLY", operational_use="FORBIDDEN", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    repository.run_training(training_run=training_run)
    repository.evaluate_training_run("run-syn-overview", min_identified_precision=0.7, include_test=True)
    manifest, _ = repository.export_bundle(training_run_id="run-syn-overview", bundle_id="bundle-syn-overview", acceptance_criteria={"min_test_accuracy": 0.0}, model_card_text="# Test")

    overview = repository.get_model_reliability_overview()

    assert len(overview) == 1
    entry = overview[0]
    assert entry["bundle_id"] == "bundle-syn-overview"
    assert entry["training_run_id"] == "run-syn-overview"
    assert entry["approval_status"] == manifest.approval_status
    assert entry["model_type"] == "logistic_regression"
    assert entry["task"] == "SAME_MODEL_UNIT_IDENTIFICATION"
    # Real TEST-split evaluation, read straight from evaluation_report.json --
    # never a collapsed FP/precision pair (that's TARGET_VS_BACKGROUND-only,
    # see _bundle_reliability_summary), and never a value this test invented.
    on_disk = read_json(repository.bundle_builder.root / "bundle-syn-overview" / "evaluation_report.json")["TEST"]
    assert entry["test_evaluation"] == on_disk
    assert entry["test_evaluation"]["accuracy"] > 0.0
    assert "precision_per_class" in entry["test_evaluation"]


def test_model_reliability_overview_is_empty_when_no_bundles_exist(synthetic_repository):
    assert synthetic_repository.get_model_reliability_overview() == []
