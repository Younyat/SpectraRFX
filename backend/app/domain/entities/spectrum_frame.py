from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True, frozen=True)
class SpectrumStatistics:
    peak_frequency_hz: float
    peak_level_db: float
    noise_floor_db: float
    mean_level_db: float
    occupied_bandwidth_hz: Optional[float] = None
    channel_power_db: Optional[float] = None
    snr_db: Optional[float] = None


@dataclass(slots=True, frozen=True)
class TraceMetadata:
    detector_mode: str
    trace_mode: str
    fft_size: int
    rbw_hz: float
    vbw_hz: float
    reference_level_db: float
    min_level_db: float
    max_level_db: float
    averaging_enabled: bool
    smoothing_enabled: bool


@dataclass(slots=True, frozen=True)
class SpectrumFrame:
    timestamp_utc: str
    center_frequency_hz: float
    span_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    sample_rate_hz: float
    frequencies_hz: List[float] = field(default_factory=list)
    levels_db: List[float] = field(default_factory=list)
    statistics: Optional[SpectrumStatistics] = None
    metadata: Optional[TraceMetadata] = None

    def __post_init__(self) -> None:
        if self.center_frequency_hz <= 0:
            raise ValueError("center_frequency_hz must be > 0")
        if self.span_hz <= 0:
            raise ValueError("span_hz must be > 0")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if self.start_frequency_hz >= self.stop_frequency_hz:
            raise ValueError("start_frequency_hz must be lower than stop_frequency_hz")
        if len(self.frequencies_hz) != len(self.levels_db):
            raise ValueError("frequencies_hz and levels_db must have the same length")

    @property
    def points(self) -> int:
        return len(self.levels_db)

    @property
    def peak_level_db(self) -> Optional[float]:
        if not self.levels_db:
            return None
        return max(self.levels_db)

    @property
    def peak_frequency_hz(self) -> Optional[float]:
        if not self.levels_db or not self.frequencies_hz:
            return None
        peak_index = max(range(len(self.levels_db)), key=self.levels_db.__getitem__)
        return self.frequencies_hz[peak_index]

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "center_frequency_hz": self.center_frequency_hz,
            "span_hz": self.span_hz,
            "start_frequency_hz": self.start_frequency_hz,
            "stop_frequency_hz": self.stop_frequency_hz,
            "sample_rate_hz": self.sample_rate_hz,
            "frequencies_hz": self.frequencies_hz,
            "levels_db": self.levels_db,
            "statistics": None if self.statistics is None else {
                "peak_frequency_hz": self.statistics.peak_frequency_hz,
                "peak_level_db": self.statistics.peak_level_db,
                "noise_floor_db": self.statistics.noise_floor_db,
                "mean_level_db": self.statistics.mean_level_db,
                "occupied_bandwidth_hz": self.statistics.occupied_bandwidth_hz,
                "channel_power_db": self.statistics.channel_power_db,
                "snr_db": self.statistics.snr_db,
            },
            "metadata": None if self.metadata is None else {
                "detector_mode": self.metadata.detector_mode,
                "trace_mode": self.metadata.trace_mode,
                "fft_size": self.metadata.fft_size,
                "rbw_hz": self.metadata.rbw_hz,
                "vbw_hz": self.metadata.vbw_hz,
                "reference_level_db": self.metadata.reference_level_db,
                "min_level_db": self.metadata.min_level_db,
                "max_level_db": self.metadata.max_level_db,
                "averaging_enabled": self.metadata.averaging_enabled,
                "smoothing_enabled": self.metadata.smoothing_enabled,
            },
        }