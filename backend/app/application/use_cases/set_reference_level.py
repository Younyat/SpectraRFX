from __future__ import annotations

class SetReferenceLevelUseCase:
    def execute(self, reference_level_db: float) -> dict:
        return {"status": "ok", "reference_level_db": reference_level_db}