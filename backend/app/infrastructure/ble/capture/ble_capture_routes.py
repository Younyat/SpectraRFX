from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def build_ble_capture_router(manager, offline_manager=None):
    router = APIRouter(prefix="/ble/capture", tags=["ble-real-iq-capture-experimental"])

    def call(fn):
        try: return fn()
        except FileNotFoundError as error: raise HTTPException(404, "CAPTURE_NOT_FOUND") from error
        except PermissionError as error: raise HTTPException(403, str(error)) from error
        except (ValueError, OSError) as error: raise HTTPException(400, str(error)) from error
        except RuntimeError as error: raise HTTPException(409, str(error)) from error

    @router.get("/devices")
    def devices(refresh: bool = False): return manager.capabilities(force_probe=refresh)

    @router.post("/jobs", status_code=202)
    def create(body: dict): return call(lambda: manager.create(body))

    @router.get("/jobs/{capture_id}")
    def get(capture_id: str): return call(lambda: manager.get(capture_id))

    @router.post("/jobs/{capture_id}/cancel")
    def cancel(capture_id: str): return call(lambda: manager.cancel(capture_id))

    @router.get("/jobs/{capture_id}/live")
    def live(capture_id: str): return call(lambda: manager.live_frame(capture_id))

    @router.get("/recordings")
    def recordings(): return {"captures": manager.list_captures()}

    @router.get("/recordings/{capture_id}")
    def metadata(capture_id: str): return call(lambda: manager.metadata(capture_id))

    @router.get("/recordings/{capture_id}/verify")
    def verify(capture_id: str): return call(lambda: manager.verify(capture_id))

    @router.get("/recordings/{capture_id}/rf-diagnostic")
    def rf_diagnostic(capture_id: str): return call(lambda: manager.rf_diagnostic(capture_id))

    @router.post("/recordings/{capture_id}/offline-replay", status_code=201)
    def offline_replay(capture_id: str, body: dict | None = None):
        return call(lambda: manager.offline_replay(capture_id, body or {}))

    @router.get("/recordings/{capture_id}/offline-replay/latest")
    def latest_offline_replay(capture_id: str):
        return call(lambda: manager.latest_offline_replay(capture_id))

    @router.post("/recordings/{capture_id}/offline-replay-jobs", status_code=202)
    def start_offline_replay_job(capture_id: str, body: dict | None = None):
        return call(lambda: manager.start_offline_replay(capture_id, body or {}))

    @router.get("/recordings/{capture_id}/offline-replay-jobs/latest")
    def latest_offline_replay_job(capture_id: str):
        return call(lambda: manager.latest_offline_replay_job(capture_id))

    @router.get("/recordings/{capture_id}/offline-replay-jobs/{replay_run_id}")
    def offline_replay_job(capture_id: str, replay_run_id: str):
        return call(lambda: manager.offline_replay_job(capture_id, replay_run_id))

    @router.post("/recordings/{capture_id}/offline-replay-jobs/{replay_run_id}/cancel")
    def cancel_offline_replay_job(capture_id: str, replay_run_id: str):
        return call(lambda: manager.cancel_offline_replay(capture_id, replay_run_id))

    @router.get("/rf-diagnostic-profiles")
    def rf_diagnostic_profiles(): return call(lambda: manager.rf_diagnostic_profiles())

    @router.get("/recordings/{capture_id}/sigmf-meta")
    def sigmf_meta(capture_id: str): return call(lambda: FileResponse(manager.meta_path(capture_id), filename=f"{capture_id}.sigmf-meta"))

    @router.get("/recordings/{capture_id}/iq")
    def iq(capture_id: str): return call(lambda: FileResponse(manager.data_path(capture_id), filename=f"{capture_id}.sigmf-data"))

    @router.post("/recordings/{capture_id}/analyze", status_code=202)
    def analyze(capture_id: str):
        def start():
            if offline_manager is None or not offline_manager.enabled: raise PermissionError("BLE_GATE2A2_OFFLINE_DISABLED")
            record = manager.metadata(capture_id)
            if record["sample_rate_sps"] != 4_000_000 or record.get("sample_format") not in (None, "cf32_le"):
                raise ValueError("ANALYSIS_REQUIRES_EXPLICIT_DERIVED_CF32_4MSPS_ARTIFACT")
            return offline_manager.create({"iq_file_path": str(manager.data_path(capture_id)), "channel_index": record["ble_channel"]})
        return call(start)

    return router
