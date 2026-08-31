"""Point-1 correction (2026-08-08), end-to-end: StudioRepository.build_capture()
is where receiver_epoch actually gets assigned (sequential knowledge across
sibling captures of the same receiver_identity_id, which capture_stage.py's
single-manifest builder cannot see on its own).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository

PROJECT_ID = "P1"


def _write_manifest(capture_dir: Path, *, capture_id: str, created_at_utc: str, device_serial: str = "E3R04Z1B2", gain_db: float = 20.0) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "capture_id": capture_id, "experimental_metadata": {"session_id": f"S-{capture_id}"},
        "sample_rate_sps": 4_000_000, "sample_format": "cf32_le", "sample_count": 1, "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000, "bytes_per_cpu_sample": 8, "actual_duration_seconds": 1.0, "data_path": "x.sigmf-data",
        "actual_file_size_bytes": 1, "file_size": 1, "data_sha256": f"sha-{capture_id}",
        "created_at_utc": created_at_utc, "b200_rf_started_at": created_at_utc,
        "diagnostic_status": "PASSED", "continuity_status": "PASSED", "hash_status": "VERIFIED", "capture_complete": True,
        "device_serial": device_serial, "hardware": "B200", "antenna": "RX2",
        "gain_configuration": {"gain_db": gain_db, "mode": "manual"},
        "capture_software_revision": "ble-sdr-capture-v3",
    }
    (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_sequential_captures_of_the_same_receiver_close_in_time_share_one_epoch(repository, tmp_path):
    _write_manifest(repository.legacy_capture_root / "CAP-1", capture_id="CAP-1", created_at_utc="2026-08-01T00:00:00Z")
    _write_manifest(repository.legacy_capture_root / "CAP-2", capture_id="CAP-2", created_at_utc="2026-08-01T00:05:00Z")

    c1 = repository.build_capture(capture_id="CAP-1", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1")
    c2 = repository.build_capture(capture_id="CAP-2", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2")

    assert c1.receiver_epoch is not None
    assert c1.receiver_epoch == c2.receiver_epoch


def test_a_capture_after_a_long_gap_gets_a_new_epoch_even_with_the_same_serial(repository, tmp_path):
    _write_manifest(repository.legacy_capture_root / "CAP-1", capture_id="CAP-1", created_at_utc="2026-08-01T00:00:00Z")
    _write_manifest(repository.legacy_capture_root / "CAP-2", capture_id="CAP-2", created_at_utc="2026-08-03T00:00:00Z")

    c1 = repository.build_capture(capture_id="CAP-1", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1")
    c2 = repository.build_capture(capture_id="CAP-2", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2")

    assert c1.receiver_epoch != c2.receiver_epoch
    assert c2.receiver_epoch_boundary_reason == "SESSION_GAP_EXCEEDED"


def test_a_capture_with_a_different_gain_gets_a_new_epoch_even_close_in_time(repository, tmp_path):
    _write_manifest(repository.legacy_capture_root / "CAP-1", capture_id="CAP-1", created_at_utc="2026-08-01T00:00:00Z", gain_db=20.0)
    _write_manifest(repository.legacy_capture_root / "CAP-2", capture_id="CAP-2", created_at_utc="2026-08-01T00:01:00Z", gain_db=30.0)

    c1 = repository.build_capture(capture_id="CAP-1", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1")
    c2 = repository.build_capture(capture_id="CAP-2", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2")

    assert c1.receiver_epoch != c2.receiver_epoch
    assert c2.receiver_epoch_boundary_reason == "QUALIFIED_PROFILE_CHANGED"


def test_epoch_assignment_only_considers_captures_of_the_same_physical_receiver(repository, tmp_path):
    _write_manifest(repository.legacy_capture_root / "CAP-1", capture_id="CAP-1", created_at_utc="2026-08-01T00:00:00Z", device_serial="SERIAL-A")
    _write_manifest(repository.legacy_capture_root / "CAP-2", capture_id="CAP-2", created_at_utc="2026-08-01T00:00:01Z", device_serial="SERIAL-B")

    c1 = repository.build_capture(capture_id="CAP-1", project_id=PROJECT_ID, campaign_id="C1", execution_id="E1")
    c2 = repository.build_capture(capture_id="CAP-2", project_id=PROJECT_ID, campaign_id="C1", execution_id="E2")

    assert c1.receiver_identity_id != c2.receiver_identity_id
    assert c1.receiver_epoch != c2.receiver_epoch
    assert c1.receiver_epoch_boundary_reason == "FIRST_CAPTURE_FOR_IDENTITY"
    assert c2.receiver_epoch_boundary_reason == "FIRST_CAPTURE_FOR_IDENTITY"
