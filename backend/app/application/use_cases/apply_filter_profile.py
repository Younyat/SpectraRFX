from __future__ import annotations

class ApplyFilterProfileUseCase:
    def execute(self, filter_type: str, low_hz: float, high_hz: float) -> dict:
        return {"status": "ok", "filter_type": filter_type, "low_hz": low_hz, "high_hz": high_hz}
