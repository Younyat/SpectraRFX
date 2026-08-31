from __future__ import annotations
import uuid

class SavePresetUseCase:
    def __init__(self, preset_repository=None):
        self.preset_repository = preset_repository

    def execute(self, name: str, config: dict) -> dict:
        preset_id = str(uuid.uuid4())[:8]
        return {"status": "ok", "preset_id": preset_id, "name": name}
