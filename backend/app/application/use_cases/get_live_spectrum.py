from __future__ import annotations

from app.application.dto.spectrum_dto import SpectrumDTO
from app.application.interfaces.spectrum_provider import SpectrumProvider
from app.domain.entities.analyzer_settings import AnalyzerSettings


class GetLiveSpectrumUseCase:
    def __init__(self, spectrum_provider: SpectrumProvider) -> None:
        self._spectrum_provider = spectrum_provider

    def execute(self, settings: AnalyzerSettings) -> SpectrumDTO:
        frame = self._spectrum_provider.get_live_spectrum(settings)
        return SpectrumDTO.from_entity(frame)