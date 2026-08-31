from __future__ import annotations
from app.application.interfaces.device_control_provider import DeviceControlProvider

class SetGainUseCase:
    def __init__(self, device_control: DeviceControlProvider):
        self.device_control = device_control
    
    def execute(self, gain_db: float) -> dict:
        if not 0 <= gain_db <= 76:
            raise ValueError("Gain must be between 0 and 76 dB")
        self.device_control.set_gain(gain_db)
        return {"status": "ok", "gain_db": gain_db}