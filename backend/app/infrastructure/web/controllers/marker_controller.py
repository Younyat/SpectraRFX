from __future__ import annotations

from app.domain.entities.marker import Marker


class MarkerController:
    def __init__(
        self,
        create_marker_use_case,
        move_marker_use_case,
        delete_marker_use_case,
    ):
        self._create_marker_use_case = create_marker_use_case
        self._move_marker_use_case = move_marker_use_case
        self._delete_marker_use_case = delete_marker_use_case
        self._markers: dict[str, Marker] = {}

    def create_marker(self, label: str, frequency_hz: float) -> dict:
        result = self._create_marker_use_case.execute(label, frequency_hz)
        marker = Marker(
            marker_id=result.marker_id,
            label=result.label,
            frequency_hz=result.frequency_hz,
            marker_type=result.marker_type,
            mode=result.mode,
            enabled=result.enabled,
            locked=result.locked,
            reference_marker_id=result.reference_marker_id,
            color=result.color,
            metadata=result.metadata or {},
        )
        self._markers[marker.marker_id] = marker
        return result.to_dict()

    def move_marker(self, marker_id: str, frequency_hz: float) -> dict:
        marker = self._markers.get(marker_id)
        if marker is None:
            raise ValueError(f"Marker not found: {marker_id}")

        marker.move_to(frequency_hz)
        result = self._move_marker_use_case.execute(marker_id, frequency_hz)
        return result.to_dict()

    def delete_marker(self, marker_id: str) -> dict:
        if marker_id not in self._markers:
            raise ValueError(f"Marker not found: {marker_id}")

        result = self._delete_marker_use_case.execute(marker_id)
        self._markers.pop(marker_id, None)
        return result

    def list_markers(self) -> dict:
        return {
            "markers": [marker.to_dict() for marker in self._markers.values()],
        }
