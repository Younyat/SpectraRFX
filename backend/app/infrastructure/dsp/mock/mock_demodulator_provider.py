from __future__ import annotations

from pathlib import Path

from app.application.interfaces.demodulator_provider import (
    DemodulationRequest,
    DemodulationResult,
    DemodulatorProvider,
)
from app.domain.entities.analyzer_settings import AnalyzerSettings


class MockDemodulatorProvider(DemodulatorProvider):
    def __init__(self) -> None:
        self._status = "idle"
        self._last_result: DemodulationResult | None = None

    def start_demodulation(
        self,
        request: DemodulationRequest,
        settings: AnalyzerSettings,
    ) -> DemodulationResult:
        audio_file_path = None
        if request.record_audio and request.output_directory:
            output_dir = Path(request.output_directory).resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            base_name = request.base_filename or "demodulated_audio"
            audio_file_path = str(output_dir / f"{base_name}.wav")

        self._status = "running"
        self._last_result = DemodulationResult(
            mode=request.mode,
            status="running",
            audio_file_path=audio_file_path,
            audio_sample_rate_hz=settings.demodulation.audio_sample_rate_hz,
            error_message=None,
        )
        return self._last_result

    def stop_demodulation(self) -> DemodulationResult:
        if self._last_result is None:
            return DemodulationResult(
                mode="am",
                status="error",
                error_message="No active demodulation",
            )

        self._status = "stopped"
        self._last_result = DemodulationResult(
            mode=self._last_result.mode,
            status="stopped",
            audio_file_path=self._last_result.audio_file_path,
            audio_sample_rate_hz=self._last_result.audio_sample_rate_hz,
            error_message=None,
        )
        return self._last_result

    def get_demodulation_status(self) -> str:
        return self._status

    def get_last_demodulation_result(self) -> DemodulationResult | None:
        return self._last_result