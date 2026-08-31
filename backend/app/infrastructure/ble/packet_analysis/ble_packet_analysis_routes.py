from __future__ import annotations

from fastapi import APIRouter, HTTPException


def build_ble_packet_analysis_router(manager) -> APIRouter:
    router = APIRouter(prefix="/ble/packet-analysis", tags=["ble-packet-analysis-lab"])

    def call(fn):
        try:
            return fn()
        except FileNotFoundError as error:
            raise HTTPException(404, str(error) or "NOT_FOUND") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/captures")
    def captures():
        return call(manager.list_captures)

    @router.get("/captures/latest-completed")
    def latest_completed():
        return call(manager.latest_completed_capture)

    @router.post("/jobs", status_code=202)
    def start_job(body: dict):
        return call(lambda: manager.start_job(body["capture_id"], body.get("replay_run_id")))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return call(lambda: manager.get_job(job_id))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return call(lambda: manager.cancel_job(job_id))

    @router.get("/captures/{capture_id}/analysis")
    def latest_analysis(capture_id: str):
        return call(lambda: manager.latest_analysis_for_capture(capture_id))

    @router.get("/analyses/{analysis_id}")
    def get_analysis(analysis_id: str, capture_id: str):
        return call(lambda: manager.get_analysis(capture_id, analysis_id))

    return router
