"""Read-only bridge from the AI Research Plugin to the platform's REAL,
already-existing BLE I/Q capture store (`BleCaptureJobManager`).

Every function here only ever calls `.list_captures()`, `.metadata()`, or
`.data_path()` on the manager and only ever opens that path in `"rb"`
mode -- never a write, never a mutating method, never anything that could
touch the SDR (spec section 22: "no controla adquisición SDR"). The
manager instance itself is the SAME shared one `ble_lab`/`ble_rffi_studio`
already use (via `get_shared_managers()`), so this plugin never
constructs a second, competing manager against the same physical
receiver.

Scope note: the only real, existing preserved-capture format on this
platform today is the BLE campaign's `cf32_le` I/Q store -- the same one
RF Terrain 3D's Offline Reconstruction feature reads. "RF capture" in
this bridge means specifically that; a generic multi-protocol capture
store does not exist yet, so this module does not invent one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

BYTES_PER_CF32LE_SAMPLE = 8


class CaptureBridgeError(Exception):
    pass


@dataclass(frozen=True)
class CaptureRegion:
    re: np.ndarray
    im: np.ndarray
    sample_rate_hz: float
    start_sample_index: int
    end_sample_index: int


class ReadOnlyCaptureBridge:
    def __init__(self, capture_manager: Any | None) -> None:
        self._capture_manager = capture_manager

    @property
    def available(self) -> bool:
        return self._capture_manager is not None

    def _require_manager(self) -> Any:
        if self._capture_manager is None:
            raise CaptureBridgeError(
                "No capture manager available (ble_lab module did not initialize one) -- "
                "the AI Research Plugin has no real captures to read."
            )
        return self._capture_manager

    def list_captures(self) -> list[dict]:
        return self._require_manager().list_captures()

    def get_metadata(self, capture_id: str) -> dict:
        manager = self._require_manager()
        try:
            return manager.metadata(capture_id)
        except CaptureBridgeError:
            raise
        except Exception as error:  # real, manager-specific exception types (e.g. missing capture directory)
            raise CaptureBridgeError(f"Failed to read metadata for capture {capture_id!r}: {error}") from error

    def read_region(self, capture_id: str, t0_seconds: float, t1_seconds: float) -> CaptureRegion:
        metadata = self.get_metadata(capture_id)

        sample_format = metadata.get("sample_format")
        if sample_format != "cf32_le":
            raise CaptureBridgeError(
                f"Unsupported capture sample_format {sample_format!r} -- only cf32_le is implemented"
            )
        sample_rate_hz = float(metadata.get("sample_rate_sps") or 0.0)
        if sample_rate_hz <= 0:
            raise CaptureBridgeError(f"Capture {capture_id!r} has no valid sample_rate_sps")

        total_samples = metadata.get("actual_samples")
        if not total_samples:
            size_bytes = metadata.get("actual_size_bytes")
            total_samples = (size_bytes // BYTES_PER_CF32LE_SAMPLE) if size_bytes else 0
        if not total_samples:
            raise CaptureBridgeError(f"Capture {capture_id!r} has no determinable sample count")

        if t1_seconds <= t0_seconds:
            raise CaptureBridgeError(f"Invalid region: t0={t0_seconds} must be < t1={t1_seconds}")

        start_sample = max(0, int(np.floor(t0_seconds * sample_rate_hz)))
        end_sample = min(int(total_samples), int(np.ceil(t1_seconds * sample_rate_hz)))
        if end_sample <= start_sample:
            raise CaptureBridgeError(
                f"Requested region [{t0_seconds}, {t1_seconds}]s falls entirely outside the "
                f"capture's real duration (0..{total_samples / sample_rate_hz:.3f}s)"
            )

        manager = self._require_manager()
        try:
            data_path = manager.data_path(capture_id)
        except Exception as error:
            raise CaptureBridgeError(f"Failed to resolve data path for capture {capture_id!r}: {error}") from error
        byte_offset = start_sample * BYTES_PER_CF32LE_SAMPLE
        byte_count = (end_sample - start_sample) * BYTES_PER_CF32LE_SAMPLE
        with open(data_path, "rb") as handle:  # read-only, never write mode
            handle.seek(byte_offset)
            raw = handle.read(byte_count)
        if len(raw) != byte_count:
            raise CaptureBridgeError(
                f"Short read for capture {capture_id!r}: expected {byte_count} bytes, got {len(raw)}"
            )

        interleaved = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
        return CaptureRegion(
            re=interleaved[:, 0].copy(),
            im=interleaved[:, 1].copy(),
            sample_rate_hz=sample_rate_hz,
            start_sample_index=start_sample,
            end_sample_index=end_sample,
        )
