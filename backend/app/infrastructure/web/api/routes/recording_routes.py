from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel


class StartRecordingBody(BaseModel):
    type: str = "iq"
    duration_seconds: float = 10.0

def build_recording_router(controller) -> APIRouter:
    router = APIRouter(prefix="/recordings", tags=["recordings"])
    
    @router.get("/")
    async def list_recordings():
        return controller.list_recordings()
    
    @router.post("/start")
    async def start_recording(body: StartRecordingBody):
        return controller.start_recording(body.duration_seconds, body.type)
    
    @router.post("/stop")
    async def stop_recording():
        return controller.stop_recording()
    
    return router
