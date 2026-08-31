"""Device Scrubber: removes one registered device's decoded-packet windows
from a real IQ capture, replacing each with a real "quiet" segment (no
decoded packet from ANY device) copied from elsewhere in the SAME recording
-- never a synthetic/averaged fill.

This is the same principle as RFI blanking / gap-filling in radio astronomy
and click removal in audio restoration: a corrupted (here: "wrong device
present") span is replaced with real material already present in the same
recording, never an invented sample. Filling with e.g. the dataset mean was
considered and rejected: a synthetic, near-constant fill is itself a
detectable artifact a classifier can key on -- the exact failure mode this
whole project has spent real effort chasing out (LO-leakage artifact,
cross-device dataset contamination). Borrowed real noise preserves the true
statistical character of the environment; only this one device's footprint
is gone.

Exists specifically for "always-on" devices, where TARGET_VS_BACKGROUND has
no real "device absent" evidence to draw from because the device never turns
off -- see StudioRepository.scrub_device_from_background().

Pure numpy logic only: no filesystem, no manifests. See
scrubbing/capture_deriver.py for turning the edited buffer this module
produces into a new, ingestible legacy capture.
"""
from __future__ import annotations

from typing import TypedDict

import numpy as np

_DTYPE_MAP = {"cf32_le": "<c8", "ci16_le": "<i2", "ci8": "i1"}
# ~8 microseconds at 4 MSps -- far shorter than even a bare 32-bit BLE access
# address (128 samples at 4 MSps), so the blended edge cannot itself
# reconstitute a decodable preamble+access-address; short enough to have no
# material effect on the "device genuinely absent" property, long enough to
# avoid a hard discontinuity (a broadband splice "click") at each boundary.
_CROSSFADE_SAMPLES = 32

Window = tuple[int, int]


class ScrubReport(TypedDict):
    iq: np.ndarray
    windows_removed: int
    windows_without_donor: list[Window]
    samples_replaced: int


def load_iq(path, sample_format: str) -> np.ndarray:
    """Same sample_format -> dtype/scale mapping as
    ble_rf_diagnostics.py::_load_values, reused here rather than
    reimplemented so both readers agree on every format this project uses."""
    dtype = _DTYPE_MAP[sample_format]
    raw = np.fromfile(path, dtype=dtype)
    if sample_format == "cf32_le":
        return raw.astype(np.complex64)
    scale = 32768.0 if sample_format == "ci16_le" else 128.0
    return (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / scale


def save_iq(iq: np.ndarray, path, sample_format: str) -> None:
    if sample_format == "cf32_le":
        iq.astype("<c8").tofile(path)
        return
    scale = 32768.0 if sample_format == "ci16_le" else 128.0
    int_dtype = "<i2" if sample_format == "ci16_le" else "i1"
    interleaved = np.empty(iq.size * 2, dtype=np.float32)
    interleaved[0::2] = iq.real
    interleaved[1::2] = iq.imag
    clip = 32767.0 if sample_format == "ci16_le" else 127.0
    np.clip(np.round(interleaved * scale), -clip, clip).astype(int_dtype).tofile(path)


def _merge_windows(windows: list[Window]) -> list[Window]:
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _quiet_gaps(total_samples: int, occupied: list[Window]) -> list[Window]:
    """Complement of every decoded-packet window (any device) -- the only
    material safe to borrow as a donor. Borrowing from inside an OTHER
    device's packet window would paste a real transmitter's real payload
    into a second location in the file, a duplication artifact of its own."""
    merged = _merge_windows(occupied)
    gaps: list[Window] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_samples:
        gaps.append((cursor, total_samples))
    return gaps


def scrub_device_windows(
    iq: np.ndarray,
    removal_windows: list[Window],
    occupied_windows: list[Window],
    *,
    seed: int = 42,
) -> ScrubReport:
    """Excises every window in removal_windows, replacing each with a real
    quiet segment drawn (with a fixed seed, for reproducibility) from
    elsewhere in the same recording, crossfaded at both edges. Never invents
    a fill: a window with no sufficiently long quiet donor available is left
    untouched and reported in windows_without_donor -- a partial, visible
    result rather than a silently-claimed complete one."""
    removal = _merge_windows(removal_windows)
    quiet = [g for g in _quiet_gaps(len(iq), occupied_windows) if g[1] - g[0] > 2 * _CROSSFADE_SAMPLES]
    rng = np.random.default_rng(seed)
    edited = iq.copy()
    windows_without_donor: list[Window] = []
    samples_replaced = 0

    for start, end in removal:
        n = end - start
        candidates = [g for g in quiet if (g[1] - g[0]) >= n]
        if not candidates:
            windows_without_donor.append((start, end))
            continue
        gap_start, gap_end = candidates[int(rng.integers(0, len(candidates)))]
        donor_offset = int(rng.integers(0, gap_end - gap_start - n + 1))
        donor_start = gap_start + donor_offset
        donor = edited[donor_start:donor_start + n].copy()

        fade = min(_CROSSFADE_SAMPLES, n // 2)
        if fade > 0:
            ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade, dtype=np.float64))).astype(np.float32)
            donor[:fade] = edited[start:start + fade] * (1 - ramp) + donor[:fade] * ramp
            donor[-fade:] = donor[-fade:] * (1 - ramp[::-1]) + edited[end - fade:end] * ramp[::-1]

        edited[start:end] = donor
        samples_replaced += n

    return {
        "iq": edited,
        "windows_removed": len(removal) - len(windows_without_donor),
        "windows_without_donor": windows_without_donor,
        "samples_replaced": samples_replaced,
    }
