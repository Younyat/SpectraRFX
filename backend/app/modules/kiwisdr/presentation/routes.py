from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.modules.kiwisdr.domain.entities import KiwiSessionRequest
from app.modules.kiwisdr.presentation.controller import KiwiSessionController, ReceiverController


class KiwiSessionBody(BaseModel):
    receiver_id: str
    frequency_khz: float = 7100.0
    mode: str = "iq"
    compression: bool = True
    agc: bool = True


def build_receiver_router(controller: ReceiverController) -> APIRouter:
    router = APIRouter(prefix="/receivers", tags=["kiwisdr-receivers"])

    @router.get("")
    def list_receivers(
        q: str | None = Query(default=None),
        country: str | None = Query(default=None),
        online: bool | None = Query(default=None),
    ) -> dict:
        return controller.list_receivers(query=q, country=country, online=online)

    @router.get("/map")
    def receiver_map(
        q: str | None = Query(default=None),
        country: str | None = Query(default=None),
        online: bool | None = Query(default=None),
    ) -> dict:
        return controller.receiver_map(query=q, country=country, online=online)

    @router.post("/refresh")
    def refresh_receivers() -> dict:
        return controller.refresh(force=True)

    @router.get("/{receiver_id}")
    def get_receiver(receiver_id: str) -> dict:
        try:
            return controller.get_receiver(receiver_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{receiver_id}/health")
    def get_receiver_health(receiver_id: str) -> dict:
        try:
            return controller.health(receiver_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def build_kiwi_session_router(controller: KiwiSessionController) -> APIRouter:
    router = APIRouter(prefix="/kiwi/sessions", tags=["kiwisdr-sessions"])

    @router.post("")
    def create_session(body: KiwiSessionBody) -> dict:
        try:
            return controller.create_session(
                KiwiSessionRequest(
                    receiver_id=body.receiver_id,
                    frequency_khz=body.frequency_khz,
                    mode=body.mode,
                    compression=body.compression,
                    agc=body.agc,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
