from __future__ import annotations
import numpy as np
from scipy import signal

class SSBDemodulator:
    def __init__(self, sample_rate_hz: float = 2_000_000.0, mode: str = "usb"):
        self.sample_rate = sample_rate_hz
        self.mode = mode
        self.demodulated = None
    
    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        if self.mode == "usb":
            demod = iq_samples.real + 1j * iq_samples.imag
        else:
            demod = iq_samples.real - 1j * iq_samples.imag
        
        audio = np.real(demod)
        sos = signal.butter(4, 3000, 'low', fs=self.sample_rate, output='sos')
        self.demodulated = signal.sosfilt(sos, audio)
        return self.demodulated
    
    def get_audio(self, audio_sample_rate: int = 8000) -> np.ndarray:
        if self.demodulated is None:
            return np.array([])
        decimation = int(self.sample_rate / audio_sample_rate)
        audio = self.demodulated[::decimation]
        audio_int16 = (audio * 32767 / (np.max(np.abs(audio)) + 1e-10)).astype(np.int16)
        return audio_int16