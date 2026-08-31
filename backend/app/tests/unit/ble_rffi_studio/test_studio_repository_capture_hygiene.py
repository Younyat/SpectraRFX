"""Two real, related problems found operating the Guided UI at scale:

1. The campaign retry loop (CampaignOrchestrator, ~46% measured single-
   attempt RF overflow rate) leaves a real, complete capture_manifest.json
   behind for every failed attempt, not just the one that finally succeeded
   -- only the successful capture_id ever gets a Studio CaptureRecord built.
   Those orphaned failed attempts showed up in the Guided captures list as
   "Sin clasificar", indistinguishable from a real capture the operator just
   hadn't gotten to yet, even though there is nothing to analyze in them.

2. Those orphaned captures accumulate real IQ files (hundreds of MB each)
   with no way to clean them up short of touching the filesystem directly.

These tests use a fully synthetic, isolated legacy_capture_root (never the
shared real fixture other tests reuse) since they create and delete capture
directories.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository

PROJECT_ID = "BLE-RFFI-TEST"


def _write_manifest(capture_root: Path, capture_id: str, *, overflow_count: int = 0, hash_status: str = "VERIFIED") -> Path:
    capture_dir = capture_root / capture_id
    capture_dir.mkdir(parents=True)
    manifest = {
        "capture_id": capture_id, "created_at_utc": "2026-07-27T00:00:00Z",
        "overflow_count": overflow_count, "discontinuity_count": 0, "short_read_count": 0, "write_error_count": 0,
        "hash_status": hash_status, "metadata_status": "COMPLETE",
        "sample_rate_sps": 4_000_000, "actual_samples": 40_000_000, "actual_size_bytes": 320_000_000,
        "ble_channel": 37, "center_frequency_hz": 2_402_000_000, "bandwidth_hz": 2_000_000,
        "sample_count": 40_000_000, "data_path": "iq_data.cf32", "file_size": 512,
        "data_sha256": "0" * 64,
    }
    (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (capture_dir / "iq_data.cf32").write_bytes(b"\x00" * 64)
    return capture_dir


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "captures", legacy_session_root=tmp_path / "sessions")


def _row_for(repository, capture_id):
    listing = repository.list_legacy_captures()
    return next(row for row in listing["captures"] if row["capture_id"] == capture_id)


def test_a_failed_quality_capture_that_was_never_built_is_labeled_as_discarded(repository):
    _write_manifest(repository.legacy_capture_root, "BLE-IQ-failed-retry", overflow_count=3)
    row = _row_for(repository, "BLE-IQ-failed-retry")
    assert row["acquisition_quality"] == "FAILED"
    assert row["capture_type_label"] == "Descartada (fallo de adquisicion RF)"
    assert row["capture_decision"] == "NOT_ANALYZED_YET"


def test_a_passed_quality_capture_that_was_never_built_stays_genuinely_unclassified(repository):
    _write_manifest(repository.legacy_capture_root, "BLE-IQ-real-unused", overflow_count=0)
    row = _row_for(repository, "BLE-IQ-real-unused")
    assert row["acquisition_quality"] == "PASSED"
    assert row["capture_type_label"] == "Sin clasificar"


def test_a_failed_quality_capture_keeps_its_real_label_once_deliberately_built(repository):
    _write_manifest(repository.legacy_capture_root, "BLE-IQ-failed-but-used", overflow_count=2)
    repository.build_capture(
        capture_id="BLE-IQ-failed-but-used", project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-TEST", session_id="SESSION-TEST",
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON", target_reference_id="UNIT-01", dataset_role="POSITIVE_CANDIDATE",
    )
    row = _row_for(repository, "BLE-IQ-failed-but-used")
    # An operator who deliberately built a CaptureRecord for a FAILED-quality
    # capture (rare, e.g. investigating the overflow itself) sees their own
    # real declaration, never silently overridden to "discarded".
    assert row["capture_type_label"] == "Dispositivo encendido"


def test_delete_legacy_capture_removes_the_directory(repository):
    capture_dir = _write_manifest(repository.legacy_capture_root, "BLE-IQ-to-delete")
    assert capture_dir.is_dir()

    result = repository.delete_legacy_capture("BLE-IQ-to-delete")

    assert result == {"deleted": True, "capture_id": "BLE-IQ-to-delete"}
    assert not capture_dir.exists()
    assert not any(row["capture_id"] == "BLE-IQ-to-delete" for row in repository.list_legacy_captures()["captures"])


def test_delete_legacy_capture_also_removes_capturerecord_and_evidence(repository):
    _write_manifest(repository.legacy_capture_root, "BLE-IQ-with-evidence")
    repository.build_capture(capture_id="BLE-IQ-with-evidence", project_id=PROJECT_ID, campaign_id="C1", execution_id="EXEC-TEST", session_id="SESSION-TEST")
    evidence_dir = repository.evidence_dir / "BLE-IQ-with-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "examples.jsonl").write_text("", encoding="utf-8")
    capture_json = repository.captures_dir / "BLE-IQ-with-evidence.json"
    assert capture_json.is_file()

    repository.delete_legacy_capture("BLE-IQ-with-evidence")

    assert not capture_json.exists()
    assert not evidence_dir.exists()


def test_delete_legacy_capture_rejects_path_traversal(repository):
    with pytest.raises(ValueError, match="INVALID_CAPTURE_ID"):
        repository.delete_legacy_capture("../../etc")
    with pytest.raises(ValueError, match="INVALID_CAPTURE_ID"):
        repository.delete_legacy_capture("sub/dir")


def test_delete_legacy_capture_raises_for_a_missing_capture(repository):
    with pytest.raises(FileNotFoundError, match="LEGACY_CAPTURE_NOT_FOUND"):
        repository.delete_legacy_capture("BLE-IQ-never-existed")
