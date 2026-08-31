from __future__ import annotations
import numpy as np

class WindowingEngine:
    WINDOW_TYPES = ["rectangular", "hann", "hamming", "blackman", "bartlett"]
    
    @staticmethod
    def create_window(window_type: str, size: int) -> np.ndarray:
        if window_type == "rectangular":
            return np.ones(size)
        elif window_type == "hann":
            return np.hanning(size)
        elif window_type == "hamming":
            return np.hamming(size)
        elif window_type == "blackman":
            return np.blackman(size)
        elif window_type == "bartlett":
            return np.bartlett(size)
        else:
            return np.ones(size)
    
    @staticmethod
    def apply_window(samples: np.ndarray, window_type: str = "hann") -> np.ndarray:
        window = WindowingEngine.create_window(window_type, len(samples))
        return samples * window
    
    @staticmethod
    def get_coherent_gain(window_type: str) -> float:
        gains = {
            "rectangular": 1.0,
            "hann": 0.5,
            "hamming": 0.54,
            "blackman": 0.42,
            "bartlett": 0.5,
        }
        return gains.get(window_type, 1.0)