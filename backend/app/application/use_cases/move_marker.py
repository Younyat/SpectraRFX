from __future__ import annotations
from app.application.dto.marker_dto import MarkerDTO

class MoveMarkerUseCase:
    def execute(self, marker_id: str, frequency_hz: float) -> MarkerDTO:
        return MarkerDTO(
            marker_id=marker_id,
            label="Marker",
            frequency_hz=frequency_hz,
        )