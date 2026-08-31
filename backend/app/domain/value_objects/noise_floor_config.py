from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


NoiseFloorMode = Literal["auto", "manual", "offset", "hybrid"]
NoiseEstimatorMethod = Literal["percentile", "median", "mean", "trimmed_mean"]


@dataclass(slots=True, frozen=True)
class NoiseFloorEstimatorConfig:
    mode: NoiseFloorMode = "auto"
    estimator_method: NoiseEstimatorMethod = "percentile"
    percentile: float = 20.0
    manual_level_db: Optional[float] = None
    offset_db: float = 0.0
    smoothing_enabled: bool = True
    smoothing_factor: float = 0.15
    min_valid_level_db: float = -200.0
    max_valid_level_db: float = 50.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.percentile <= 100.0:
            raise ValueError("percentile must be in [0, 100]")
        if not 0.0 < self.smoothing_factor <= 1.0:
            raise ValueError("smoothing_factor must be in (0, 1]")
        if self.min_valid_level_db >= self.max_valid_level_db:
            raise ValueError("min_valid_level_db must be lower than max_valid_level_db")

        if self.mode == "manual" and self.manual_level_db is None:
            raise ValueError("manual_level_db is required when mode is 'manual'")

        if self.manual_level_db is not None:
            if not self.min_valid_level_db <= self.manual_level_db <= self.max_valid_level_db:
                raise ValueError("manual_level_db is outside valid bounds")

    @property
    def uses_automatic_estimation(self) -> bool:
        return self.mode in {"auto", "offset", "hybrid"}

    @property
    def uses_manual_reference(self) -> bool:
        return self.mode in {"manual", "hybrid"}

    def with_manual_level(self, level_db: float) -> "NoiseFloorEstimatorConfig":
        return NoiseFloorEstimatorConfig(
            mode="manual",
            estimator_method=self.estimator_method,
            percentile=self.percentile,
            manual_level_db=level_db,
            offset_db=self.offset_db,
            smoothing_enabled=self.smoothing_enabled,
            smoothing_factor=self.smoothing_factor,
            min_valid_level_db=self.min_valid_level_db,
            max_valid_level_db=self.max_valid_level_db,
        )

    def with_offset(self, offset_db: float) -> "NoiseFloorEstimatorConfig":
        return NoiseFloorEstimatorConfig(
            mode="offset",
            estimator_method=self.estimator_method,
            percentile=self.percentile,
            manual_level_db=self.manual_level_db,
            offset_db=offset_db,
            smoothing_enabled=self.smoothing_enabled,
            smoothing_factor=self.smoothing_factor,
            min_valid_level_db=self.min_valid_level_db,
            max_valid_level_db=self.max_valid_level_db,
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "estimator_method": self.estimator_method,
            "percentile": self.percentile,
            "manual_level_db": self.manual_level_db,
            "offset_db": self.offset_db,
            "smoothing_enabled": self.smoothing_enabled,
            "smoothing_factor": self.smoothing_factor,
            "min_valid_level_db": self.min_valid_level_db,
            "max_valid_level_db": self.max_valid_level_db,
            "uses_automatic_estimation": self.uses_automatic_estimation,
            "uses_manual_reference": self.uses_manual_reference,
        }


@dataclass(slots=True, frozen=True)
class NoiseFloorThresholdConfig:
    threshold_enabled: bool = False
    threshold_db: Optional[float] = None
    relative_to_noise_floor: bool = True
    relative_offset_db: float = 6.0

    def __post_init__(self) -> None:
        if self.threshold_enabled:
            if self.relative_to_noise_floor:
                if self.relative_offset_db < 0:
                    raise ValueError("relative_offset_db must be >= 0")
            else:
                if self.threshold_db is None:
                    raise ValueError("threshold_db is required when using an absolute threshold")

    def resolved_threshold(self, noise_floor_db: float) -> Optional[float]:
        if not self.threshold_enabled:
            return None
        if self.relative_to_noise_floor:
            return noise_floor_db + self.relative_offset_db
        return self.threshold_db

    def to_dict(self) -> dict:
        return {
            "threshold_enabled": self.threshold_enabled,
            "threshold_db": self.threshold_db,
            "relative_to_noise_floor": self.relative_to_noise_floor,
            "relative_offset_db": self.relative_offset_db,
        }


@dataclass(slots=True, frozen=True)
class NoiseFloorConfig:
    estimator: NoiseFloorEstimatorConfig
    threshold: NoiseFloorThresholdConfig

    def to_dict(self) -> dict:
        return {
            "estimator": self.estimator.to_dict(),
            "threshold": self.threshold.to_dict(),
        }