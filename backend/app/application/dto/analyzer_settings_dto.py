from __future__ import annotations

from dataclasses import asdict, dataclass

from app.domain.entities.analyzer_settings import AnalyzerSettings


@dataclass(slots=True)
class AnalyzerSettingsDTO:
    center_frequency_hz: float
    span_hz: float
    sample_rate_hz: float
    gain_db: float
    rbw_hz: float
    vbw_hz: float
    reference_level_db: float
    detector_mode: str = "sample"

    @classmethod
    def from_entity(cls, entity: AnalyzerSettings) -> "AnalyzerSettingsDTO":
        return cls(
            center_frequency_hz=entity.frequency.center_frequency_hz,
            span_hz=entity.frequency.span_hz,
            sample_rate_hz=entity.frequency.sample_rate_hz,
            gain_db=entity.gain.gain_db,
            rbw_hz=entity.resolution.rbw_hz,
            vbw_hz=entity.resolution.vbw_hz,
            reference_level_db=entity.display.reference_level_db,
            detector_mode=entity.trace.detector_mode,
        )

    def to_dict(self) -> dict:
        return asdict(self)
