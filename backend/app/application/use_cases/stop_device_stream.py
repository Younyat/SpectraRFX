from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class StopDeviceStreamUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self) -> dict:
        result = self.device_control.stop_streaming()
        return result
