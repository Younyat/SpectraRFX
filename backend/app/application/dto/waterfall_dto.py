from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from app.domain.entities.waterfall_frame import WaterfallFrame


@dataclass(slots=True)
class WaterfallDTO:
    timestamp_utc: str
    center_frequency_hz: float
    span_hz: float
    history_count: int = 0
    data: list[list[float]] = field(default_factory=list)
    start_frequency_hz: Optional[float] = None
    stop_frequency_hz: Optional[float] = None
    sample_rate_hz: Optional[float] = None
    row_index: int = 0
    frequencies_hz: list[float] = field(default_factory=list)
    levels_db: list[float] = field(default_factory=list)
    normalized_levels: Optional[list[float]] = None
    points: int = 0
    metadata: Optional[dict] = None

    @classmethod
    def from_entity(cls, entity: WaterfallFrame | None) -> "WaterfallDTO | None":
        if entity is None:
            return None

        return cls(
            timestamp_utc=entity.timestamp_utc,
            center_frequency_hz=entity.center_frequency_hz,
            span_hz=entity.span_hz,
            start_frequency_hz=entity.start_frequency_hz,
            stop_frequency_hz=entity.stop_frequency_hz,
            sample_rate_hz=entity.sample_rate_hz,
            row_index=entity.row_index,
            frequencies_hz=entity.frequencies_hz,
            levels_db=entity.levels_db,
            normalized_levels=entity.normalized_levels,
            points=entity.points,
            metadata=None if entity.metadata is None else asdict(entity.metadata),
        )

    def to_dict(self) -> dict:
        return asdict(self)
