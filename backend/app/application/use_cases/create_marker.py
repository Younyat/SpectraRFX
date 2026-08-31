from __future__ import annotations
import uuid
from app.application.dto.marker_dto import MarkerDTO

class CreateMarkerUseCase:
    def execute(self, label: str, frequency_hz: float) -> MarkerDTO:
        marker_id = str(uuid.uuid4())[:8]
        return MarkerDTO(
            marker_id=marker_id,
            label=label,
            frequency_hz=frequency_hz,
        )