from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass(slots=True)
class RFCapture:
    capture_id: str
    session_id: str
    timestamp_utc: str
    center_frequency_hz: float
    sample_rate_hz: float
    duration_seconds: float
    file_path: Optional[str] = None
    file_size_bytes: int = 0
    sample_count: int = 0
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "capture_id": self.capture_id,
            "session_id": self.session_id,
            "timestamp_utc": self.timestamp_utc,
            "center_frequency_hz": self.center_frequency_hz,
            "sample_rate_hz": self.sample_rate_hz,
            "duration_seconds": self.duration_seconds,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "sample_count": self.sample_count,
        }
