from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class SetCenterFrequencyUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self, frequency_hz: float) -> dict:
        if frequency_hz <= 0:
            raise ValueError("Frequency must be > 0")
        self.device_control.set_center_frequency(frequency_hz)
        return {"status": "ok", "center_frequency_hz": frequency_hz}