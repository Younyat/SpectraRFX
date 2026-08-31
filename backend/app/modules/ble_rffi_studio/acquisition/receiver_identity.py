"""Receiver-identity and qualified-acquisition-profile primitives (2026-08-08
correction, point 1): separates WHICH physical B200
(receiver_identity_id, stable for the unit's whole lifetime) from WHICH
qualified acquisition conditions (qualified_acquisition_profile_hash) --
the previous receiver_epoch conflated identity with epoch and additionally
used the legacy `device_id` field, which real data showed to be unreliable:
some real capture_manifest.json files record it as a normalized/hashed
string (populated from request.json by an upstream tool), others never
populate it and the old code fell through to the raw hardware serial --
verified against real data, the SAME physical B200
(device_serial=E3R04Z1B2 in every real capture on disk) was silently split
into two different identities (133 captures under a hashed device_id vs 11
under the raw serial) purely by this inconsistency, not by any real
hardware change.
"""
from __future__ import annotations

import hashlib

_QUALIFIED_PROFILE_FIELDS = (
    "sdr_model", "device_serial", "sample_rate_sps", "frontend_bandwidth_hz",
    "gain_db", "gain_mode", "rx_channel", "antenna_port", "clock_source", "time_source", "capture_tool",
)


def compute_receiver_identity_id(*, sdr_model: str, device_serial: str | None) -> str | None:
    """Canonical physical-receiver identity: SDR model + hardware serial
    ONLY -- deliberately never the legacy, unreliable `device_id` field (see
    module docstring). None when no real serial is on file (this pipeline
    has no other trustworthy hardware-identity source -- never falls back
    to a request.json-declared, operator-facing id)."""
    if not device_serial:
        return None
    return "identity-" + hashlib.sha256(f"{sdr_model}|{device_serial}".encode("utf-8")).hexdigest()[:16]


def compute_qualified_acquisition_profile_hash(
    *, sdr_model: str, device_serial: str | None, sample_rate_sps: int, frontend_bandwidth_hz: int,
    gain_db: float, gain_mode: str, rx_channel: str, antenna_port: str,
    clock_source: str | None, time_source: str | None, capture_tool: str,
) -> str:
    """Every acquisition-chain parameter that can plausibly change what the
    receiver measures -- not preprocessing, not anything computed after the
    fact. Two captures of the SAME physical unit with an identical hash here
    were acquired, as far as this pipeline can observe, under the same
    qualified conditions; a real change to any of these fields (e.g. a
    different gain_mode between PRE and POST) yields a different hash and,
    via receiver_epoch_assignment.py, a new receiver_epoch."""
    values = {
        "sdr_model": sdr_model, "device_serial": device_serial or "", "sample_rate_sps": sample_rate_sps,
        "frontend_bandwidth_hz": frontend_bandwidth_hz, "gain_db": gain_db, "gain_mode": gain_mode,
        "rx_channel": rx_channel, "antenna_port": antenna_port, "clock_source": clock_source or "",
        "time_source": time_source or "", "capture_tool": capture_tool,
    }
    canonical = "|".join(f"{key}={values[key]}" for key in _QUALIFIED_PROFILE_FIELDS)
    return "profile-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
