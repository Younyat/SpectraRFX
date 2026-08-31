from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(slots=True)
class CaptureDTO:
    capture_id: str
    session_id: str
    timestamp_utc: str
    duration_seconds: float
    file_path: Optional[str] = None
    file_size_bytes: int = 0
    center_frequency_hz: Optional[float] = None
    sample_rate_hz: Optional[float] = None
    sample_count: int = 0
    metadata: dict | None = None

    @classmethod
    def from_entity(cls, entity) -> "CaptureDTO":
        return cls(
            capture_id=entity.capture_id,
            session_id=entity.session_id,
            timestamp_utc=entity.timestamp_utc,
            duration_seconds=entity.duration_seconds,
            file_path=entity.file_path,
            file_size_bytes=entity.file_size_bytes,
            center_frequency_hz=getattr(entity, "center_frequency_hz", None),
            sample_rate_hz=getattr(entity, "sample_rate_hz", None),
            sample_count=getattr(entity, "sample_count", 0),
            metadata=getattr(entity, "metadata", {}),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return data
