from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class FrequencyRange:
    start_hz: float
    stop_hz: float

    def __post_init__(self) -> None:
        if self.start_hz < 0:
            raise ValueError("start_hz must be >= 0")
        if self.stop_hz <= 0:
            raise ValueError("stop_hz must be > 0")
        if self.start_hz >= self.stop_hz:
            raise ValueError("start_hz must be lower than stop_hz")

    @property
    def span_hz(self) -> float:
        return self.stop_hz - self.start_hz

    @property
    def center_hz(self) -> float:
        return self.start_hz + self.span_hz / 2.0

    def contains(self, frequency_hz: float) -> bool:
        return self.start_hz <= frequency_hz <= self.stop_hz

    def overlaps(self, other: "FrequencyRange") -> bool:
        return not (self.stop_hz < other.start_hz or other.stop_hz < self.start_hz)

    def intersection(self, other: "FrequencyRange") -> "FrequencyRange | None":
        if not self.overlaps(other):
            return None

        start = max(self.start_hz, other.start_hz)
        stop = min(self.stop_hz, other.stop_hz)

        if start >= stop:
            return None

        return FrequencyRange(start_hz=start, stop_hz=stop)

    def expand(self, margin_hz: float) -> "FrequencyRange":
        if margin_hz < 0:
            raise ValueError("margin_hz must be >= 0")

        start = max(0.0, self.start_hz - margin_hz)
        stop = self.stop_hz + margin_hz
        return FrequencyRange(start_hz=start, stop_hz=stop)

    def shift(self, delta_hz: float) -> "FrequencyRange":
        new_start = self.start_hz + delta_hz
        new_stop = self.stop_hz + delta_hz

        if new_start < 0:
            raise ValueError("shift would move the range below 0 Hz")

        return FrequencyRange(start_hz=new_start, stop_hz=new_stop)

    def clamp_to(self, outer: "FrequencyRange") -> "FrequencyRange":
        if not self.overlaps(outer):
            raise ValueError("cannot clamp a non-overlapping range")

        start = max(self.start_hz, outer.start_hz)
        stop = min(self.stop_hz, outer.stop_hz)

        if start >= stop:
            raise ValueError("clamped range would be invalid")

        return FrequencyRange(start_hz=start, stop_hz=stop)

    @classmethod
    def from_center_span(cls, center_hz: float, span_hz: float) -> "FrequencyRange":
        if center_hz <= 0:
            raise ValueError("center_hz must be > 0")
        if span_hz <= 0:
            raise ValueError("span_hz must be > 0")

        half_span = span_hz / 2.0
        start = center_hz - half_span
        stop = center_hz + half_span

        if start < 0:
            raise ValueError("resulting start frequency would be below 0 Hz")

        return cls(start_hz=start, stop_hz=stop)

    def to_dict(self) -> dict:
        return {
            "start_hz": self.start_hz,
            "stop_hz": self.stop_hz,
            "span_hz": self.span_hz,
            "center_hz": self.center_hz,
        }