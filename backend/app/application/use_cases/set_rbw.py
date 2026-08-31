from __future__ import annotations

class SetRBWUseCase:
    def execute(self, rbw_hz: float) -> dict:
        if rbw_hz <= 0:
            raise ValueError("RBW must be > 0")
        return {"status": "ok", "rbw_hz": rbw_hz}