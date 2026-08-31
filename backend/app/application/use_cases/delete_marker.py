from __future__ import annotations

class DeleteMarkerUseCase:
    def execute(self, marker_id: str) -> dict:
        return {"status": "ok", "deleted_marker_id": marker_id}