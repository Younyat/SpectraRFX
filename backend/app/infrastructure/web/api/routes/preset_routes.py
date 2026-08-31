from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel


class SavePresetBody(BaseModel):
    name: str
    settings: dict | None = None
    config: dict | None = None

def build_preset_router(controller) -> APIRouter:
    router = APIRouter(prefix="/presets", tags=["presets"])
    
    @router.get("/")
    async def list_presets():
        return controller.list_presets()
    
    @router.post("/")
    async def save_preset(body: SavePresetBody):
        return controller.save_preset(body.name, body.config or body.settings or {})
    
    @router.get("/{preset_id}")
    async def load_preset(preset_id: str):
        return controller.load_preset(preset_id)
    
    return router
