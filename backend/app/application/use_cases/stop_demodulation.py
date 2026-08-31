from __future__ import annotations

class StopDemodulationUseCase:
    def __init__(self, demodulator_provider=None):
        self.demodulator_provider = demodulator_provider

    def execute(self) -> dict:
        return {"status": "ok", "demodulation_stopped": True}
