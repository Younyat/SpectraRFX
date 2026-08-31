"""Decodes a single, already-captured LIVE IQ burst in memory, reusing the
EXACT SAME Gate 2A.2 receiver chain ble_offline_replay.py already uses for
offline batch decode (ble-worker-lab's run_offline_receiver) -- so a
live-classified window can be built the same way a training ExampleRecord's
window is (packet-aligned, from packet_start_bit/packet_end_bit), instead of
a raw energy-threshold burst window. See BLE-RFFI Studio README's "Why live
detection fails despite a good TEST score" for the full diagnosis this fixes.

Deliberately additive, opt-in, and isolated from the existing energy-only
live path -- "cuidado, no romper nada" was explicit:
- OFF by default (BLE_LIVE_DECODE_ENABLED must be explicitly set to
  "1"/"true"/"yes"): until turned on, this entire module is inert and the
  live pipeline's behavior is byte-for-byte what it was before this file
  existed;
- importing ble-worker-lab happens lazily, only inside live_decode_burst(),
  so nothing about any existing caller's import time changes even when
  enabled;
- ble-worker-lab being unavailable/import failing makes this a no-op
  returning None, which callers must treat as "fall back to the existing
  energy-only behavior", never as an error;
- any exception during decode is caught and turned into None -- a decode
  failure here must never crash or block the live-check thread, exactly like
  every other best-effort path in real_spectrum_stream.py's live-check loop.

Ground-truth caveat this inherits, not introduces: ble-worker-lab's Gate 2A.2
receiver is documented (docs/technical-readmes/ble/README.md) as a
development candidate (381/384 on its own dev sweep, not the required
384/384; no Holdout B yet) -- this module does not make that decoder any
more or less validated than it already is for the OFFLINE training path that
has depended on it all along. It only stops LIVE inference from using a
*different, less rigorous* extraction method (pure energy threshold) than
training does.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

_ENABLED = os.environ.get("BLE_LIVE_DECODE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
_WORKER_REPOSITORY = Path(os.environ.get("BLE_GATE2A2_REPOSITORY", r"C:\Users\Usuario\ble-worker-lab"))


def live_decode_enabled() -> bool:
    return _ENABLED


def live_decode_burst(iq_samples: np.ndarray, channel: int) -> dict[str, Any] | None:
    """Runs the real BLE receiver (burst detection -> demod -> bitstream
    decode -> CRC check) over an already-captured burst's raw samples.
    Returns the FIRST CRC-valid confirmed packet found, as
    {"packet_start_sample", "packet_end_sample", "address"} with sample
    offsets relative to iq_samples itself (clamped to [0, len(iq_samples)]) --
    or None if disabled, ble-worker-lab is unavailable, or no valid BLE
    packet was decoded in this burst (common: the energy detector fires on
    non-BLE energy too, e.g. Wi-Fi or other 2.4 GHz activity).
    """
    if not _ENABLED or iq_samples is None or iq_samples.size == 0:
        return None
    try:
        src_path = str(_WORKER_REPOSITORY / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        from ble_worker.dsp_models import ReceiverConfig
        from ble_worker.dsp_receiver import run_offline_receiver

        samples = np.asarray(iq_samples, dtype=np.complex64)
        source_iq_sha256 = hashlib.sha256(samples.tobytes()).hexdigest()
        config = ReceiverConfig(channel_index=channel, minimum_burst_samples=80, maximum_burst_samples=max(4096, int(samples.size)))
        result = run_offline_receiver(samples, config, source_iq_sha256=source_iq_sha256)

        semantic_by_packet_id = {}
        for semantic in result.semantic_packets:
            try:
                semantic_by_packet_id[semantic.packet_id] = semantic
            except Exception:
                continue

        for candidate, decoded in zip(result.candidates, result.decoded_results):
            for packet in decoded.confirmed_packets:
                if not packet.crc_valid:
                    continue
                start = candidate.sample_start + round(packet.packet_start_bit * candidate.samples_per_symbol)
                end = candidate.sample_start + round(packet.packet_end_bit * candidate.samples_per_symbol)
                address = None
                semantic = semantic_by_packet_id.get(packet.packet_sha256)
                if semantic is not None:
                    try:
                        address = (semantic.addresses.get("advertiser") or {}).get("address_canonical")
                    except Exception:
                        address = None
                return {
                    "packet_start_sample": max(0, int(start)),
                    "packet_end_sample": min(int(samples.size), int(end)),
                    "address": address,
                }
        return None
    except Exception:
        return None
