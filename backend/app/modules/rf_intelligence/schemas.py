from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config.runtime_settings import get_runtime_value


TemporalType = Literal["continuous", "bursty", "hopping_candidate", "unknown"]
ClassifierMode = Literal["rules_only", "hybrid_rules_ml", "ml_only"]


class SpectrumFrameInput(BaseModel):
    timestamp_utc: str | None = None
    center_frequency_hz: float
    span_hz: float
    start_frequency_hz: float | None = None
    stop_frequency_hz: float | None = None
    sample_rate_hz: float | None = None
    frequencies_hz: list[float] = Field(default_factory=list)
    levels_db: list[float] = Field(default_factory=list)


class RFIntelligenceSettings(BaseModel):
    threshold_offset_db: float = Field(
        default_factory=lambda: float(get_runtime_value("RF_INTELLIGENCE_THRESHOLD_OFFSET_DB", 10.0))
    )
    min_snr_db: float = Field(default_factory=lambda: float(get_runtime_value("RF_INTELLIGENCE_MIN_SNR_DB", 6.0)))
    min_bins: int = 2
    merge_gap_bins: int = 2
    classifier_mode: ClassifierMode = "hybrid_rules_ml"


class RFObjectEvidence(BaseModel):
    frequency_band_match: bool = False
    bandwidth_match: bool = False
    temporal_match: bool = False
    channel_grid_match: str | None = None
    notes: list[str] = Field(default_factory=list)


class RFObjectDetection(BaseModel):
    id: str
    track_id: str | None = None
    label: str
    candidate_family: str
    confidence: float
    center_frequency_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    bandwidth_hz: float
    occupied_bandwidth_hz: float
    snr_db: float
    peak_power_db: float
    mean_power_db: float
    noise_floor_db: float
    temporal_type: TemporalType
    persistence: float
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None
    evidence: RFObjectEvidence


class RFSceneAnalysis(BaseModel):
    timestamp_utc: str | None
    noise_floor_db: float | None
    threshold_db: float | None
    detections: list[RFObjectDetection]
    summary: dict[str, Any]


class RFAnalyzeRequest(BaseModel):
    frame: SpectrumFrameInput
    settings: RFIntelligenceSettings = Field(default_factory=RFIntelligenceSettings)
