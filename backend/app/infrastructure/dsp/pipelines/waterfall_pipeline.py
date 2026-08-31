from __future__ import annotations
import numpy as np
from collections import deque

class WaterfallPipeline:
    def __init__(self, history_size: int = 400):
        self.history_size = history_size
        self.history = deque(maxlen=history_size)
    
    def add_frame(self, spectrum: np.ndarray) -> np.ndarray:
        self.history.append(spectrum.copy())
        return np.array(list(self.history))
    
    def get_waterfall(self) -> np.ndarray:
        if not self.history:
            return np.array([])
        return np.array(list(self.history))
    
    def clear(self) -> None:
        self.history.clear()
        return normalized.astype(np.float32)