from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True, frozen=True)
class ResolutionBandwidthConfig:
    rbw_hz: float
    vbw_hz: float
    averaging_count: int = 1
    
    def __post_init__(self) -> None:
        if self.rbw_hz <= 0:
            raise ValueError("rbw_hz must be > 0")
        if self.vbw_hz <= 0:
            raise ValueError("vbw_hz must be > 0")
        if self.averaging_count < 1:
            raise ValueError("averaging_count must be >= 1")
    
    @property
    def ratio(self) -> float:
        return self.rbw_hz / self.vbw_hz if self.vbw_hz > 0 else 0.0
    
    def to_dict(self) -> dict:
        return {
            "rbw_hz": self.rbw_hz,
            "vbw_hz": self.vbw_hz,
            "averaging_count": self.averaging_count,
            "ratio": self.ratio,
        }

    def __post_init__(self) -> None:
        if self.vbw_hz <= 0:
            raise ValueError("vbw_hz must be > 0")
        if self.smoothing_factor is not None and not 0.0 < self.smoothing_factor <= 1.0:
            raise ValueError("smoothing_factor must be in (0, 1]")
        if self.averaging_length is not None and self.averaging_length <= 0:
            raise ValueError("averaging_length must be > 0")

    def to_dict(self) -> dict:
        return {
            "vbw_hz": self.vbw_hz,
            "enabled": self.enabled,
            "smoothing_factor": self.smoothing_factor,
            "averaging_length": self.averaging_length,
        }


@dataclass(slots=True, frozen=True)
class SweepResolutionConfig:
    rbw: RBWConfig
    vbw: VBWConfig
    span_hz: float
    sweep_mode: SweepMode = "realtime"

    def __post_init__(self) -> None:
        if self.span_hz <= 0:
            raise ValueError("span_hz must be > 0")

    @property
    def vbw_to_rbw_ratio(self) -> float:
        return self.vbw.vbw_hz / self.rbw.rbw_hz

    @property
    def estimated_points_in_span(self) -> float:
        return self.span_hz / self.rbw.rbw_hz

    @property
    def is_vbw_narrower_than_rbw(self) -> bool:
        return self.vbw.vbw_hz < self.rbw.rbw_hz

    def validate_consistency(self) -> None:
        if self.vbw.enabled and self.vbw.vbw_hz > self.rbw.rbw_hz * 10:
            raise ValueError("vbw_hz is unrealistically larger than rbw_hz")
        if self.estimated_points_in_span < 2:
            raise ValueError("span is too narrow for the selected rbw")

    def to_dict(self) -> dict:
        return {
            "rbw": self.rbw.to_dict(),
            "vbw": self.vbw.to_dict(),
            "span_hz": self.span_hz,
            "sweep_mode": self.sweep_mode,
            "vbw_to_rbw_ratio": self.vbw_to_rbw_ratio,
            "estimated_points_in_span": self.estimated_points_in_span,
            "is_vbw_narrower_than_rbw": self.is_vbw_narrower_than_rbw,
        }