from __future__ import annotations

class SetDetectorModeUseCase:
    def execute(self, mode: str) -> dict:
        if mode not in ["sample", "average", "peak", "min"]:
            raise ValueError(f"Invalid detector mode: {mode}")
        return {"status": "ok", "detector_mode": mode}