from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from app.domain.entities.spectrum_frame import SpectrumFrame


@dataclass(slots=True)
class SpectrumDTO:
    timestamp_utc: str
    center_frequency_hz: float
    span_hz: float
    frequencies_hz: list[float] = field(default_factory=list)
    levels_db: list[float] = field(default_factory=list)
    start_frequency_hz: Optional[float] = None
    stop_frequency_hz: Optional[float] = None
    sample_rate_hz: Optional[float] = None
    points: int = 0
    peak_frequency_hz: Optional[float] = None
    peak_level_db: Optional[float] = None
    statistics: Optional[dict] = None
    metadata: Optional[dict] = None

    @classmethod
    def from_entity(cls, entity: SpectrumFrame | None) -> "SpectrumDTO | None":
        if entity is None:
            return None

        return cls(
            timestamp_utc=entity.timestamp_utc,
            center_frequency_hz=entity.center_frequency_hz,
            span_hz=entity.span_hz,
            frequencies_hz=entity.frequencies_hz,
            levels_db=entity.levels_db,
            start_frequency_hz=entity.start_frequency_hz,
            stop_frequency_hz=entity.stop_frequency_hz,
            sample_rate_hz=entity.sample_rate_hz,
            points=entity.points,
            peak_frequency_hz=entity.peak_frequency_hz,
            peak_level_db=entity.peak_level_db,
            statistics=None if entity.statistics is None else asdict(entity.statistics),
            metadata=None if entity.metadata is None else asdict(entity.metadata),
        )

    def to_dict(self) -> dict:
        return asdict(self)
