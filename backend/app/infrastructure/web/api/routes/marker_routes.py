from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel


class CreateMarkerBody(BaseModel):
    label: str
    frequency: float | None = None
    frequency_hz: float | None = None

def build_marker_router(controller) -> APIRouter:
    router = APIRouter(prefix="/markers", tags=["markers"])
    
    @router.get("/")
    async def list_markers():
        return controller.list_markers()
    
    @router.post("/")
    async def create_marker(body: CreateMarkerBody):
        frequency_hz = body.frequency_hz if body.frequency_hz is not None else body.frequency
        if frequency_hz is None:
            raise ValueError("frequency_hz or frequency is required")
        return controller.create_marker(body.label, frequency_hz)
    
    @router.delete("/{marker_id}")
    async def delete_marker(marker_id: str):
        return controller.delete_marker(marker_id)
    
    return router
