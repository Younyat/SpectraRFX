from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, List
from app.domain.repositories.capture_repository import CaptureRepository
from app.domain.entities.rf_capture import RFCapture

class JsonCaptureRepository(CaptureRepository):
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, capture: RFCapture) -> str:
        data = {"capture_id": capture.capture_id}
        path = self.storage_dir / f"{capture.capture_id}.json"
        with open(path, "w") as f:
            json.dump(data, f)
        return capture.capture_id
    
    def get_by_id(self, capture_id: str) -> Optional[RFCapture]:
        path = self.storage_dir / f"{capture_id}.json"
        if not path.exists():
            return None
        return None
    
    def list_by_session(self, session_id: str) -> List[RFCapture]:
        return []
    
    def delete(self, capture_id: str) -> None:
        path = self.storage_dir / f"{capture_id}.json"
        if path.exists():
            path.unlink()
    
    def list_all(self) -> List[RFCapture]:
        return []