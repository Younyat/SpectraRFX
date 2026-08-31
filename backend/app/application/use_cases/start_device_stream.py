from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class StartDeviceStreamUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self, settings) -> dict:
        result = self.device_control.start_streaming(settings)
        return result