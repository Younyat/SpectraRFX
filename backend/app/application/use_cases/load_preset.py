from __future__ import annotations

class LoadPresetUseCase:
    def __init__(self, preset_repository=None):
        self.preset_repository = preset_repository

    def execute(self, preset_id: str) -> dict:
        return {"status": "ok", "preset_id": preset_id, "config": {}}
