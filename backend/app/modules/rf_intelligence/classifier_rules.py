from __future__ import annotations

from typing import Any

from app.modules.rf_intelligence.detector import SignalCandidate
from app.modules.rf_intelligence.knowledge_base import load_band_profiles
from app.modules.rf_intelligence.schemas import RFObjectEvidence


def classify_candidate(candidate: SignalCandidate) -> tuple[str, str, float, RFObjectEvidence]:
    best_profile: dict[str, Any] | None = None
    best_score = 0.0
    best_evidence = RFObjectEvidence()

    for profile in load_band_profiles().values():
        score, evidence = _score_profile(candidate, profile)
        if score > best_score:
            best_score = score
            best_profile = profile
            best_evidence = evidence

    if best_profile is None or best_score < 0.35:
        evidence = RFObjectEvidence(
            notes=[
                "Energy region exceeded adaptive threshold.",
                "No band profile matched strongly; preserve as unknown for dataset review.",
            ]
        )
        return "Unknown RF signal", "unknown", min(0.55, max(0.25, candidate.snr_db / 40.0)), evidence

    confidence = min(0.98, max(0.40, best_score))
    return best_profile["label"], best_profile["family"], confidence, best_evidence


def infer_temporal_type(candidate: SignalCandidate, family: str, persistence: float) -> str:
    if family in {"broadcast_fm"} or persistence >= 0.80:
        return "continuous"
    if family in {"bluetooth_ble"}:
        return "hopping_candidate"
    if family in {"wifi_24g", "zigbee_802154", "ism_remote", "ism_iot"}:
        return "bursty"
    return "unknown"


def _score_profile(candidate: SignalCandidate, profile: dict[str, Any]) -> tuple[float, RFObjectEvidence]:
    center = candidate.center_frequency_hz
    bandwidth = max(candidate.occupied_bandwidth_hz, candidate.bandwidth_hz)
    frequency_match = profile["frequency_min_hz"] <= center <= profile["frequency_max_hz"]
    bandwidth_match = _bandwidth_matches(bandwidth, profile.get("expected_bandwidth_hz"))

    score = 0.0
    notes: list[str] = []
    if frequency_match:
        score += 0.45
        notes.append("Center frequency is inside the profile band.")
    if bandwidth_match:
        score += 0.35
        notes.append("Occupied bandwidth is inside the expected range.")

    snr_score = min(0.15, max(0.0, candidate.snr_db / 120.0))
    score += snr_score
    if candidate.snr_db >= 12:
        notes.append("SNR is strong enough for a stable technical hypothesis.")

    channel_grid_match = _nearest_channel(center, profile.get("channel_centers_hz"))
    if channel_grid_match:
        score += 0.05
        notes.append("Center frequency is near a known channel grid.")

    if frequency_match and not bandwidth_match:
        notes.append("Band matched, but bandwidth differs from the profile.")

    return score, RFObjectEvidence(
        frequency_band_match=frequency_match,
        bandwidth_match=bandwidth_match,
        temporal_match=False,
        channel_grid_match=channel_grid_match,
        notes=notes,
    )


def _bandwidth_matches(bandwidth_hz: float, expected_bandwidth_hz: Any) -> bool:
    if not isinstance(expected_bandwidth_hz, list) or not expected_bandwidth_hz:
        return False

    values: list[float] = []
    for value in expected_bandwidth_hz:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return False

    if len(values) == 2:
        bw_min, bw_max = sorted(values)
        return bw_min <= bandwidth_hz <= bw_max

    # One or more nominal channel bandwidths. Accept a practical tolerance around
    # each nominal value because live occupied-bandwidth estimates are noisy.
    for nominal in values:
        tolerance = max(nominal * 0.35, 25_000.0)
        if nominal - tolerance <= bandwidth_hz <= nominal + tolerance:
            return True
    return False


def _nearest_channel(center_hz: float, channels: list[float] | None) -> str | None:
    if not channels:
        return None
    nearest_index, nearest_hz = min(enumerate(channels, start=1), key=lambda item: abs(item[1] - center_hz))
    if abs(nearest_hz - center_hz) <= 3_000_000:
        return f"channel_{nearest_index}"
    return None
