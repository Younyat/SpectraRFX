"""RTL-SDR Device Adapter for USB RTL-SDR dongles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.config.constants import (
    RTLSDR_DEFAULT_CENTER_FREQUENCY_HZ,
    RTLSDR_DEFAULT_GAIN_DB,
    RTLSDR_DEFAULT_SAMPLE_RATE_HZ,
    ERROR_INVALID_CENTER_FREQUENCY,
    ERROR_INVALID_GAIN,
    ERROR_INVALID_SAMPLE_RATE,
    MAX_CENTER_FREQUENCY_HZ,
    MAX_GAIN_DB,
    MAX_SAMPLE_RATE_HZ,
    MIN_CENTER_FREQUENCY_HZ,
    MIN_GAIN_DB,
    MIN_SAMPLE_RATE_HZ,
)

logger = logging.getLogger(__name__)


@dataclass
class RTLSDRDeviceInfo:
    """Information about RTL-SDR device capabilities."""

    device_index: int = 0
    vendor_id: int = 0x0BDA
    product_id: int = 0x2838
    serial: str = ""
    has_bias_t: bool = False


class RTLSDRDeviceAdapter:
    """Adapter for RTL-SDR USB dongles using pyrtlsdr library."""

    def __init__(self, device_index: int = 0):
        """Initialize RTL-SDR device adapter.

        Args:
            device_index: USB device index to use
        """
        try:
            import rtlsdr
        except ImportError:
            raise ImportError(
                "pyrtlsdr not installed. Install with: pip install pyrtlsdr"
            )

        self._rtlsdr = rtlsdr
        self._device = None
        self._device_index = device_index
        self._is_streaming = False
        self._sample_rate_hz = RTLSDR_DEFAULT_SAMPLE_RATE_HZ
        self._center_frequency_hz = RTLSDR_DEFAULT_CENTER_FREQUENCY_HZ
        self._gain_db = RTLSDR_DEFAULT_GAIN_DB
        self._agc_enabled = False

    def open(self) -> None:
        """Open and initialize the RTL-SDR device."""
        try:
            self._device = self._rtlsdr.RtlSdr(device_index=self._device_index)
            logger.info(f"RTL-SDR device opened at index {self._device_index}")

            # Set initial parameters
            self._device.sample_rate = int(self._sample_rate_hz)
            self._device.center_freq = int(self._center_frequency_hz)
            self._device.gain = "auto"  # Start with AGC
            self._agc_enabled = True

        except Exception as e:
            logger.error(f"Failed to open RTL-SDR device: {e}")
            raise

    def close(self) -> None:
        """Close the RTL-SDR device."""
        if self._device is not None:
            try:
                if self._is_streaming:
                    self.stop_streaming()
                self._device.close()
                self._device = None
                logger.info("RTL-SDR device closed")
            except Exception as e:
                logger.error(f"Error closing RTL-SDR device: {e}")

    def is_open(self) -> bool:
        """Check if device is open."""
        return self._device is not None

    def set_center_frequency_hz(self, frequency_hz: float) -> None:
        """Set center frequency in Hz."""
        if not (MIN_CENTER_FREQUENCY_HZ <= frequency_hz <= MAX_CENTER_FREQUENCY_HZ):
            raise ValueError(
                ERROR_INVALID_CENTER_FREQUENCY.format(
                    MIN_CENTER_FREQUENCY_HZ, MAX_CENTER_FREQUENCY_HZ
                )
            )

        if self._device is None:
            raise RuntimeError("Device not open")

        try:
            self._device.center_freq = int(frequency_hz)
            self._center_frequency_hz = frequency_hz
            logger.debug(f"Center frequency set to {frequency_hz / 1e6:.2f} MHz")
        except Exception as e:
            logger.error(f"Failed to set center frequency: {e}")
            raise

    def set_sample_rate_hz(self, sample_rate_hz: float) -> None:
        """Set sample rate in Hz."""
        # RTL-SDR limited sample rates
        valid_rates = [250_000, 960_000, 1_024_000, 1_800_000, 1_920_000, 2_048_000, 2_400_000]

        if sample_rate_hz not in valid_rates:
            # Round to nearest valid rate
            sample_rate_hz = min(valid_rates, key=lambda x: abs(x - sample_rate_hz))
            logger.warning(f"RTL-SDR adjusted sample rate to {sample_rate_hz} Hz")

        if self._device is None:
            raise RuntimeError("Device not open")

        try:
            self._device.sample_rate = int(sample_rate_hz)
            self._sample_rate_hz = sample_rate_hz
            logger.debug(f"Sample rate set to {sample_rate_hz / 1e6:.2f} MHz")
        except Exception as e:
            logger.error(f"Failed to set sample rate: {e}")
            raise

    def set_gain_db(self, gain_db: float) -> None:
        """Set manual gain in dB. Disables AGC."""
        if not (MIN_GAIN_DB <= gain_db <= MAX_GAIN_DB):
            raise ValueError(
                ERROR_INVALID_GAIN.format(MIN_GAIN_DB, MAX_GAIN_DB)
            )

        if self._device is None:
            raise RuntimeError("Device not open")

        try:
            # RTL-SDR uses discrete gain values
            self._device.gain = "manual"
            self._device.gain = int(gain_db)
            self._gain_db = gain_db
            self._agc_enabled = False
            logger.debug(f"Gain set to {gain_db} dB (manual mode)")
        except Exception as e:
            logger.error(f"Failed to set gain: {e}")
            raise

    def set_agc(self, enabled: bool) -> None:
        """Enable/disable AGC (Automatic Gain Control)."""
        if self._device is None:
            raise RuntimeError("Device not open")

        try:
            if enabled:
                self._device.gain = "auto"
                self._agc_enabled = True
                logger.debug("AGC enabled")
            else:
                self._device.gain = "manual"
                self._agc_enabled = False
                logger.debug("AGC disabled")
        except Exception as e:
            logger.error(f"Failed to set AGC: {e}")
            raise

    def start_streaming(self, num_samples: int = 4096) -> None:
        """Start streaming samples from device."""
        if self._device is None:
            raise RuntimeError("Device not open")

        if self._is_streaming:
            logger.warning("Device already streaming")
            return

        try:
            self._is_streaming = True
            logger.info(f"RTL-SDR streaming started ({num_samples} samples/read)")
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            raise

    def stop_streaming(self) -> None:
        """Stop streaming samples."""
        if self._is_streaming:
            self._is_streaming = False
            logger.info("RTL-SDR streaming stopped")

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Read samples from device.

        Args:
            num_samples: Number of samples to read

        Returns:
            Complex64 numpy array of samples
        """
        if self._device is None:
            raise RuntimeError("Device not open")

        try:
            # Read samples and convert to complex64
            samples = self._device.read_samples(num_samples)
            return np.array(samples, dtype=np.complex64)
        except Exception as e:
            logger.error(f"Failed to read samples: {e}")
            raise

    def get_device_info(self) -> RTLSDRDeviceInfo:
        """Get device information."""
        try:
            import rtlsdr
            info = rtlsdr.get_device_info(self._device_index)
            return RTLSDRDeviceInfo(
                device_index=self._device_index,
                serial=info["serial"] if info else "",
            )
        except Exception as e:
            logger.error(f"Failed to get device info: {e}")
            return RTLSDRDeviceInfo(device_index=self._device_index)

    def get_current_settings(self) -> dict:
        """Get current device settings."""
        return {
            "sample_rate_hz": self._sample_rate_hz,
            "center_frequency_hz": self._center_frequency_hz,
            "gain_db": self._gain_db,
            "agc_enabled": self._agc_enabled,
            "is_streaming": self._is_streaming,
        }

    @staticmethod
    def list_devices() -> list[RTLSDRDeviceInfo]:
        """List available RTL-SDR devices."""
        try:
            import rtlsdr
            devices = []
            device_count = rtlsdr.get_device_info_count()
            for i in range(device_count):
                info = rtlsdr.get_device_info(i)
                if info:
                    devices.append(
                        RTLSDRDeviceInfo(
                            device_index=i,
                            serial=info.get("serial", ""),
                        )
                    )
            return devices
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []
