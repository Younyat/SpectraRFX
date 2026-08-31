from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class SetSpanUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self, span_hz: float) -> dict:
        if span_hz <= 0:
            raise ValueError("Span must be > 0")
        return {"status": "ok", "span_hz": span_hz}