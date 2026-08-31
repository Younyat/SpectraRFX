from __future__ import annotations

from dataclasses import dataclass

from app.modules.rf_intelligence.features import (
    estimate_noise_floor,
    estimate_occupied_bandwidth,
    finite_pairs,
    mean_db,
)
from app.modules.rf_intelligence.schemas import RFIntelligenceSettings, SpectrumFrameInput


@dataclass(slots=True)
class SignalCandidate:
    candidate_id: str
    start_frequency_hz: float
    stop_frequency_hz: float
    center_frequency_hz: float
    bandwidth_hz: float
    occupied_bandwidth_hz: float
    snr_db: float
    peak_power_db: float
    mean_power_db: float
    noise_floor_db: float
    start_bin: int
    stop_bin: int


def detect_signal_candidates(
    frame: SpectrumFrameInput,
    settings: RFIntelligenceSettings,
) -> tuple[list[SignalCandidate], float | None, float | None]:
    frequencies_hz, levels_db = finite_pairs(frame.frequencies_hz, frame.levels_db)
    if len(frequencies_hz) < max(settings.min_bins, 2):
        return [], None, None

    noise_floor_db = estimate_noise_floor(levels_db)
    if noise_floor_db is None:
        return [], None, None

    threshold_db = noise_floor_db + settings.threshold_offset_db
    active_indexes = [index for index, level in enumerate(levels_db) if level >= threshold_db]
    groups = _group_indexes(active_indexes, settings.merge_gap_bins)

    candidates: list[SignalCandidate] = []
    for group_index, group in enumerate(groups, start=1):
        if len(group) < settings.min_bins:
            continue
        start_bin = min(group)
        stop_bin = max(group)
        group_levels = levels_db[start_bin : stop_bin + 1]
        group_frequencies = frequencies_hz[start_bin : stop_bin + 1]
        peak_power_db = max(group_levels)
        snr_db = peak_power_db - noise_floor_db
        if snr_db < settings.min_snr_db:
            continue

        start_frequency_hz = group_frequencies[0]
        stop_frequency_hz = group_frequencies[-1]
        bandwidth_hz = abs(stop_frequency_hz - start_frequency_hz)
        if bandwidth_hz == 0 and len(frequencies_hz) > 1:
            bandwidth_hz = abs(frequencies_hz[1] - frequencies_hz[0])
            start_frequency_hz -= bandwidth_hz / 2
            stop_frequency_hz += bandwidth_hz / 2

        candidates.append(
            SignalCandidate(
                candidate_id=f"det_{group_index:03d}",
                start_frequency_hz=min(start_frequency_hz, stop_frequency_hz),
                stop_frequency_hz=max(start_frequency_hz, stop_frequency_hz),
                center_frequency_hz=(start_frequency_hz + stop_frequency_hz) / 2,
                bandwidth_hz=abs(bandwidth_hz),
                occupied_bandwidth_hz=estimate_occupied_bandwidth(group_frequencies, group_levels, noise_floor_db),
                snr_db=snr_db,
                peak_power_db=peak_power_db,
                mean_power_db=mean_db(group_levels),
                noise_floor_db=noise_floor_db,
                start_bin=start_bin,
                stop_bin=stop_bin,
            )
        )

    return candidates, noise_floor_db, threshold_db


def _group_indexes(indexes: list[int], merge_gap_bins: int) -> list[list[int]]:
    if not indexes:
        return []
    groups: list[list[int]] = [[indexes[0]]]
    for index in indexes[1:]:
        if index - groups[-1][-1] <= merge_gap_bins + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups
