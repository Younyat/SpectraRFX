from __future__ import annotations
import numpy as np
from app.infrastructure.dsp.demodulators.am_demodulator import AMDemodulator

class DemodulationPipeline:
    def __init__(self, demod_type: str = "AM", sample_rate: float = 2_000_000.0):
        self.demod_type = demod_type
        self.sample_rate = sample_rate
        self.demodulator = self._create_demodulator()
    
    def _create_demodulator(self):
        if self.demod_type == "AM":
            return AMDemodulator(self.sample_rate)
        return None
    
    def process(self, iq_samples: np.ndarray) -> np.ndarray:
        if self.demodulator is None:
            return np.array([])
        return self.demodulator.demodulate(iq_samples)
    
    def get_audio(self, audio_sr: int = 8000) -> np.ndarray:
        if self.demodulator is None:
            return np.array([])
        return self.demodulator.get_audio(audio_sr)