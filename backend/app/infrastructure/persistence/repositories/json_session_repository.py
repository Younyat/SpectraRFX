from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, List
from app.domain.repositories.session_repository import SessionRepository
from app.domain.entities.session import Session

class JsonSessionRepository(SessionRepository):
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, session: Session) -> str:
        data = {"session_id": session.session_id, "name": getattr(session, 'name', '')}
        path = self.storage_dir / f"{session.session_id}.json"
        with open(path, "w") as f:
            json.dump(data, f)
        return session.session_id
    
    def get_by_id(self, session_id: str) -> Optional[Session]:
        path = self.storage_dir / f"{session_id}.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            data = json.load(f)
        session = Session(session_id=data["session_id"])
        return session
    
    def list_all(self) -> List[Session]:
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            session_id = path.stem
            session = self.get_by_id(session_id)
            if session:
                sessions.append(session)
        return sessions
    
    def delete(self, session_id: str) -> None:
        path = self.storage_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()