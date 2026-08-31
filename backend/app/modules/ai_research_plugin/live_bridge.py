"""Read-only bridge to the LIVE SDR stream for AI Research Plugin LIVE
inference -- requests a bounded, one-shot raw I/Q snapshot from the SAME
worker subprocess Live Monitor/RF Terrain already use
(RealSpectrumStream.capture_live_iq_snapshot), never opens a second SDR
session (see that method's docstring and spectrum_stream_worker.py's
iq_snapshot_request for the underlying mechanism, modeled directly on the
existing, already-shipped BLE live-check burst path).

Entirely additive: if this bridge is never called, nothing about the live
spectrum stream, Live Monitor, or RF Terrain LIVE mode changes.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


class LiveIqBridgeError(Exception):
    pass


class SupportsLiveIqSnapshot(Protocol):
    def capture_live_iq_snapshot(self, analyzer_settings: Any, sample_count: int, timeout_seconds: float) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class LiveIqSnapshot:
    re: np.ndarray
    im: np.ndarray
    sample_rate_hz: float
    center_frequency_hz: float
    timestamp_utc: str
    # A real, verifiable hash of the exact snapshot bytes -- reproducibility
    # anchor for an otherwise-ephemeral live capture (there is no stored
    # file for a LIVE run to point back to, unlike the OFFLINE capture
    # bridge's real data_sha256 from capture_manifest.json).
    data_sha256: str


class LiveIqBridge:
    def __init__(self, stream: SupportsLiveIqSnapshot, analyzer_settings: Any) -> None:
        self._stream = stream
        self._analyzer_settings = analyzer_settings

    async def capture_snapshot(self, sample_count: int, timeout_seconds: float = 5.0) -> LiveIqSnapshot:
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(
            None, self._stream.capture_live_iq_snapshot, self._analyzer_settings, sample_count, timeout_seconds,
        )
        if frame is None:
            raise LiveIqBridgeError(
                "Timed out waiting for a live I/Q snapshot from the SDR worker -- "
                "is a real device connected and streaming?"
            )
        if frame.get("sample_format") != "cf32_le":
            raise LiveIqBridgeError(f"Unexpected live snapshot sample_format: {frame.get('sample_format')!r}")

        raw_bytes = base64.b64decode(frame["iq_window_base64"])
        interleaved = np.frombuffer(raw_bytes, dtype="<f4").reshape(-1, 2)
        return LiveIqSnapshot(
            re=interleaved[:, 0].copy(),
            im=interleaved[:, 1].copy(),
            sample_rate_hz=float(frame["sample_rate_hz"]),
            center_frequency_hz=float(frame["center_frequency_hz"]),
            timestamp_utc=str(frame["timestamp_utc"]),
            data_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
