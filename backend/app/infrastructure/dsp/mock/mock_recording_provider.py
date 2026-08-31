from __future__ import annotations

from pathlib import Path

from app.application.interfaces.recording_provider import (
    RecordingProvider,
    RecordingRequest,
    RecordingResult,
)
from app.domain.entities.analyzer_settings import AnalyzerSettings


class MockRecordingProvider(RecordingProvider):
    def __init__(self) -> None:
        self._status = "idle"
        self._last_result: RecordingResult | None = None

    def start_recording(
        self,
        request: RecordingRequest,
        settings: AnalyzerSettings,
    ) -> RecordingResult:
        output_dir = Path(request.directory).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        iq_file = str(output_dir / f"{request.recording_name}.cfile") if request.record_iq else None
        audio_file = str(output_dir / f"{request.recording_name}.wav") if request.record_audio else None
        metadata_file = str(output_dir / f"{request.recording_name}.json")

        self._status = "recording"
        self._last_result = RecordingResult(
            recording_name=request.recording_name,
            status="recording",
            iq_file_path=iq_file,
            audio_file_path=audio_file,
            metadata_file_path=metadata_file,
            duration_seconds=request.duration_seconds,
            error_message=None,
        )
        return self._last_result

    def stop_recording(self) -> RecordingResult:
        if self._last_result is None:
            return RecordingResult(
                recording_name="",
                status="error",
                error_message="No active recording",
            )

        self._status = "stopped"
        self._last_result = RecordingResult(
            recording_name=self._last_result.recording_name,
            status="stopped",
            iq_file_path=self._last_result.iq_file_path,
            audio_file_path=self._last_result.audio_file_path,
            metadata_file_path=self._last_result.metadata_file_path,
            duration_seconds=self._last_result.duration_seconds,
            error_message=None,
        )
        return self._last_result

    def get_recording_status(self) -> str:
        return self._status

    def get_last_recording_result(self) -> RecordingResult | None:
        return self._last_result

    def list_recordings(self, directory: str) -> list[RecordingResult]:
        root = Path(directory).resolve()
        if not root.exists():
            return []

        results: list[RecordingResult] = []
        for metadata_file in sorted(root.glob("*.json")):
            stem = metadata_file.stem
            iq_file = root / f"{stem}.cfile"
            audio_file = root / f"{stem}.wav"

            results.append(
                RecordingResult(
                    recording_name=stem,
                    status="stopped",
                    iq_file_path=str(iq_file) if iq_file.exists() else None,
                    audio_file_path=str(audio_file) if audio_file.exists() else None,
                    metadata_file_path=str(metadata_file),
                    duration_seconds=None,
                    error_message=None,
                )
            )
        return results