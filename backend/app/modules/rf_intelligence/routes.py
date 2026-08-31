from __future__ import annotations

from fastapi import APIRouter

from app.modules.rf_intelligence.knowledge_base import resolve_band_profile
from app.modules.rf_intelligence.schemas import RFAnalyzeRequest, RFIntelligenceSettings, SpectrumFrameInput
from app.modules.rf_intelligence.service import RFIntelligenceService


def build_rf_intelligence_router(service: RFIntelligenceService, spectrum_controller) -> APIRouter:
    router = APIRouter(prefix="/rf-intelligence", tags=["rf-intelligence"])

    @router.post("/analyze")
    async def analyze_frame(request: RFAnalyzeRequest):
        return service.analyze_frame(request.frame, request.settings)

    @router.post("/band-profile/resolve")
    async def resolve_capture_band_profile(request: dict):
        try:
            resolved = resolve_band_profile(
                start_frequency_hz=request.get("start_frequency_hz"),
                stop_frequency_hz=request.get("stop_frequency_hz"),
                center_frequency_hz=request.get("center_frequency_hz"),
                bandwidth_hz=request.get("bandwidth_hz") or request.get("occupied_bandwidth_hz"),
            )
            return {
                "status": "ok" if resolved.get("matched") else "needs_review",
                "module": "rf_intelligence.band_profile_resolver",
                "available": True,
                "message": resolved.get("message"),
                "data": resolved,
                "errors": [],
            }
        except Exception as exc:
            return {
                "status": "error",
                "module": "rf_intelligence.band_profile_resolver",
                "available": False,
                "message": "Band profile resolution failed.",
                "data": {},
                "errors": [str(exc)],
            }

    @router.get("/live")
    async def analyze_live_spectrum(
        threshold_offset_db: float = 10.0,
        min_snr_db: float = 6.0,
        min_bins: int = 2,
        merge_gap_bins: int = 2,
    ):
        raw_frame = spectrum_controller.get_spectrum(None)
        frame = SpectrumFrameInput(
            timestamp_utc=raw_frame.get("timestamp_utc"),
            center_frequency_hz=raw_frame.get("center_frequency_hz", 0),
            span_hz=raw_frame.get("span_hz", 0),
            start_frequency_hz=raw_frame.get("start_frequency_hz"),
            stop_frequency_hz=raw_frame.get("stop_frequency_hz"),
            sample_rate_hz=raw_frame.get("sample_rate_hz"),
            frequencies_hz=raw_frame.get("frequencies_hz") or [],
            levels_db=raw_frame.get("levels_db") or [],
        )
        settings = RFIntelligenceSettings(
            threshold_offset_db=threshold_offset_db,
            min_snr_db=min_snr_db,
            min_bins=min_bins,
            merge_gap_bins=merge_gap_bins,
        )
        return service.analyze_frame(frame, settings)

    return router
