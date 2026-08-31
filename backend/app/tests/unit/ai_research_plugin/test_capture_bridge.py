from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.ai_research_plugin.capture_bridge import CaptureBridgeError, ReadOnlyCaptureBridge

SAMPLE_RATE_HZ = 2_000_000.0
N_SAMPLES = 20_000


class FakeCaptureManager:
    """Duck-types the exact read-only surface ReadOnlyCaptureBridge calls
    on the real BleCaptureJobManager (list_captures/metadata/data_path) --
    the real manager needs live SDR device objects to construct, so unit
    tests exercise this plugin's own bridge code against a fake that
    matches its real, narrow, read-only interface instead."""

    def __init__(self, data_path: Path, metadata: dict):
        self._data_path = data_path
        self._metadata = metadata

    def list_captures(self):
        return [self._metadata]

    def metadata(self, capture_id: str):
        assert capture_id == self._metadata["capture_id"]
        return self._metadata

    def data_path(self, capture_id: str) -> Path:
        assert capture_id == self._metadata["capture_id"]
        return self._data_path


def _write_cf32le_tone(path: Path, n_samples: int, freq_hz: float) -> None:
    n = np.arange(n_samples)
    phase = 2 * np.pi * freq_hz * n / SAMPLE_RATE_HZ
    re = np.cos(phase).astype(np.float32)
    im = np.sin(phase).astype(np.float32)
    interleaved = np.empty(n_samples * 2, dtype=np.float32)
    interleaved[0::2] = re
    interleaved[1::2] = im
    path.write_bytes(interleaved.tobytes())


@pytest.fixture
def bridge(tmp_path: Path) -> ReadOnlyCaptureBridge:
    data_path = tmp_path / "BLE-IQ-test.sigmf-data"
    _write_cf32le_tone(data_path, N_SAMPLES, freq_hz=50_000)
    metadata = {
        "capture_id": "BLE-IQ-test",
        "sample_format": "cf32_le",
        "sample_rate_sps": SAMPLE_RATE_HZ,
        "actual_samples": N_SAMPLES,
    }
    manager = FakeCaptureManager(data_path, metadata)
    return ReadOnlyCaptureBridge(manager)


def test_unavailable_when_no_manager_was_injected():
    bridge = ReadOnlyCaptureBridge(None)
    assert bridge.available is False
    with pytest.raises(CaptureBridgeError):
        bridge.list_captures()


def test_list_and_metadata_pass_through_to_the_real_manager(bridge: ReadOnlyCaptureBridge):
    assert bridge.available is True
    captures = bridge.list_captures()
    assert captures[0]["capture_id"] == "BLE-IQ-test"
    metadata = bridge.get_metadata("BLE-IQ-test")
    assert metadata["sample_rate_sps"] == SAMPLE_RATE_HZ


def test_read_region_returns_the_real_bytes_for_the_requested_time_window(bridge: ReadOnlyCaptureBridge):
    region = bridge.read_region("BLE-IQ-test", t0_seconds=0.001, t1_seconds=0.002)
    expected_start = int(0.001 * SAMPLE_RATE_HZ)
    expected_end = int(np.ceil(0.002 * SAMPLE_RATE_HZ))
    assert region.start_sample_index == expected_start
    assert region.end_sample_index == expected_end
    assert len(region.re) == expected_end - expected_start
    assert region.sample_rate_hz == SAMPLE_RATE_HZ


def test_read_region_matches_the_real_tone_written_to_disk(bridge: ReadOnlyCaptureBridge):
    region = bridge.read_region("BLE-IQ-test", t0_seconds=0.0, t1_seconds=N_SAMPLES / SAMPLE_RATE_HZ)
    n = np.arange(len(region.re))
    expected_phase = 2 * np.pi * 50_000 * n / SAMPLE_RATE_HZ
    np.testing.assert_allclose(region.re, np.cos(expected_phase), atol=1e-5)
    np.testing.assert_allclose(region.im, np.sin(expected_phase), atol=1e-5)


def test_rejects_an_inverted_time_range(bridge: ReadOnlyCaptureBridge):
    with pytest.raises(CaptureBridgeError, match="t0"):
        bridge.read_region("BLE-IQ-test", t0_seconds=0.002, t1_seconds=0.001)


def test_rejects_a_region_entirely_outside_the_real_capture_duration(bridge: ReadOnlyCaptureBridge):
    capture_duration_s = N_SAMPLES / SAMPLE_RATE_HZ
    with pytest.raises(CaptureBridgeError, match="outside"):
        bridge.read_region("BLE-IQ-test", t0_seconds=capture_duration_s + 1, t1_seconds=capture_duration_s + 2)


def test_fails_closed_for_an_unsupported_sample_format(tmp_path: Path):
    data_path = tmp_path / "bad.sigmf-data"
    data_path.write_bytes(b"\x00" * 100)
    manager = FakeCaptureManager(data_path, {
        "capture_id": "BLE-IQ-bad", "sample_format": "ci16_le", "sample_rate_sps": SAMPLE_RATE_HZ, "actual_samples": 10,
    })
    bridge = ReadOnlyCaptureBridge(manager)
    with pytest.raises(CaptureBridgeError, match="ci16_le"):
        bridge.read_region("BLE-IQ-bad", 0.0, 0.001)
