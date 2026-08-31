from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

class PresetRepository(ABC):
    @abstractmethod
    def create(self, preset_id: str, name: str, config: Dict[str, Any]) -> None:
        pass
    
    @abstractmethod
    def get_by_id(self, preset_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def list_all(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def delete(self, preset_id: str) -> None:
        pass
    
    @abstractmethod
    def update(self, preset_id: str, config: Dict[str, Any]) -> None:
        pass