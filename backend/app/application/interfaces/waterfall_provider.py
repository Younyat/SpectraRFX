from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.analyzer_settings import AnalyzerSettings
from app.domain.entities.waterfall_frame import WaterfallFrame


class WaterfallProvider(ABC):
    @abstractmethod
    def get_live_waterfall_frame(self, settings: AnalyzerSettings) -> WaterfallFrame:
        """
        Produces a single waterfall frame using the current analyzer settings.
        """
        raise NotImplementedError

    @abstractmethod
    def get_last_waterfall_frame(self) -> WaterfallFrame | None:
        """
        Returns the most recent available waterfall frame, if any.
        """
        raise NotImplementedError

    @abstractmethod
    def clear_history(self) -> None:
        """
        Clears the internal waterfall history buffer.
        """
        raise NotImplementedError

    @abstractmethod
    def get_history_size(self) -> int:
        """
        Returns the current number of frames stored in the waterfall history buffer.
        """
        raise NotImplementedError