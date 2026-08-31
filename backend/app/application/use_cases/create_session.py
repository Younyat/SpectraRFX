from __future__ import annotations
import uuid
from app.application.dto.session_dto import SessionDTO

class CreateSessionUseCase:
    def __init__(self, session_repository=None):
        self.session_repository = session_repository

    def execute(self, name: str) -> SessionDTO:
        session_id = str(uuid.uuid4())[:8]
        from datetime import datetime
        return SessionDTO(
            session_id=session_id,
            name=name,
            created_utc=datetime.utcnow().isoformat(),
        )
