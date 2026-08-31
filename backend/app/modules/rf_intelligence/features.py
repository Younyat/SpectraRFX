from __future__ import annotations

import math
from statistics import median


def finite_pairs(frequencies_hz: list[float], levels_db: list[float]) -> tuple[list[float], list[float]]:
    pairs = [
        (float(freq), float(level))
        for freq, level in zip(frequencies_hz, levels_db)
        if math.isfinite(freq) and math.isfinite(level)
    ]
    if not pairs:
        return [], []
    frequencies, levels = zip(*pairs)
    return list(frequencies), list(levels)


def estimate_noise_floor(levels_db: list[float]) -> float | None:
    finite = [level for level in levels_db if math.isfinite(level)]
    if not finite:
        return None
    return float(median(finite))


def mean_db(levels_db: list[float]) -> float:
    finite = [level for level in levels_db if math.isfinite(level)]
    if not finite:
        return float("nan")
    return sum(finite) / len(finite)


def estimate_occupied_bandwidth(frequencies_hz: list[float], levels_db: list[float], noise_floor_db: float) -> float:
    if len(frequencies_hz) < 2:
        return 0.0
    peak = max(levels_db)
    edge_threshold = max(noise_floor_db + 3.0, peak - 10.0)
    active_indexes = [index for index, level in enumerate(levels_db) if level >= edge_threshold]
    if not active_indexes:
        return abs(frequencies_hz[-1] - frequencies_hz[0])
    return abs(frequencies_hz[max(active_indexes)] - frequencies_hz[min(active_indexes)])


def spectral_flatness_score(levels_db: list[float]) -> float:
    finite = [level for level in levels_db if math.isfinite(level)]
    if len(finite) < 2:
        return 0.0
    level_range = max(finite) - min(finite)
    return max(0.0, min(1.0, 1.0 - (level_range / 30.0)))
