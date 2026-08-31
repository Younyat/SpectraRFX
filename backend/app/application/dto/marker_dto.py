from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.domain.entities.marker import Marker, MarkerReadout


@dataclass(slots=True)
class MarkerReadoutDTO:
    frequency_hz: float
    level_db: float
    delta_frequency_hz: Optional[float] = None
    delta_level_db: Optional[float] = None
    bandwidth_hz: Optional[float] = None
    noise_floor_db: Optional[float] = None
    snr_db: Optional[float] = None

    @classmethod
    def from_entity(cls, entity: MarkerReadout) -> "MarkerReadoutDTO":
        return cls(
            frequency_hz=entity.frequency_hz,
            level_db=entity.level_db,
            delta_frequency_hz=entity.delta_frequency_hz,
            delta_level_db=entity.delta_level_db,
            bandwidth_hz=entity.bandwidth_hz,
            noise_floor_db=entity.noise_floor_db,
            snr_db=entity.snr_db,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MarkerDTO:
    marker_id: str
    label: str
    frequency_hz: float
    marker_type: str = "normal"
    mode: str = "manual"
    enabled: bool = True
    locked: bool = False
    reference_marker_id: Optional[str] = None
    readout: Optional[MarkerReadoutDTO] = None
    color: Optional[str] = None
    metadata: dict | None = None

    @classmethod
    def from_entity(cls, entity: Marker) -> "MarkerDTO":
        return cls(
            marker_id=entity.marker_id,
            label=entity.label,
            frequency_hz=entity.frequency_hz,
            marker_type=entity.marker_type,
            mode=entity.mode,
            enabled=entity.enabled,
            locked=entity.locked,
            reference_marker_id=entity.reference_marker_id,
            readout=None if entity.readout is None else MarkerReadoutDTO.from_entity(entity.readout),
            color=entity.color,
            metadata=entity.metadata,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return data
