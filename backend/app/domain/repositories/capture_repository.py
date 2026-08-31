from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List
from app.domain.entities.rf_capture import RFCapture

class CaptureRepository(ABC):
    @abstractmethod
    def create(self, capture: RFCapture) -> str:
        pass
    
    @abstractmethod
    def get_by_id(self, capture_id: str) -> Optional[RFCapture]:
        pass
    
    @abstractmethod
    def list_by_session(self, session_id: str) -> List[RFCapture]:
        pass
    
    @abstractmethod
    def delete(self, capture_id: str) -> None:
        pass
    
    @abstractmethod
    def list_all(self) -> List[RFCapture]:
        pass