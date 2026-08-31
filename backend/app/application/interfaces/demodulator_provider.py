from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

from app.domain.entities.analyzer_settings import AnalyzerSettings


DemodulationStatus = Literal["idle", "starting", "running", "stopped", "error"]
DemodulationMode = Literal["off", "am", "fm", "wfm", "usb", "lsb", "cw"]


@dataclass(slots=True, frozen=True)
class DemodulationRequest:
    mode: DemodulationMode
    output_audio_enabled: bool = True
    record_audio: bool = False
    audio_output_device: Optional[str] = None
    output_directory: Optional[str] = None
    base_filename: Optional[str] = None
    session_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode == "off":
            raise ValueError("mode must not be 'off' for a demodulation request")

        if self.record_audio:
            if self.output_directory is None or not self.output_directory.strip():
                raise ValueError("output_directory is required when record_audio is enabled")
            if self.base_filename is not None and not self.base_filename.strip():
                raise ValueError("base_filename must not be empty when provided")


@dataclass(slots=True, frozen=True)
class DemodulationResult:
    mode: DemodulationMode
    status: DemodulationStatus
    audio_file_path: Optional[str] = None
    audio_sample_rate_hz: Optional[int] = None
    error_message: Optional[str] = None

    def is_success(self) -> bool:
        return self.status in {"starting", "running", "stopped"} and self.error_message is None


class DemodulatorProvider(ABC):
    @abstractmethod
    def start_demodulation(
        self,
        request: DemodulationRequest,
        settings: AnalyzerSettings,
    ) -> DemodulationResult:
        """
        Starts demodulation using the current analyzer settings.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_demodulation(self) -> DemodulationResult:
        """
        Stops the active demodulation session.
        """
        raise NotImplementedError

    @abstractmethod
    def get_demodulation_status(self) -> DemodulationStatus:
        """
        Returns the current demodulation status.
        """
        raise NotImplementedError

    @abstractmethod
    def get_last_demodulation_result(self) -> DemodulationResult | None:
        """
        Returns the last demodulation result, if any.
        """
        raise NotImplementedError