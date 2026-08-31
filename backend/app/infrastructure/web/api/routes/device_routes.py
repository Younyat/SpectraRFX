from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SetFrequencyBody(BaseModel):
    frequency: float | None = None
    frequency_hz: float | None = None


class SetGainBody(BaseModel):
    gain: float | None = None
    gain_db: float | None = None


class SetSampleRateBody(BaseModel):
    sample_rate: float | None = None
    sample_rate_hz: float | None = None

def build_device_router(controller) -> APIRouter:
    router = APIRouter(prefix="/device", tags=["device"])
    
    @router.get("/status")
    async def get_status():
        return controller.get_device_status()

    @router.post("/connect")
    async def connect_device():
        return controller.connect_device()

    @router.post("/disconnect")
    async def disconnect_device():
        return controller.disconnect_device()

    @router.post("/receiver/open")
    async def open_wfm_receiver():
        return controller.open_wfm_receiver()

    @router.post("/receiver/close")
    async def close_wfm_receiver():
        return controller.close_wfm_receiver()
    
    @router.post("/stream/start")
    async def start_stream():
        return controller.start_streaming()
    
    @router.post("/stream/stop")
    async def stop_stream():
        return controller.stop_streaming()
    
    @router.post("/frequency")
    async def set_frequency(body: SetFrequencyBody):
        frequency_hz = body.frequency_hz if body.frequency_hz is not None else body.frequency
        if frequency_hz is None:
            raise HTTPException(status_code=400, detail="frequency_hz or frequency is required")
        try:
            return controller.set_frequency(frequency_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    @router.post("/gain")
    async def set_gain(body: SetGainBody):
        gain_db = body.gain_db if body.gain_db is not None else body.gain
        if gain_db is None:
            raise HTTPException(status_code=400, detail="gain_db or gain is required")
        try:
            return controller.set_gain(gain_db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sample-rate")
    async def set_sample_rate(body: SetSampleRateBody):
        sample_rate_hz = body.sample_rate_hz if body.sample_rate_hz is not None else body.sample_rate
        if sample_rate_hz is None:
            raise HTTPException(status_code=400, detail="sample_rate_hz or sample_rate is required")
        try:
            return controller.set_sample_rate(sample_rate_hz)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    return router
