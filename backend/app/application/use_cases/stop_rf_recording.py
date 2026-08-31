from __future__ import annotations
from app.application.dto.recording_dto import RecordingDTO

class StopRFRecordingUseCase:
    def __init__(self, recording_provider=None):
        self.recording_provider = recording_provider

    def execute(self, recording_id: str) -> RecordingDTO:
        return RecordingDTO(
            recording_id=recording_id,
            filename="",
            duration_seconds=0.0,
            status="stopped",
        )
