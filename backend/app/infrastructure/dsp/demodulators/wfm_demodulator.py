from __future__ import annotations
import numpy as np
from scipy import signal

class WFMDemodulator:
    def __init__(self, sample_rate_hz: float = 2_000_000.0, deviation_hz: float = 75_000.0):
        self.sample_rate = sample_rate_hz
        self.deviation = deviation_hz
        self.demodulated = None
    
    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        phase = np.unwrap(np.angle(iq_samples))
        phase_diff = np.diff(phase)
        demod = phase_diff * self.sample_rate / (2 * np.pi * self.deviation)
        sos = signal.butter(4, 15000, 'low', fs=self.sample_rate, output='sos')
        self.demodulated = signal.sosfilt(sos, demod)
        return self.demodulated
    
    def get_audio(self, audio_sample_rate: int = 44100) -> np.ndarray:
        if self.demodulated is None:
            return np.array([])
        decimation = int(self.sample_rate / audio_sample_rate)
        audio = self.demodulated[::decimation]
        audio_int16 = (audio * 32767 / (np.max(np.abs(audio)) + 1e-10)).astype(np.int16)
        return audio_int16