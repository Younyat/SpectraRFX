from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

class MockDeviceAdapter:
    def __init__(self):
        self.is_open = False
        self.is_streaming = False
        self.frequency_hz = 1_000_000_000
        self.gain_db = 20.0
        self.sample_rate_hz = 2_000_000
    
    def open(self):
        self.is_open = True
        logger.info("Mock device opened")
    
    def close(self):
        self.is_open = False
        logger.info("Mock device closed")
    
    def start_streaming(self, *args, **kwargs):
        if not self.is_open:
            self.open()
        self.is_streaming = True
        logger.info("Mock device streaming started")
        return {"status": "streaming_started", "driver": "mock"}
    
    def stop_streaming(self):
        self.is_streaming = False
        logger.info("Mock device streaming stopped")
        return {"status": "streaming_stopped", "driver": "mock"}
    
    def set_center_frequency_hz(self, frequency_hz: float):
        self.frequency_hz = frequency_hz
        logger.debug(f"Frequency set to {frequency_hz/1e6:.1f} MHz")

    def set_center_frequency(self, frequency_hz: float):
        self.set_center_frequency_hz(frequency_hz)
        return {"status": "ok", "center_frequency_hz": frequency_hz}
    
    def set_sample_rate_hz(self, sample_rate_hz: float):
        self.sample_rate_hz = sample_rate_hz
        logger.debug(f"Sample rate set to {sample_rate_hz/1e6:.1f} MHz")

    def set_sample_rate(self, sample_rate_hz: float):
        self.set_sample_rate_hz(sample_rate_hz)
        return {"status": "ok", "sample_rate_hz": sample_rate_hz}
    
    def set_gain_db(self, gain_db: float):
        self.gain_db = gain_db
        logger.debug(f"Gain set to {gain_db} dB")

    def set_gain(self, gain_db: float):
        self.set_gain_db(gain_db)
        return {"status": "ok", "gain_db": gain_db}
    
    def read_samples(self, num_samples: int) -> np.ndarray:
        if not self.is_streaming:
            return np.array([])
        noise = np.random.normal(0, 0.1, num_samples)
        signal_freq = 10_000_000
        t = np.arange(num_samples) / self.sample_rate_hz
        signal = 0.5 * np.exp(1j * 2 * np.pi * signal_freq * t)
        return (signal + noise).astype(np.complex64)
    
    def get_device_info(self) -> dict:
        return {
            "name": "Mock SDR Device",
            "driver": "mock",
        }
