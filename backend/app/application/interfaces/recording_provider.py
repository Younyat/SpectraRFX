from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

from app.domain.entities.analyzer_settings import AnalyzerSettings


RecordingStatus = Literal["idle", "recording", "stopped", "error"]


@dataclass(slots=True, frozen=True)
class RecordingRequest:
    recording_name: str
    directory: str
    duration_seconds: float
    record_iq: bool = True
    record_audio: bool = False
    session_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.recording_name.strip():
            raise ValueError("recording_name must not be empty")
        if not self.directory.strip():
            raise ValueError("directory must not be empty")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be > 0")
        if not self.record_iq and not self.record_audio:
            raise ValueError("At least one recording output must be enabled")


@dataclass(slots=True, frozen=True)
class RecordingResult:
    recording_name: str
    status: RecordingStatus
    iq_file_path: Optional[str] = None
    audio_file_path: Optional[str] = None
    metadata_file_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None

    def is_success(self) -> bool:
        return self.status in {"recording", "stopped"} and self.error_message is None


class RecordingProvider(ABC):
    @abstractmethod
    def start_recording(
        self,
        request: RecordingRequest,
        settings: AnalyzerSettings,
    ) -> RecordingResult:
        """
        Starts an RF and or audio recording according to the request and analyzer settings.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_recording(self) -> RecordingResult:
        """
        Stops the current recording if one is active.
        """
        raise NotImplementedError

    @abstractmethod
    def get_recording_status(self) -> RecordingStatus:
        """
        Returns the current recording status.
        """
        raise NotImplementedError

    @abstractmethod
    def get_last_recording_result(self) -> RecordingResult | None:
        """
        Returns the last known recording result, if any.
        """
        raise NotImplementedError

    @abstractmethod
    def list_recordings(self, directory: str) -> list[RecordingResult]:
        """
        Lists recordings available in the given directory.
        """
        raise NotImplementedError