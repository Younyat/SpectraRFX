from __future__ import annotations

class StartDemodulationUseCase:
    def __init__(self, demodulator_provider=None):
        self.demodulator_provider = demodulator_provider

    def execute(self, mode: str) -> dict:
        if mode not in ["AM", "FM", "WFM", "USB", "LSB"]:
            raise ValueError(f"Invalid demodulation mode: {mode}")
        return {"status": "ok", "demodulation_mode": mode}
