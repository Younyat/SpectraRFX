from __future__ import annotations
from pydantic import BaseModel
from typing import Optional

class SetFrequencyRequest(BaseModel):
    frequency_hz: float

class SetGainRequest(BaseModel):
    gain_db: float

class SetSpanRequest(BaseModel):
    span_hz: float

class CreateMarkerRequest(BaseModel):
    label: str
    frequency_hz: float

class StartRecordingRequest(BaseModel):
    duration_seconds: float = 10.0

class SavePresetRequest(BaseModel):
    name: str
    config: dict = {}

class SetRBWRequest(BaseModel):
    rbw_hz: float

class SetVBWRequest(BaseModel):
    vbw_hz: float

class StartDemodulationRequest(BaseModel):
    mode: str

class ApplyFilterRequest(BaseModel):
    filter_type: str
    low_hz: Optional[float] = None
    high_hz: Optional[float] = None