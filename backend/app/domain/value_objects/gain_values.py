from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GainLimits:
    min_gain_db: float
    max_gain_db: float
    step_gain_db: float = 1.0

    def __post_init__(self) -> None:
        if self.min_gain_db > self.max_gain_db:
            raise ValueError("min_gain_db must be <= max_gain_db")
        if self.step_gain_db <= 0:
            raise ValueError("step_gain_db must be > 0")

    def clamp(self, gain_db: float) -> float:
        return max(self.min_gain_db, min(self.max_gain_db, gain_db))

    def contains(self, gain_db: float) -> bool:
        return self.min_gain_db <= gain_db <= self.max_gain_db

    def to_dict(self) -> dict:
        return {
            "min_gain_db": self.min_gain_db,
            "max_gain_db": self.max_gain_db,
            "step_gain_db": self.step_gain_db,
        }


@dataclass(slots=True, frozen=True)
class GainValue:
    gain_db: float

    def __post_init__(self) -> None:
        if not isinstance(self.gain_db, (int, float)):
            raise ValueError("gain_db must be numeric")

    def clamp(self, limits: GainLimits) -> GainValue:
        return GainValue(gain_db=limits.clamp(self.gain_db))

    def validate_against(self, limits: GainLimits) -> None:
        if not limits.contains(self.gain_db):
            raise ValueError(
                f"gain_db={self.gain_db} is outside allowed range "
                f"[{limits.min_gain_db}, {limits.max_gain_db}]"
            )

    def add(self, delta_db: float) -> GainValue:
        return GainValue(gain_db=self.gain_db + delta_db)

    def subtract(self, delta_db: float) -> GainValue:
        return GainValue(gain_db=self.gain_db - delta_db)

    def to_dict(self) -> dict:
        return {"gain_db": self.gain_db}
        return GainValue(gain_db=self.gain_db + delta_db)

    def subtract(self, delta_db: float) -> "GainValue":
        return GainValue(gain_db=self.gain_db - delta_db)

    def quantize(self, limits: GainLimits) -> "GainValue":
        clamped = limits.clamp(self.gain_db)
        steps = round((clamped - limits.min_gain_db) / limits.step_gain_db)
        quantized = limits.min_gain_db + steps * limits.step_gain_db
        quantized = limits.clamp(quantized)
        return GainValue(gain_db=quantized)

    def to_dict(self) -> dict:
        return {
            "gain_db": self.gain_db,
        }


@dataclass(slots=True, frozen=True)
class GainConfiguration:
    gain: GainValue
    agc_enabled: bool = False
    attenuation_db: float = 0.0
    preamp_enabled: bool = False

    def effective_gain_db(self) -> float:
        return self.gain.gain_db - self.attenuation_db

    def with_gain(self, gain_db: float) -> "GainConfiguration":
        return GainConfiguration(
            gain=GainValue(gain_db=gain_db),
            agc_enabled=self.agc_enabled,
            attenuation_db=self.attenuation_db,
            preamp_enabled=self.preamp_enabled,
        )

    def enable_agc(self) -> "GainConfiguration":
        return GainConfiguration(
            gain=self.gain,
            agc_enabled=True,
            attenuation_db=self.attenuation_db,
            preamp_enabled=self.preamp_enabled,
        )

    def disable_agc(self) -> "GainConfiguration":
        return GainConfiguration(
            gain=self.gain,
            agc_enabled=False,
            attenuation_db=self.attenuation_db,
            preamp_enabled=self.preamp_enabled,
        )

    def to_dict(self) -> dict:
        return {
            "gain": self.gain.to_dict(),
            "agc_enabled": self.agc_enabled,
            "attenuation_db": self.attenuation_db,
            "preamp_enabled": self.preamp_enabled,
            "effective_gain_db": self.effective_gain_db(),
        }