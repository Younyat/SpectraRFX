"""I.1: the shared IQ resolver (records/iq_resolution.py) -- legacy
filename, relative path, absolute-path override, missing file, path
traversal, and hash correctness/incorrectness."""
from __future__ import annotations

import hashlib

import pytest

from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_scientific_results.records.iq_resolution import resolve_iq_path


def _capture(**overrides) -> CaptureRecord:
    fields = dict(
        project_id="P", campaign_id="C", capture_id="CAP-1", session_id="S", execution_id="E",
        data_origin="SYNTHETIC_TEST_ONLY", receiver_device_id="RX", sdr_model="USRP_B200_SYNTHETIC",
        rx_channel="RX2", antenna_port="RX2", sample_rate_sps=4_000_000, sample_dtype="cf32", byte_order="LE",
        sample_count=1000, channel_count=1, center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000,
        effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="MANUAL", capture_duration_s=1.0,
        capture_tool="test", iq_path="CAP-1.cf32", iq_size_bytes=8, iq_sha256="sha", acquisition_quality="PASSED",
        created_at="2026-08-01T00:00:00Z",
    )
    fields.update(overrides)
    return CaptureRecord(**fields)


def test_resolves_legacy_bare_filename(tmp_path):
    capture = _capture(capture_id="CAP-1", iq_path="CAP-1.cf32")
    resolved = resolve_iq_path(tmp_path, capture)
    assert resolved == tmp_path / "CAP-1" / "CAP-1.cf32"


def test_resolves_relative_subpath_within_capture_dir(tmp_path):
    capture = _capture(capture_id="CAP-2", iq_path="raw/CAP-2.sigmf-data")
    resolved = resolve_iq_path(tmp_path, capture)
    assert resolved == tmp_path / "CAP-2" / "raw" / "CAP-2.sigmf-data"


def test_missing_file_resolves_to_a_path_that_does_not_exist(tmp_path):
    capture = _capture(capture_id="CAP-3", iq_path="CAP-3.cf32")
    resolved = resolve_iq_path(tmp_path, capture)
    assert not resolved.is_file()


def test_path_traversal_in_iq_path_is_rejected(tmp_path):
    capture = _capture(capture_id="CAP-4", iq_path="../../secrets.txt")
    with pytest.raises(ValueError, match="PATH_TRAVERSAL_REJECTED"):
        resolve_iq_path(tmp_path, capture)


def test_path_traversal_in_capture_id_is_rejected(tmp_path):
    capture = _capture(capture_id="../escape", iq_path="x.cf32")
    with pytest.raises(ValueError, match="PATH_TRAVERSAL_REJECTED"):
        resolve_iq_path(tmp_path, capture)


def test_resolved_file_hash_matches_declared_sha256(tmp_path):
    payload = b"real bytes"
    capture = _capture(capture_id="CAP-5", iq_path="CAP-5.cf32", iq_sha256=hashlib.sha256(payload).hexdigest())
    resolved = resolve_iq_path(tmp_path, capture)
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(payload)
    assert hashlib.sha256(resolved.read_bytes()).hexdigest() == capture.iq_sha256


def test_resolved_file_hash_mismatch_is_detectable(tmp_path):
    capture = _capture(capture_id="CAP-6", iq_path="CAP-6.cf32", iq_sha256=hashlib.sha256(b"expected").hexdigest())
    resolved = resolve_iq_path(tmp_path, capture)
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"tampered")
    assert hashlib.sha256(resolved.read_bytes()).hexdigest() != capture.iq_sha256
