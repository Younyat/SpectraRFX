from __future__ import annotations

class GetAudioStatusUseCase:
    def __init__(self, demodulator_provider=None):
        self.demodulator_provider = demodulator_provider

    def execute(self) -> dict:
        return {"status": "stopped", "is_playing": False}
