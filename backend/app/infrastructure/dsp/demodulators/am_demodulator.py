from __future__ import annotations
import numpy as np

class AMDemodulator:
    def __init__(self, sample_rate_hz: float = 2_000_000.0):
        self.sample_rate = sample_rate_hz
        self.demodulated = None
    
    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        envelope = np.abs(iq_samples)
        self.demodulated = envelope - np.mean(envelope)
        return self.demodulated
    
    def get_audio(self, audio_sample_rate: int = 8000) -> np.ndarray:
        if self.demodulated is None:
            return np.array([])
        decimation = int(self.sample_rate / audio_sample_rate)
        audio = self.demodulated[::decimation]
        audio_int16 = (audio * 32767 / (np.max(np.abs(audio)) + 1e-10)).astype(np.int16)
        return audio_int16