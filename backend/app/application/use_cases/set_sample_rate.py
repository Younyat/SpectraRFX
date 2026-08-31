from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class SetSampleRateUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self, sample_rate_hz: float) -> dict:
        if sample_rate_hz <= 0:
            raise ValueError("Sample rate must be > 0")
        self.device_control.set_sample_rate(sample_rate_hz)
        return {"status": "ok", "sample_rate_hz": sample_rate_hz}