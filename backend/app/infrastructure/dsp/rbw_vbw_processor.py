from __future__ import annotations
import numpy as np

class RBWVBWProcessor:
    def __init__(self, rbw_hz: float, vbw_hz: float):
        self.rbw_hz = rbw_hz
        self.vbw_hz = vbw_hz
        self.averaging_buffer = []
    
    def process(self, spectrum: np.ndarray) -> np.ndarray:
        self.averaging_buffer.append(spectrum.copy())
        if len(self.averaging_buffer) > 1:
            return np.mean(self.averaging_buffer, axis=0)
        return spectrum
    
    def set_rbw(self, rbw_hz: float) -> None:
        self.rbw_hz = rbw_hz
    
    def set_vbw(self, vbw_hz: float) -> None:
        self.vbw_hz = vbw_hz
    
    def reset(self) -> None:
        self.averaging_buffer = []