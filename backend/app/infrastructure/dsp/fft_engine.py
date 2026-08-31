from __future__ import annotations
import numpy as np
from scipy.fft import fft

class FFTEngine:
    def __init__(self, fft_size: int = 4096, window: str = "hann"):
        self.fft_size = fft_size
        self.window_type = window
        self._create_window()
    
    def _create_window(self) -> None:
        if self.window_type == "hann":
            self.window = np.hanning(self.fft_size)
        elif self.window_type == "hamming":
            self.window = np.hamming(self.fft_size)
        elif self.window_type == "blackman":
            self.window = np.blackman(self.fft_size)
        else:
            self.window = np.ones(self.fft_size)
    
    def compute(self, samples: np.ndarray) -> np.ndarray:
        windowed = samples[:self.fft_size] * self.window
        spectrum = fft(windowed)
        magnitude = np.abs(spectrum) / self.fft_size
        return magnitude[:self.fft_size//2]
    
    def compute_power_db(self, samples: np.ndarray, ref_impedance: float = 50.0) -> np.ndarray:
        magnitude = self.compute(samples)
        power_watts = (magnitude ** 2) / ref_impedance
        power_db = 10 * np.log10(power_watts + 1e-20)
        return power_db