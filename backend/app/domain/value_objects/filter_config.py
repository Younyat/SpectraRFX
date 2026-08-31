from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


FilterType = Literal["off", "low_pass", "high_pass", "band_pass", "band_stop", "notch"]
WindowType = Literal["rectangular", "hann", "hamming", "blackman"]


@dataclass(slots=True, frozen=True)
class FilterDesignConfig:
    filter_type: FilterType = "off"
    sample_rate_hz: float = 1_000_000.0
    cutoff_hz: Optional[float] = None
    low_cut_hz: Optional[float] = None
    high_cut_hz: Optional[float] = None
    transition_hz: float = 5_000.0
    order: int = 101
    window: WindowType = "hann"
    gain: float = 1.0

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if self.transition_hz <= 0:
            raise ValueError("transition_hz must be > 0")
        if self.order <= 0:
            raise ValueError("order must be > 0")
        if self.gain <= 0:
            raise ValueError("gain must be > 0")

        nyquist = self.sample_rate_hz / 2.0

        if self.filter_type in {"low_pass", "high_pass"}:
            if self.cutoff_hz is None:
                raise ValueError("cutoff_hz is required for low_pass and high_pass")
            if self.cutoff_hz <= 0 or self.cutoff_hz >= nyquist:
                raise ValueError("cutoff_hz must be in (0, nyquist)")

        if self.filter_type in {"band_pass", "band_stop", "notch"}:
            if self.low_cut_hz is None or self.high_cut_hz is None:
                raise ValueError("low_cut_hz and high_cut_hz are required for band filters")
            if self.low_cut_hz <= 0:
                raise ValueError("low_cut_hz must be > 0")
            if self.high_cut_hz >= nyquist:
                raise ValueError("high_cut_hz must be < nyquist")
            if self.low_cut_hz >= self.high_cut_hz:
                raise ValueError("low_cut_hz must be lower than high_cut_hz")

    @property
    def enabled(self) -> bool:
        return self.filter_type != "off"

    @property
    def bandwidth_hz(self) -> Optional[float]:
        if self.low_cut_hz is None or self.high_cut_hz is None:
            return None
        return self.high_cut_hz - self.low_cut_hz

    @property
    def center_hz(self) -> Optional[float]:
        if self.low_cut_hz is None or self.high_cut_hz is None:
            return None
        return self.low_cut_hz + (self.high_cut_hz - self.low_cut_hz) / 2.0

    def with_disabled(self) -> "FilterDesignConfig":
        return FilterDesignConfig(
            filter_type="off",
            sample_rate_hz=self.sample_rate_hz,
            transition_hz=self.transition_hz,
            order=self.order,
            window=self.window,
            gain=self.gain,
        )

    def to_dict(self) -> dict:
        return {
            "filter_type": self.filter_type,
            "sample_rate_hz": self.sample_rate_hz,
            "cutoff_hz": self.cutoff_hz,
            "low_cut_hz": self.low_cut_hz,
            "high_cut_hz": self.high_cut_hz,
            "transition_hz": self.transition_hz,
            "order": self.order,
            "window": self.window,
            "gain": self.gain,
            "enabled": self.enabled,
            "bandwidth_hz": self.bandwidth_hz,
            "center_hz": self.center_hz,
        }


@dataclass(slots=True, frozen=True)
class NotchFilterConfig:
    center_hz: float
    width_hz: float
    sample_rate_hz: float
    order: int = 101
    window: WindowType = "hann"

    def __post_init__(self) -> None:
        if self.center_hz <= 0:
            raise ValueError("center_hz must be > 0")
        if self.width_hz <= 0:
            raise ValueError("width_hz must be > 0")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if self.order <= 0:
            raise ValueError("order must be > 0")

        nyquist = self.sample_rate_hz / 2.0
        low = self.center_hz - self.width_hz / 2.0
        high = self.center_hz + self.width_hz / 2.0

        if low <= 0:
            raise ValueError("notch lower edge must be > 0")
        if high >= nyquist:
            raise ValueError("notch upper edge must be < nyquist")

    @property
    def low_cut_hz(self) -> float:
        return self.center_hz - self.width_hz / 2.0

    @property
    def high_cut_hz(self) -> float:
        return self.center_hz + self.width_hz / 2.0

    def as_filter_design_config(self) -> FilterDesignConfig:
        return FilterDesignConfig(
            filter_type="notch",
            sample_rate_hz=self.sample_rate_hz,
            low_cut_hz=self.low_cut_hz,
            high_cut_hz=self.high_cut_hz,
            order=self.order,
            window=self.window,
        )

    def to_dict(self) -> dict:
        return {
            "center_hz": self.center_hz,
            "width_hz": self.width_hz,
            "sample_rate_hz": self.sample_rate_hz,
            "order": self.order,
            "window": self.window,
            "low_cut_hz": self.low_cut_hz,
            "high_cut_hz": self.high_cut_hz,
        }