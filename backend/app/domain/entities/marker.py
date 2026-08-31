from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


MarkerType = Literal["normal", "delta", "noise", "peak"]
MarkerMode = Literal["manual", "peak", "peak_next", "peak_left", "peak_right"]


@dataclass(slots=True)
class MarkerReadout:
    frequency_hz: float
    level_db: float
    delta_frequency_hz: Optional[float] = None
    delta_level_db: Optional[float] = None
    bandwidth_hz: Optional[float] = None
    noise_floor_db: Optional[float] = None
    snr_db: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "frequency_hz": self.frequency_hz,
            "level_db": self.level_db,
            "delta_frequency_hz": self.delta_frequency_hz,
            "delta_level_db": self.delta_level_db,
            "bandwidth_hz": self.bandwidth_hz,
            "noise_floor_db": self.noise_floor_db,
            "snr_db": self.snr_db,
        }


@dataclass(slots=True)
class Marker:
    marker_id: str
    label: str
    frequency_hz: float
    marker_type: MarkerType = "normal"
    mode: MarkerMode = "manual"
    enabled: bool = True
    locked: bool = False
    reference_marker_id: Optional[str] = None
    readout: Optional[MarkerReadout] = None
    color: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.marker_id.strip():
            raise ValueError("marker_id must not be empty")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if self.frequency_hz <= 0:
            raise ValueError("frequency_hz must be > 0")

    def move_to(self, frequency_hz: float) -> None:
        if self.locked:
            raise ValueError("marker is locked and cannot be moved")
        if frequency_hz <= 0:
            raise ValueError("frequency_hz must be > 0")
        self.frequency_hz = frequency_hz

    def rename(self, new_label: str) -> None:
        if not new_label.strip():
            raise ValueError("label must not be empty")
        self.label = new_label

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def lock(self) -> None:
        self.locked = True

    def unlock(self) -> None:
        self.locked = False

    def set_mode(self, mode: MarkerMode) -> None:
        self.mode = mode

    def set_type(self, marker_type: MarkerType) -> None:
        self.marker_type = marker_type

    def attach_reference(self, marker_id: str) -> None:
        if not marker_id.strip():
            raise ValueError("reference marker id must not be empty")
        self.reference_marker_id = marker_id

    def clear_reference(self) -> None:
        self.reference_marker_id = None

    def update_readout(
        self,
        level_db: float,
        delta_frequency_hz: Optional[float] = None,
        delta_level_db: Optional[float] = None,
        bandwidth_hz: Optional[float] = None,
        noise_floor_db: Optional[float] = None,
        snr_db: Optional[float] = None,
    ) -> None:
        self.readout = MarkerReadout(
            frequency_hz=self.frequency_hz,
            level_db=level_db,
            delta_frequency_hz=delta_frequency_hz,
            delta_level_db=delta_level_db,
            bandwidth_hz=bandwidth_hz,
            noise_floor_db=noise_floor_db,
            snr_db=snr_db,
        )

    def to_dict(self) -> dict:
        return {
            "marker_id": self.marker_id,
            "label": self.label,
            "frequency_hz": self.frequency_hz,
            "marker_type": self.marker_type,
            "mode": self.mode,
            "enabled": self.enabled,
            "locked": self.locked,
            "reference_marker_id": self.reference_marker_id,
            "readout": None if self.readout is None else self.readout.to_dict(),
            "color": self.color,
            "metadata": self.metadata,
        }