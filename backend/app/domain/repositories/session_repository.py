from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List
from app.domain.entities.session import Session

class SessionRepository(ABC):
    @abstractmethod
    def create(self, session: Session) -> str:
        pass
    
    @abstractmethod
    def get_by_id(self, session_id: str) -> Optional[Session]:
        pass
    
    @abstractmethod
    def list_all(self) -> List[Session]:
        pass
    
    @abstractmethod
    def delete(self, session_id: str) -> None:
        pass