from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True, frozen=True)
class WaterfallMetadata:
    color_map: str
    min_level_db: float
    max_level_db: float
    history_size: int
    averaging_enabled: bool
    smoothing_enabled: bool


@dataclass(slots=True, frozen=True)
class WaterfallFrame:
    timestamp_utc: str
    center_frequency_hz: float
    span_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    sample_rate_hz: float
    row_index: int
    frequencies_hz: List[float] = field(default_factory=list)
    levels_db: List[float] = field(default_factory=list)
    normalized_levels: Optional[List[float]] = None
    metadata: Optional[WaterfallMetadata] = None

    def __post_init__(self) -> None:
        if self.center_frequency_hz <= 0:
            raise ValueError("center_frequency_hz must be > 0")
        if self.span_hz <= 0:
            raise ValueError("span_hz must be > 0")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if self.start_frequency_hz >= self.stop_frequency_hz:
            raise ValueError("start_frequency_hz must be lower than stop_frequency_hz")
        if self.row_index < 0:
            raise ValueError("row_index must be >= 0")
        if len(self.frequencies_hz) != len(self.levels_db):
            raise ValueError("frequencies_hz and levels_db must have the same length")
        if self.normalized_levels is not None and len(self.normalized_levels) != len(self.levels_db):
            raise ValueError("normalized_levels and levels_db must have the same length")

    @property
    def points(self) -> int:
        return len(self.levels_db)

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "center_frequency_hz": self.center_frequency_hz,
            "span_hz": self.span_hz,
            "start_frequency_hz": self.start_frequency_hz,
            "stop_frequency_hz": self.stop_frequency_hz,
            "sample_rate_hz": self.sample_rate_hz,
            "row_index": self.row_index,
            "frequencies_hz": self.frequencies_hz,
            "levels_db": self.levels_db,
            "normalized_levels": self.normalized_levels,
            "metadata": None if self.metadata is None else {
                "color_map": self.metadata.color_map,
                "min_level_db": self.metadata.min_level_db,
                "max_level_db": self.metadata.max_level_db,
                "history_size": self.metadata.history_size,
                "averaging_enabled": self.metadata.averaging_enabled,
                "smoothing_enabled": self.metadata.smoothing_enabled,
            },
        }