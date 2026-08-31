from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.analyzer_settings import AnalyzerSettings
from app.domain.entities.spectrum_frame import SpectrumFrame


class SpectrumProvider(ABC):
    @abstractmethod
    def get_live_spectrum(self, settings: AnalyzerSettings) -> SpectrumFrame:
        """
        Produces a single live spectrum frame using the current analyzer settings.
        """
        raise NotImplementedError

    @abstractmethod
    def get_last_spectrum(self) -> SpectrumFrame | None:
        """
        Returns the most recent available spectrum frame, if any.
        """
        raise NotImplementedError

    @abstractmethod
    def clear_trace_state(self) -> None:
        """
        Clears internal trace state such as averaging, max hold, and min hold.
        """
        raise NotImplementedError

    @abstractmethod
    def reset_peak_tracking(self) -> None:
        """
        Resets any internal peak tracking state used by the spectrum engine.
        """
        raise NotImplementedError