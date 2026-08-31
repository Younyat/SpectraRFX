from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SetCenterBody(BaseModel):
    center_frequency_hz: float | None = None
    frequency_hz: float | None = None


class SetSpanBody(BaseModel):
    span_hz: float


class SetSampleRateBody(BaseModel):
    sample_rate_hz: float


class SetStartStopBody(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float


class SetRbwBody(BaseModel):
    rbw_hz: float


class SetVbwBody(BaseModel):
    vbw_hz: float


class SetReferenceLevelBody(BaseModel):
    reference_level_db: float | None = None
    level_dbm: float | None = None


class SetNoiseFloorBody(BaseModel):
    noise_floor_offset_db: float | None = None
    offset_db: float | None = None


class SetDetectorBody(BaseModel):
    detector_mode: str | None = None
    mode: str | None = None


class SetAveragingBody(BaseModel):
    enabled: bool | None = None
    averaging_factor: float | None = None
    count: float | None = None


class ScpiBody(BaseModel):
    command: str


def build_spectrum_router(controller) -> APIRouter:
    router = APIRouter(prefix="/spectrum", tags=["spectrum"])
    
    @router.get("/live")
    async def get_live_spectrum():
        return controller.get_spectrum(None)

    @router.get("/safety-limits")
    async def get_safety_limits():
        return controller.get_safety_limits()

    @router.post("/center-frequency")
    async def set_center_frequency(body: SetCenterBody):
        frequency_hz = body.center_frequency_hz if body.center_frequency_hz is not None else body.frequency_hz
        if frequency_hz is None:
            raise HTTPException(status_code=400, detail="center_frequency_hz or frequency_hz is required")
        try:
            return controller.set_center_frequency(frequency_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/span")
    async def set_span(body: SetSpanBody):
        try:
            return controller.set_span(body.span_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sample-rate")
    async def set_sample_rate(body: SetSampleRateBody):
        try:
            return controller.set_sample_rate(body.sample_rate_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/start-stop")
    async def set_start_stop(body: SetStartStopBody):
        try:
            return controller.set_start_stop(body.start_frequency_hz, body.stop_frequency_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/rbw")
    async def set_rbw(body: SetRbwBody):
        try:
            return controller.set_rbw(body.rbw_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/vbw")
    async def set_vbw(body: SetVbwBody):
        try:
            return controller.set_vbw(body.vbw_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/reference-level")
    async def set_reference_level(body: SetReferenceLevelBody):
        level = body.reference_level_db if body.reference_level_db is not None else body.level_dbm
        if level is None:
            raise HTTPException(status_code=400, detail="reference_level_db or level_dbm is required")
        try:
            return controller.set_reference_level(level)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/noise-floor-offset")
    async def set_noise_floor_offset(body: SetNoiseFloorBody):
        offset = body.noise_floor_offset_db if body.noise_floor_offset_db is not None else body.offset_db
        if offset is None:
            raise HTTPException(status_code=400, detail="noise_floor_offset_db or offset_db is required")
        try:
            return controller.set_noise_floor_offset(offset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/detector-mode")
    async def set_detector_mode(body: SetDetectorBody):
        mode = body.detector_mode if body.detector_mode is not None else body.mode
        if mode is None:
            raise HTTPException(status_code=400, detail="detector_mode or mode is required")
        try:
            return controller.set_detector_mode(mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/averaging")
    async def set_averaging(body: SetAveragingBody):
        factor = body.averaging_factor if body.averaging_factor is not None else body.count
        enabled = body.enabled if body.enabled is not None else bool(factor and factor > 1)
        try:
            return controller.set_averaging(enabled, factor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/scpi")
    async def execute_scpi(body: ScpiBody):
        try:
            return controller.execute_scpi(body.command)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    return router
