from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class LiveDemodStartBody(BaseModel):
    center_hz: float
    mode: str
    sample_rate_hz: float = 2_000_000.0
    gain_db: float = 30.0
    chunk_duration: float = 0.5
    bpf_low_hz: float | None = None
    bpf_high_hz: float | None = None


class LiveDemodUpdateBody(BaseModel):
    gain_db: float | None = None
    center_hz: float | None = None
    bpf_low_hz: float | None = None
    bpf_high_hz: float | None = None
    bpf_update: bool = False  # explicit flag: send set_bpf even when both are None (disable)


def build_live_demodulation_router(controller) -> APIRouter:
    router = APIRouter(prefix="/live-demodulation", tags=["live-demodulation"])

    @router.post("/start")
    def start_live_demodulation(body: LiveDemodStartBody):
        try:
            return controller.start(
                center_hz=body.center_hz,
                mode=body.mode,
                sample_rate_hz=body.sample_rate_hz,
                gain_db=body.gain_db,
                chunk_duration=body.chunk_duration,
                bpf_low_hz=body.bpf_low_hz,
                bpf_high_hz=body.bpf_high_hz,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/stop")
    def stop_live_demodulation():
        return controller.stop()

    @router.post("/update")
    def update_live_demodulation(body: LiveDemodUpdateBody):
        try:
            if body.gain_db is not None:
                controller.update_gain(body.gain_db)
            if body.center_hz is not None:
                controller.update_freq(body.center_hz)
            if body.bpf_update:
                controller.update_bpf(body.bpf_low_hz, body.bpf_high_hz)
            return controller.get_status()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/status")
    def get_live_demodulation_status():
        return controller.get_status()

    @router.get("/stream")
    async def stream_live_audio(request: Request):
        async def generate():
            async for event in controller.sse_generator():
                if await request.is_disconnected():
                    break
                yield event

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router
