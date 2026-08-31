from __future__ import annotations

import asyncio
import base64
import hashlib

import numpy as np
import pytest

from app.modules.ai_research_plugin.live_bridge import LiveIqBridge, LiveIqBridgeError

SAMPLE_RATE_HZ = 2_000_000.0
CENTER_FREQUENCY_HZ = 2_440_000_000.0


def _build_snapshot_frame(n_samples: int, freq_hz: float = 50_000.0) -> dict:
    n = np.arange(n_samples)
    phase = 2 * np.pi * freq_hz * n / SAMPLE_RATE_HZ
    complex_samples = (np.cos(phase) + 1j * np.sin(phase)).astype(np.complex64)
    return {
        "source": "iq_snapshot",
        "request_id": "irrelevant-for-the-bridge",
        "timestamp_utc": "2026-01-01T00:00:00Z",
        "center_frequency_hz": CENTER_FREQUENCY_HZ,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "bandwidth_hz": SAMPLE_RATE_HZ,
        "sample_format": "cf32_le",
        "sample_count": n_samples,
        "iq_window_base64": base64.b64encode(complex_samples.tobytes()).decode("ascii"),
    }


class FakeStream:
    def __init__(self, frame: dict | None):
        self._frame = frame
        self.calls: list[tuple] = []

    def capture_live_iq_snapshot(self, analyzer_settings, sample_count, timeout_seconds):
        self.calls.append((analyzer_settings, sample_count, timeout_seconds))
        return self._frame


def _run(coro):
    return asyncio.run(coro)


def test_decodes_a_real_snapshot_into_matching_re_im_arrays():
    frame = _build_snapshot_frame(256)
    bridge = LiveIqBridge(FakeStream(frame), analyzer_settings="fake-settings")

    snapshot = _run(bridge.capture_snapshot(sample_count=256))

    assert len(snapshot.re) == 256
    assert len(snapshot.im) == 256
    assert snapshot.sample_rate_hz == SAMPLE_RATE_HZ
    assert snapshot.center_frequency_hz == CENTER_FREQUENCY_HZ
    n = np.arange(256)
    expected_phase = 2 * np.pi * 50_000.0 * n / SAMPLE_RATE_HZ
    np.testing.assert_allclose(snapshot.re, np.cos(expected_phase), atol=1e-5)
    np.testing.assert_allclose(snapshot.im, np.sin(expected_phase), atol=1e-5)


def test_data_sha256_is_a_real_hash_of_the_exact_snapshot_bytes():
    frame = _build_snapshot_frame(128)
    bridge = LiveIqBridge(FakeStream(frame), analyzer_settings="fake-settings")

    snapshot = _run(bridge.capture_snapshot(sample_count=128))

    raw_bytes = base64.b64decode(frame["iq_window_base64"])
    assert snapshot.data_sha256 == hashlib.sha256(raw_bytes).hexdigest()


def test_forwards_the_requested_sample_count_and_analyzer_settings_to_the_stream():
    frame = _build_snapshot_frame(64)
    stream = FakeStream(frame)
    bridge = LiveIqBridge(stream, analyzer_settings="my-settings-object")

    _run(bridge.capture_snapshot(sample_count=64, timeout_seconds=2.5))

    assert stream.calls == [("my-settings-object", 64, 2.5)]


def test_raises_a_clear_error_on_timeout_none_from_the_stream():
    bridge = LiveIqBridge(FakeStream(None), analyzer_settings="fake-settings")
    with pytest.raises(LiveIqBridgeError, match="Timed out"):
        _run(bridge.capture_snapshot(sample_count=64))


def test_fails_closed_on_an_unexpected_sample_format():
    frame = _build_snapshot_frame(64)
    frame["sample_format"] = "ci16_le"
    bridge = LiveIqBridge(FakeStream(frame), analyzer_settings="fake-settings")
    with pytest.raises(LiveIqBridgeError, match="ci16_le"):
        _run(bridge.capture_snapshot(sample_count=64))
