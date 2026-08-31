from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


class MarkerBandIqCaptureBody(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float
    duration_seconds: float = 5.0
    label: str = ""
    modulation_hint: str = "unknown"
    notes: str = ""
    dataset_split: str = "train"
    session_id: str = ""
    transmitter_id: str = ""
    transmitter_class: str = ""
    operator: str = ""
    environment: str = ""
    file_format: str = "cfile"
    live_preview_snr_db: float | None = None
    live_preview_noise_floor_db: float | None = None
    live_preview_peak_level_db: float | None = None
    live_preview_peak_frequency_hz: float | None = None
    # Capture mode: "immediate" uses the GNU Radio flowgraph script;
    # "triggered_burst" routes to triggered_burst_capture.py (UHD direct + circular buffer).
    capture_mode: str = "immediate"
    # -- Triggered capture params --
    trigger_strategy: str = "adaptive_energy_trigger"
    trigger_threshold_db: float = 6.0
    pre_trigger_ms: float = 50.0
    post_trigger_ms: float = 100.0
    min_event_duration_ms: float = 10.0
    max_event_duration_ms: float = 2000.0
    cooldown_ms: float = 500.0
    trigger_max_wait_s: float = 10.0
    capture_repetitions: int = 1
    min_valid_events: int = 1
    smart_persistence_ms: float = 10.0
    auto_qc_enabled: bool = True
    target_task: str = "device_fingerprinting"
    signal_type: str = ""


def build_modulated_signal_router(controller) -> APIRouter:
    router = APIRouter(prefix="/modulated-signals", tags=["modulated-signals"])

    @router.post("/captures")
    async def capture_marker_band_iq(body: MarkerBandIqCaptureBody):
        try:
            return controller.capture_marker_band(
                start_frequency_hz=body.start_frequency_hz,
                stop_frequency_hz=body.stop_frequency_hz,
                duration_seconds=body.duration_seconds,
                label=body.label,
                modulation_hint=body.modulation_hint,
                notes=body.notes,
                dataset_split=body.dataset_split,
                session_id=body.session_id,
                transmitter_id=body.transmitter_id,
                transmitter_class=body.transmitter_class,
                operator=body.operator,
                environment=body.environment,
                file_format=body.file_format,
                live_preview_snr_db=body.live_preview_snr_db,
                live_preview_noise_floor_db=body.live_preview_noise_floor_db,
                live_preview_peak_level_db=body.live_preview_peak_level_db,
                live_preview_peak_frequency_hz=body.live_preview_peak_frequency_hz,
                capture_mode=body.capture_mode,
                trigger_strategy=body.trigger_strategy,
                trigger_threshold_db=body.trigger_threshold_db,
                pre_trigger_ms=body.pre_trigger_ms,
                post_trigger_ms=body.post_trigger_ms,
                min_event_duration_ms=body.min_event_duration_ms,
                max_event_duration_ms=body.max_event_duration_ms,
                cooldown_ms=body.cooldown_ms,
                trigger_max_wait_s=body.trigger_max_wait_s,
                capture_repetitions=body.capture_repetitions,
                min_valid_events=body.min_valid_events,
                smart_persistence_ms=body.smart_persistence_ms,
                auto_qc_enabled=body.auto_qc_enabled,
                target_task=body.target_task,
                signal_type=body.signal_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/captures")
    async def list_captures():
        return {"captures": controller.list_captures()}

    @router.get("/captures/{capture_id}")
    async def get_capture(capture_id: str):
        try:
            return controller.get_capture(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/captures/{capture_id}")
    async def delete_capture(capture_id: str):
        try:
            return controller.delete_capture(capture_id)
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if "not found" in message.lower() else 400
            raise HTTPException(status_code=status_code, detail=message) from exc

    @router.get("/captures/{capture_id}/iq")
    async def download_iq(capture_id: str):
        try:
            path = controller.get_iq_file(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @router.get("/captures/{capture_id}/metadata")
    async def download_metadata(capture_id: str):
        try:
            path = controller.get_metadata_file(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/json", filename=path.name)

    return router
