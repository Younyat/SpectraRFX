from __future__ import annotations
import numpy as np

class IQPassthrough:
    def __init__(self, sample_rate_hz: float = 2_000_000.0):
        self.sample_rate = sample_rate_hz
        self.data = None
    
    def process(self, iq_samples: np.ndarray) -> np.ndarray:
        self.data = iq_samples.copy()
        return self.data
    
    def get_iq(self) -> np.ndarray:
        return self.data if self.data is not None else np.array([])