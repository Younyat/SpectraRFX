from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_band_profiles() -> dict[str, dict[str, Any]]:
    path = Path(__file__).with_name("band_profiles.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_band_profile(
    *,
    start_frequency_hz: float | None = None,
    stop_frequency_hz: float | None = None,
    center_frequency_hz: float | None = None,
    bandwidth_hz: float | None = None,
) -> dict[str, Any]:
    """Resolve marker-band frequencies to a weak, editable capture label.

    The resolver intentionally produces a class/signal hypothesis, not a
    confirmed physical transmitter identity. Scientific training still requires
    user confirmation before a sample becomes a strong label.
    """

    start = _safe_float(start_frequency_hz)
    stop = _safe_float(stop_frequency_hz)
    center = _safe_float(center_frequency_hz)
    bandwidth = _safe_float(bandwidth_hz)

    if start is not None and stop is not None:
        low, high = sorted((start, stop))
        if center is None:
            center = (low + high) / 2.0
        if bandwidth is None:
            bandwidth = max(0.0, high - low)
    elif center is not None and bandwidth is not None and bandwidth > 0:
        low = center - bandwidth / 2.0
        high = center + bandwidth / 2.0
    else:
        return {
            "matched": False,
            "profile_key": None,
            "score": 0.0,
            "message": "Provide marker start/stop frequencies or center frequency plus bandwidth.",
            "defaults": _unknown_defaults(),
            "candidates": [],
        }

    candidates: list[dict[str, Any]] = []
    for key, profile in load_band_profiles().items():
        profile_low = _safe_float(profile.get("frequency_min_hz"))
        profile_high = _safe_float(profile.get("frequency_max_hz"))
        if profile_low is None or profile_high is None:
            continue
        score = _profile_match_score(low, high, center, bandwidth, profile_low, profile_high, profile)
        if score <= 0:
            continue
        candidates.append(
            {
                "profile_key": key,
                "label": profile.get("label", key),
                "family": profile.get("family", "unknown"),
                "modulation": profile.get("modulation", []),
                "temporal_pattern": profile.get("temporal_pattern"),
                "frequency_min_hz": profile_low,
                "frequency_max_hz": profile_high,
                "expected_bandwidth_hz": profile.get("expected_bandwidth_hz", []),
                "score": round(score, 4),
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates or candidates[0]["score"] < 0.25:
        return {
            "matched": False,
            "profile_key": None,
            "score": round(candidates[0]["score"], 4) if candidates else 0.0,
            "message": "No band profile matched strongly enough; keep as review-required weak label.",
            "defaults": _unknown_defaults(),
            "candidates": candidates[:5],
        }

    best = candidates[0]
    defaults = _defaults_from_profile(best)
    return {
        "matched": True,
        "profile_key": best["profile_key"],
        "score": best["score"],
        "message": "Band profile resolved from Marker 1/Marker 2 frequency window. Review and confirm before scientific training.",
        "defaults": defaults,
        "candidates": candidates[:5],
    }


def _profile_match_score(
    low: float,
    high: float,
    center: float | None,
    bandwidth: float | None,
    profile_low: float,
    profile_high: float,
    profile: dict[str, Any],
) -> float:
    overlap = max(0.0, min(high, profile_high) - max(low, profile_low))
    query_width = max(high - low, 1.0)
    profile_width = max(profile_high - profile_low, 1.0)
    overlap_ratio = overlap / query_width
    center_match = bool(center is not None and profile_low <= center <= profile_high)
    bandwidth_match = _bandwidth_matches(float(bandwidth or query_width), profile.get("expected_bandwidth_hz"))
    specificity = min(0.20, 5_000_000.0 / profile_width)

    score = 0.0
    if center_match:
        score += 0.45
    score += min(0.25, overlap_ratio * 0.25)
    if bandwidth_match:
        score += 0.20
    score += specificity
    return score


def _bandwidth_matches(bandwidth_hz: float, expected_bandwidth_hz: Any) -> bool:
    if not isinstance(expected_bandwidth_hz, list) or not expected_bandwidth_hz:
        return False
    values = [_safe_float(value) for value in expected_bandwidth_hz]
    values = [value for value in values if value is not None and value > 0]
    if not values:
        return False
    if len(values) == 2:
        low, high = sorted(values)
        return low <= bandwidth_hz <= high
    for nominal in values:
        tolerance = max(nominal * 0.40, 25_000.0)
        if nominal - tolerance <= bandwidth_hz <= nominal + tolerance:
            return True
    return False


def _defaults_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile_key = str(profile.get("profile_key") or "band_profile")
    family = str(profile.get("family") or "unknown").strip() or "unknown"
    label = str(profile.get("label") or profile_key).strip() or profile_key
    modulation = profile.get("modulation") if isinstance(profile.get("modulation"), list) else []
    modulation_class = str(modulation[0]) if modulation else family
    return {
        "transmitter_label": label,
        "transmitter_class": family,
        "transmitter_id": f"weak_{profile_key}",
        "family": family,
        "signal_type": family,
        "modulation_class": modulation_class,
        "protocol_family": family,
        "band_label": label,
        "profile_key": profile_key,
        "ground_truth_confidence": "weak_from_band_profile",
        "label_status": "weak_label",
        "review_status": "needs_review",
        "training_readiness": "candidate",
    }


def _unknown_defaults() -> dict[str, Any]:
    return {
        "transmitter_label": "unresolved_band_profile",
        "transmitter_class": "unresolved_rf_signal",
        "transmitter_id": "weak_unresolved_rf_signal",
        "family": "unresolved_rf_signal",
        "signal_type": "unresolved_rf_signal",
        "modulation_class": "unresolved",
        "protocol_family": "unresolved",
        "band_label": "Unresolved RF band",
        "profile_key": None,
        "ground_truth_confidence": "weak_unresolved",
        "label_status": "weak_label",
        "review_status": "needs_review",
        "training_readiness": "candidate",
    }


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None
