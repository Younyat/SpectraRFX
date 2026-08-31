from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.infrastructure.web.controllers.spectrum_controller import SpectrumController


def build_waterfall_router(controller: SpectrumController) -> APIRouter:
    router = APIRouter(prefix="/waterfall", tags=["waterfall"])

    @router.get("/live")
    def get_live_waterfall() -> dict:
        try:
            return controller.get_live_waterfall()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router