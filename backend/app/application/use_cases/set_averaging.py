from __future__ import annotations

class SetAveragingUseCase:
    def execute(self, enabled: bool, factor: float = 0.2) -> dict:
        return {"status": "ok", "averaging_enabled": enabled, "factor": factor}