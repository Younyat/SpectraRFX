from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.analyzer_settings import AnalyzerSettings
from app.domain.entities.device_state import DeviceState


class DeviceControlProvider(ABC):
    @abstractmethod
    def connect(self) -> DeviceState:
        """
        Connects to the underlying SDR device and returns the updated device state.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> DeviceState:
        """
        Disconnects from the underlying SDR device and returns the updated device state.
        """
        raise NotImplementedError

    @abstractmethod
    def start_stream(self, settings: AnalyzerSettings) -> DeviceState:
        """
        Starts the live device stream using the provided analyzer settings.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_stream(self) -> DeviceState:
        """
        Stops the live device stream.
        """
        raise NotImplementedError

    @abstractmethod
    def get_device_state(self) -> DeviceState:
        """
        Returns the current device state snapshot.
        """
        raise NotImplementedError

    @abstractmethod
    def apply_settings(self, settings: AnalyzerSettings) -> DeviceState:
        """
        Applies analyzer settings to the hardware and returns the updated state.
        """
        raise NotImplementedError

    @abstractmethod
    def set_center_frequency(self, frequency_hz: float) -> DeviceState:
        """
        Tunes the device to the requested center frequency.
        """
        raise NotImplementedError

    @abstractmethod
    def set_sample_rate(self, sample_rate_hz: float) -> DeviceState:
        """
        Updates the device sample rate.
        """
        raise NotImplementedError

    @abstractmethod
    def set_gain(self, gain_db: float) -> DeviceState:
        """
        Updates manual gain.
        """
        raise NotImplementedError

    @abstractmethod
    def set_agc_enabled(self, enabled: bool) -> DeviceState:
        """
        Enables or disables AGC if supported by the device.
        """
        raise NotImplementedError

    @abstractmethod
    def set_antenna(self, antenna: str) -> DeviceState:
        """
        Selects the receive antenna.
        """
        raise NotImplementedError