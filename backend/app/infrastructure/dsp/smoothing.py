from __future__ import annotations
import numpy as np

class SmoothingEngine:
    def __init__(self, factor: float = 0.15):
        self.factor = max(0.0, min(1.0, factor))
        self.last_data = None
    
    def smooth(self, data: np.ndarray) -> np.ndarray:
        if self.last_data is None:
            self.last_data = data.copy()
            return data
        
        smoothed = self.factor * data + (1 - self.factor) * self.last_data
        self.last_data = smoothed.copy()
        return smoothed
    
    def reset(self) -> None:
        self.last_data = None


def trace_average(current: np.ndarray, previous: np.ndarray | None, factor: float) -> np.ndarray:
    if current.ndim != 1:
        raise ValueError("current must be a 1D array")
    if previous is None:
        return current.astype(np.float32, copy=True)
    if previous.ndim != 1:
        raise ValueError("previous must be a 1D array")
    if len(current) != len(previous):
        raise ValueError("current and previous must have the same length")
    if not 0.0 < factor <= 1.0:
        raise ValueError("factor must be in (0, 1]")

    return (factor * current + (1.0 - factor) * previous).astype(np.float32)