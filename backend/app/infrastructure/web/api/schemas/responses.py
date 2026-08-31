from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional

class SpectrumResponse(BaseModel):
    timestamp_utc: str
    center_frequency_hz: float
    span_hz: float
    frequencies_hz: List[float]
    levels_db: List[float]

class MarkerResponse(BaseModel):
    marker_id: str
    label: str
    frequency_hz: float
    level_db: Optional[float] = None
    enabled: bool = True

class DeviceStatusResponse(BaseModel):
    status: str
    frequency_hz: float
    gain_db: float
    is_streaming: bool

class RecordingResponse(BaseModel):
    recording_id: str
    filename: str
    status: str
    duration_seconds: float
    file_size_bytes: int = 0

class PresetResponse(BaseModel):
    preset_id: str
    name: str
    config: dict