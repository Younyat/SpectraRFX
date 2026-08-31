from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.modules.rf_signal_understanding.application.signal_understanding_service import RFSignalUnderstandingService
from app.modules.rf_signal_understanding.domain.schemas import (
    AnalyzeCaptureRequest,
    CaptureForTrainingRequest,
    CompareModelsRequest,
    CompareWithRFIntelligenceRequest,
    ExportLabelledRegionsRequest,
    IncrementalTrainingRequest,
    PseudoLabelRequest,
    RegisterCaptureRequest,
    RegionReviewRequest,
    TrainingRequest,
    ValidationRequest,
)


def build_rf_signal_understanding_router(service: RFSignalUnderstandingService, spectrum_controller=None, modulated_signal_controller=None) -> APIRouter:
    router = APIRouter(prefix="/rf-signal-understanding", tags=["rf-signal-understanding"])

    @router.get("/live")
    async def live(
        start_frequency_hz: float | None = Query(default=None),
        stop_frequency_hz: float | None = Query(default=None),
        decision_mode: str = Query(default="hybrid"),
    ):
        if spectrum_controller is None:
            raise HTTPException(status_code=503, detail="Live spectrum controller is not available")
        raw_frame = spectrum_controller.get_spectrum(None)
        raw_frame = _crop_frame_to_frequency_window(raw_frame, start_frequency_hz, stop_frequency_hz)
        return service.analyze_live_frame(raw_frame, decision_mode=decision_mode)

    @router.post("/analyze-frame")
    async def analyze_frame(request: dict[str, Any], decision_mode: str = Query(default="hybrid")):
        frame = request.get("frame", request)
        if not isinstance(frame, dict):
            raise HTTPException(status_code=400, detail="Frame payload must be an object")
        return service.analyze_live_frame(frame, decision_mode=decision_mode)

    @router.post("/compare-live-with-rf-intelligence")
    async def compare_live_with_rf_intelligence(
        start_frequency_hz: float | None = Query(default=None),
        stop_frequency_hz: float | None = Query(default=None),
        decision_mode: str = Query(default="hybrid"),
    ):
        if spectrum_controller is None:
            raise HTTPException(status_code=503, detail="Live spectrum controller is not available")
        raw_frame = spectrum_controller.get_spectrum(None)
        raw_frame = _crop_frame_to_frequency_window(raw_frame, start_frequency_hz, stop_frequency_hz)
        return service.compare_live_with_rf_intelligence(raw_frame, decision_mode=decision_mode)

    @router.post("/analyze")
    async def analyze(request: AnalyzeCaptureRequest):
        try:
            return service.analyze_capture(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/capture-for-training")
    async def capture_for_training(request: CaptureForTrainingRequest):
        if modulated_signal_controller is None:
            raise HTTPException(status_code=503, detail="Capture Lab controller is not available")
        try:
            return service.capture_for_training(request, modulated_signal_controller)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/capture-registry/register")
    async def register_capture(request: RegisterCaptureRequest):
        try:
            return service.register_capture(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/capture-registry")
    async def capture_registry():
        return service.list_registered_captures()

    @router.post("/capture-registry/{capture_id}/analyze")
    async def analyze_registry_capture(capture_id: str):
        try:
            return service.analyze_registered_capture(capture_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/capture-registry/{capture_id}")
    async def delete_registry_capture(capture_id: str):
        try:
            service.delete_registered_capture(capture_id)
            return {"message": f"Capture {capture_id} deleted successfully"}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/training-queue")
    async def training_queue():
        return service.training_queue_summary()

    @router.get("/results/{analysis_id}")
    async def get_result(analysis_id: str):
        try:
            return service.get_result(analysis_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/compare-with-rf-intelligence")
    async def compare_with_rf_intelligence(request: CompareWithRFIntelligenceRequest):
        try:
            return service.compare_with_rf_intelligence(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/train-region-detector")
    async def train_region_detector(request: TrainingRequest):
        try:
            return service.train_region_detector(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/train-classifier")
    async def train_classifier(request: TrainingRequest):
        try:
            return service.train_classifier(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/validate")
    async def validate(request: ValidationRequest):
        try:
            return service.validate(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/regions/review")
    async def review_region(request: RegionReviewRequest):
        try:
            return service.review_region(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/regions/pseudo-label")
    async def pseudo_label_region(request: PseudoLabelRequest):
        try:
            return service.create_pseudo_label(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/datasets/export-labelled-regions")
    async def export_labelled_regions(request: ExportLabelledRegionsRequest):
        try:
            return service.export_labelled_regions(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/train-classifier-incremental")
    async def train_classifier_incremental(request: IncrementalTrainingRequest):
        try:
            return service.train_classifier_incremental(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/compare-models")
    async def compare_models(request: CompareModelsRequest):
        try:
            return service.compare_models(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/models")
    async def models():
        return service.models()

    @router.get("/references")
    async def references():
        return service.references()

    return router


def _crop_frame_to_frequency_window(raw_frame: dict[str, Any], start_frequency_hz: float | None, stop_frequency_hz: float | None) -> dict[str, Any]:
    if start_frequency_hz is None or stop_frequency_hz is None:
        return raw_frame
    start = min(float(start_frequency_hz), float(stop_frequency_hz))
    stop = max(float(start_frequency_hz), float(stop_frequency_hz))
    if not (start > 0 and stop > start):
        raise HTTPException(status_code=400, detail="Invalid marker frequency window")

    frequencies = list(raw_frame.get("frequencies_hz") or [])
    levels = list(raw_frame.get("levels_db") or [])
    if not frequencies or len(frequencies) != len(levels):
        return {
            **raw_frame,
            "center_frequency_hz": start + (stop - start) / 2.0,
            "span_hz": stop - start,
            "sample_rate_hz": stop - start,
            "frequencies_hz": [],
            "levels_db": [],
            "data": [],
            "points": 0,
            "source": f"{raw_frame.get('source', 'real_sdr')}_marker_window",
        }

    cropped = [(freq, level) for freq, level in zip(frequencies, levels) if start <= float(freq) <= stop]
    cropped_frequencies = [float(freq) for freq, _ in cropped]
    cropped_levels = [float(level) for _, level in cropped]
    return {
        **raw_frame,
        "center_frequency_hz": start + (stop - start) / 2.0,
        "span_hz": stop - start,
        "sample_rate_hz": stop - start,
        "frequencies_hz": cropped_frequencies,
        "levels_db": cropped_levels,
        "data": [cropped_levels] if cropped_levels else [],
        "points": len(cropped_levels),
        "source": f"{raw_frame.get('source', 'real_sdr')}_marker_window",
        "marker_window": {
            "start_frequency_hz": start,
            "stop_frequency_hz": stop,
            "center_frequency_hz": start + (stop - start) / 2.0,
            "bandwidth_hz": stop - start,
        },
    }
