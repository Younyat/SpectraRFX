from __future__ import annotations
from abc import ABC, abstractmethod
from app.domain.entities.device_state import DeviceState

class DeviceRepository(ABC):
    @abstractmethod
    def get_current_state(self) -> DeviceState:
        pass
    
    @abstractmethod
    def save_state(self, state: DeviceState) -> None:
        pass
    
    @abstractmethod
    def update_frequency(self, frequency_hz: float) -> None:
        pass
    
    @abstractmethod
    def update_gain(self, gain_db: float) -> None:
        pass