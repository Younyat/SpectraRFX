from __future__ import annotations
from app.application.dto.waterfall_dto import WaterfallDTO
from app.application.interfaces.waterfall_provider import WaterfallProvider

class GetLiveWaterfallUseCase:
    def __init__(self, waterfall_provider: WaterfallProvider):
        self._waterfall_provider = waterfall_provider
    
    def execute(self, settings) -> WaterfallDTO:
        frame = self._waterfall_provider.get_live_waterfall_frame(settings)
        if frame is None:
            return WaterfallDTO(
                timestamp_utc="",
                center_frequency_hz=0,
                span_hz=0,
            )
        return WaterfallDTO.from_entity(frame) if hasattr(WaterfallDTO, 'from_entity') else WaterfallDTO(
            timestamp_utc=getattr(frame, 'timestamp_utc', ''),
            center_frequency_hz=getattr(frame, 'center_frequency_hz', 0),
            span_hz=getattr(frame, 'span_hz', 0),
        )