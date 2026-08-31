from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(slots=True)
class RecordingDTO:
    recording_id: str
    filename: str
    duration_seconds: float
    file_size_bytes: int = 0
    format: str = "iq"
    status: str = "completed"
    error_message: Optional[str] = None

    @classmethod
    def from_entity(cls, entity) -> "RecordingDTO":
        return cls(
            recording_id=getattr(entity, "capture_id", getattr(entity, "recording_id", "")),
            filename=getattr(entity, "file_path", "") or "",
            duration_seconds=getattr(entity, "duration_seconds", 0.0),
            file_size_bytes=getattr(entity, "file_size_bytes", 0),
            status=getattr(entity, "status", "completed"),
            error_message=getattr(entity, "error_message", None),
        )

    def to_dict(self) -> dict:
        return asdict(self)
