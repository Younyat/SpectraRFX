from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

class UHDDeviceAdapter:
    def __init__(self, device_args: str = ""):
        self.device_args = device_args
        self.usrp = None
        self.frequency_hz = 1_000_000_000
        self.gain_db = 20.0
        self.sample_rate_hz = 2_000_000
        self.is_open = False
    
    def open(self):
        try:
            import uhd
            self.usrp = uhd.usrp.MultiUSRP(self.device_args)
            self.is_open = True
            logger.info("UHD device opened")
        except ImportError:
            logger.error("UHD library not available")
            raise
        except Exception as e:
            logger.error(f"Failed to open UHD device: {e}")
            raise
    
    def close(self):
        if self.usrp is not None:
            self.usrp = None
            self.is_open = False
            logger.info("UHD device closed")
    
    def set_center_frequency_hz(self, frequency_hz: float):
        if self.usrp is None:
            return
        try:
            self.usrp.set_rx_freq(frequency_hz)
            self.frequency_hz = frequency_hz
        except Exception as e:
            logger.error(f"Failed to set frequency: {e}")
    
    def set_gain_db(self, gain_db: float):
        if self.usrp is None:
            return
        try:
            self.usrp.set_rx_gain(gain_db)
            self.gain_db = gain_db
        except Exception as e:
            logger.error(f"Failed to set gain: {e}")
    
    def set_sample_rate_hz(self, sample_rate_hz: float):
        if self.usrp is None:
            return
        try:
            self.usrp.set_rx_rate(sample_rate_hz)
            self.sample_rate_hz = sample_rate_hz
        except Exception as e:
            logger.error(f"Failed to set sample rate: {e}")
    
    def read_samples(self, num_samples: int) -> np.ndarray:
        if self.usrp is None:
            return np.array([])
        try:
            samples = self.usrp.recv_num_samps(num_samples, uhd.types.RXStreamer)
            return samples.astype(np.complex64)
        except Exception as e:
            logger.error(f"Failed to read samples: {e}")
            return np.array([])

    def set_sample_rate(self, sample_rate_hz: float) -> DeviceState:
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if self._usrp is None:
            raise RuntimeError("UHD device is not connected")

        self._usrp.set_rx_rate(float(sample_rate_hz), 0)
        self._state.telemetry.current_sample_rate_hz = float(sample_rate_hz)
        return self._state

    def set_gain(self, gain_db: float) -> DeviceState:
        if self._usrp is None:
            raise RuntimeError("UHD device is not connected")

        try:
            self._usrp.set_gain(float(gain_db), 0)
        except TypeError:
            self._usrp.set_gain(float(gain_db))
        self._state.telemetry.current_gain_db = float(gain_db)
        self._state.telemetry.agc_enabled = False
        return self._state

    def set_agc_enabled(self, enabled: bool) -> DeviceState:
        if self._usrp is None:
            raise RuntimeError("UHD device is not connected")

        agc_enabled = bool(enabled)
        try:
            self._usrp.set_rx_agc(agc_enabled, 0)
        except Exception:
            # no todos los dispositivos o bindings lo soportan
            if agc_enabled:
                self._state.telemetry.last_error_message = "AGC is not supported by this device or UHD build"
        self._state.telemetry.agc_enabled = agc_enabled
        return self._state

    def set_antenna(self, antenna: str) -> DeviceState:
        if not antenna.strip():
            raise ValueError("antenna must not be empty")
        if self._usrp is None:
            raise RuntimeError("UHD device is not connected")

        self._usrp.set_rx_antenna(antenna, 0)
        self._state.telemetry.current_antenna = antenna
        return self._state

    def _resolve_antenna(self, settings: AnalyzerSettings) -> str:
        return self._state.telemetry.current_antenna or "RX2"

    def _read_capabilities(self) -> DeviceCapabilities:
        if self._usrp is None:
            raise RuntimeError("UHD device is not connected")

        antennas: list[str] = []
        try:
            antennas = list(self._usrp.get_rx_antennas(0))
        except Exception:
            antennas = []

        min_freq = None
        max_freq = None
        min_rate = None
        max_rate = None
        min_gain = None
        max_gain = None

        try:
            freq_range = self._usrp.get_rx_freq_range(0)
            min_freq = float(freq_range.start())
            max_freq = float(freq_range.stop())
        except Exception:
            pass

        try:
            rate_range = self._usrp.get_rx_rates(0)
            min_rate = float(rate_range.start())
            max_rate = float(rate_range.stop())
        except Exception:
            pass

        try:
            gain_range = self._usrp.get_gain_range(0)
            min_gain = float(gain_range.start())
            max_gain = float(gain_range.stop())
        except Exception:
            pass

        return DeviceCapabilities(
            driver=self._driver_name,
            device_name="UHD SDR Device",
            serial_number=None,
            supports_agc=True,
            supports_iq_recording=True,
            supports_audio_demodulation=True,
            min_frequency_hz=min_freq,
            max_frequency_hz=max_freq,
            min_sample_rate_hz=min_rate,
            max_sample_rate_hz=max_rate,
            min_gain_db=min_gain,
            max_gain_db=max_gain,
            antennas=antennas,
        )