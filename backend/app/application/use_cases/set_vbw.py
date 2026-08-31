from __future__ import annotations

class SetVBWUseCase:
    def execute(self, vbw_hz: float) -> dict:
        if vbw_hz <= 0:
            raise ValueError("VBW must be > 0")
        return {"status": "ok", "vbw_hz": vbw_hz}