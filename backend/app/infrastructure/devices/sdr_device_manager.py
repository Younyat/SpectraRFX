from __future__ import annotations
import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

class SDRDeviceManager:
    def __init__(self, adapter=None):
        self.adapter = adapter
        self.device_state = None
    
    def open_device(self):
        if self.adapter is None:
            raise RuntimeError("No device adapter configured")
        try:
            self.adapter.open()
            logger.info("Device opened")
        except Exception as e:
            logger.error(f"Failed to open device: {e}")
            raise
    
    def close_device(self):
        if self.adapter is None:
            return
        try:
            self.adapter.close()
            logger.info("Device closed")
        except Exception as e:
            logger.error(f"Failed to close device: {e}")
    
    def start_streaming(self):
        if self.adapter is None:
            raise RuntimeError("No device adapter configured")
        try:
            self.adapter.start_streaming()
            logger.info("Streaming started")
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            raise
    
    def stop_streaming(self):
        if self.adapter is None:
            return
        try:
            self.adapter.stop_streaming()
            logger.info("Streaming stopped")
        except Exception as e:
            logger.error(f"Failed to stop streaming: {e}")
    
    def set_center_frequency(self, frequency_hz: float):
        if self.adapter is None:
            raise RuntimeError("No device adapter configured")
        self.adapter.set_center_frequency_hz(frequency_hz)
    
    def set_gain(self, gain_db: float):
        if self.adapter is None:
            raise RuntimeError("No device adapter configured")
        self.adapter.set_gain_db(gain_db)
    
    def set_sample_rate(self, sample_rate_hz: float):
        if self.adapter is None:
            raise RuntimeError("No device adapter configured")
        self.adapter.set_sample_rate_hz(sample_rate_hz)
    
    def read_samples(self, num_samples: int) -> np.ndarray:
        if self.adapter is None:
            return np.array([])
        return self.adapter.read_samples(num_samples)
    
    def get_device_state(self):
        return {
            "frequency_hz": self.adapter.frequency_hz if self.adapter else 0,
            "gain_db": self.adapter.gain_db if self.adapter else 0,
            "sample_rate_hz": self.adapter.sample_rate_hz if self.adapter else 0,
            "is_streaming": self.adapter.is_streaming if self.adapter else False,
        }