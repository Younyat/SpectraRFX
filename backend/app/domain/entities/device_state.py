from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


DeviceConnectionStatus = Literal["disconnected", "connecting", "connected", "error"]
DeviceStreamStatus = Literal["stopped", "starting", "running", "stopping", "error"]


@dataclass(slots=True)
class DeviceCapabilities:
    driver: str
    device_name: str
    serial_number: Optional[str] = None
    supports_agc: bool = False
    supports_iq_recording: bool = True
    supports_audio_demodulation: bool = True
    min_frequency_hz: Optional[float] = None
    max_frequency_hz: Optional[float] = None
    min_sample_rate_hz: Optional[float] = None
    max_sample_rate_hz: Optional[float] = None
    min_gain_db: Optional[float] = None
    max_gain_db: Optional[float] = None
    antennas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "driver": self.driver,
            "device_name": self.device_name,
            "serial_number": self.serial_number,
            "supports_agc": self.supports_agc,
            "supports_iq_recording": self.supports_iq_recording,
            "supports_audio_demodulation": self.supports_audio_demodulation,
            "min_frequency_hz": self.min_frequency_hz,
            "max_frequency_hz": self.max_frequency_hz,
            "min_sample_rate_hz": self.min_sample_rate_hz,
            "max_sample_rate_hz": self.max_sample_rate_hz,
            "min_gain_db": self.min_gain_db,
            "max_gain_db": self.max_gain_db,
            "antennas": self.antennas,
        }


@dataclass(slots=True)
class DeviceTelemetry:
    current_frequency_hz: Optional[float] = None
    current_sample_rate_hz: Optional[float] = None
    current_gain_db: Optional[float] = None
    current_antenna: Optional[str] = None
    agc_enabled: bool = False
    dropped_samples: int = 0
    overflow_count: int = 0
    last_error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "current_frequency_hz": self.current_frequency_hz,
            "current_sample_rate_hz": self.current_sample_rate_hz,
            "current_gain_db": self.current_gain_db,
            "current_antenna": self.current_antenna,
            "agc_enabled": self.agc_enabled,
            "dropped_samples": self.dropped_samples,
            "overflow_count": self.overflow_count,
            "last_error_message": self.last_error_message,
        }


@dataclass(slots=True)
class DeviceState:
    device_id: str
    driver: str
    connection_status: DeviceConnectionStatus = "disconnected"
    stream_status: DeviceStreamStatus = "stopped"
    connected: bool = False
    streaming: bool = False
    capabilities: Optional[DeviceCapabilities] = None
    telemetry: DeviceTelemetry = field(default_factory=DeviceTelemetry)

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise ValueError("device_id must not be empty")
        if not self.driver.strip():
            raise ValueError("driver must not be empty")

    def mark_connecting(self) -> None:
        self.connection_status = "connecting"
        self.connected = False

    def mark_connected(self) -> None:
        self.connection_status = "connected"
        self.connected = True

    def mark_disconnected(self) -> None:
        self.connection_status = "disconnected"
        self.stream_status = "stopped"
        self.connected = False
        self.streaming = False

    def mark_connection_error(self, message: str) -> None:
        self.connection_status = "error"
        self.connected = False
        self.telemetry.last_error_message = message

    def mark_stream_starting(self) -> None:
        self.stream_status = "starting"
        self.streaming = False

    def mark_stream_running(self) -> None:
        self.stream_status = "running"
        self.streaming = True

    def mark_stream_stopping(self) -> None:
        self.stream_status = "stopping"

    def mark_stream_stopped(self) -> None:
        self.stream_status = "stopped"
        self.streaming = False

    def mark_stream_error(self, message: str) -> None:
        self.stream_status = "error"
        self.streaming = False
        self.telemetry.last_error_message = message

    def update_tuning(
        self,
        frequency_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        agc_enabled: bool,
    ) -> None:
        if frequency_hz <= 0:
            raise ValueError("frequency_hz must be > 0")
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")

        self.telemetry.current_frequency_hz = frequency_hz
        self.telemetry.current_sample_rate_hz = sample_rate_hz
        self.telemetry.current_gain_db = gain_db
        self.telemetry.current_antenna = antenna
        self.telemetry.agc_enabled = agc_enabled

    def register_overflow(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("count must be >= 0")
        self.telemetry.overflow_count += count

    def register_dropped_samples(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must be >= 0")
        self.telemetry.dropped_samples += count

    def set_capabilities(self, capabilities: DeviceCapabilities) -> None:
        self.capabilities = capabilities

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "driver": self.driver,
            "connection_status": self.connection_status,
            "stream_status": self.stream_status,
            "connected": self.connected,
            "streaming": self.streaming,
            "capabilities": None if self.capabilities is None else self.capabilities.to_dict(),
            "telemetry": self.telemetry.to_dict(),
        }