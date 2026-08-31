from __future__ import annotations

class SetNoiseFloorOffsetUseCase:
    def execute(self, offset_db: float) -> dict:
        return {"status": "ok", "noise_floor_offset_db": offset_db}