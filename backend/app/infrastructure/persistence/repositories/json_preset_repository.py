from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.domain.repositories.preset_repository import PresetRepository

class JsonPresetRepository(PresetRepository):
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, preset_id: str, name: str, config: Dict[str, Any]) -> None:
        data = {"preset_id": preset_id, "name": name, "config": config}
        path = self.storage_dir / f"{preset_id}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def get_by_id(self, preset_id: str) -> Optional[Dict[str, Any]]:
        path = self.storage_dir / f"{preset_id}.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f)
    
    def list_all(self) -> List[Dict[str, Any]]:
        presets = []
        for path in self.storage_dir.glob("*.json"):
            with open(path, "r") as f:
                presets.append(json.load(f))
        return presets
    
    def delete(self, preset_id: str) -> None:
        path = self.storage_dir / f"{preset_id}.json"
        if path.exists():
            path.unlink()
    
    def update(self, preset_id: str, config: Dict[str, Any]) -> None:
        data = self.get_by_id(preset_id)
        if data:
            data["config"] = config
            self.create(preset_id, data["name"], config)