"""Routes for the experimental Gate 2A.2 section of BLE Lab: live status (read
from ble-worker-lab's own artifacts) and the offline IQ analysis job flow. Kept
in a separate router from routes.py (Gate 1B) on purpose -- nothing here can
change Gate 1B's behavior."""
import shutil
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.infrastructure.ble.ble_gate2a2_status import gate2a2_status


def build_ble_gate2a2_router(manager):
    router = APIRouter(prefix="/ble/gate2a2", tags=["ble-lab-gate2a2-experimental"])

    def operational():
        if not manager.enabled:
            raise HTTPException(404, "ble_gate2a2_offline_disabled")

    def handle(fn):
        try:
            return fn()
        except FileNotFoundError as error:
            raise HTTPException(404, "ble_gate2a2_job_not_found") from error
        except (ValueError, PermissionError) as error:
            raise HTTPException(400, str(error)) from error
        except Exception as error:  # worker/adapter failures surface as 409, matching Gate 1B's convention
            raise HTTPException(409, str(error)) from error

    @router.get("/status")
    def status():
        return gate2a2_status()

    @router.post("/jobs", status_code=202)
    def create(body: dict):
        operational()
        return handle(lambda: manager.create(body))

    @router.get("/jobs/{job_id}")
    def get(job_id: str):
        operational()
        return handle(lambda: manager.get(job_id))

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        operational()
        return handle(lambda: manager.cancel(job_id))

    mapping = {
        "candidates": "candidates.jsonl",
        "confirmed-packets": "confirmed_packets.jsonl",
        "semantic-packets": "semantic_packets.jsonl",
        "events": "dsp_stage_events.jsonl",
        "rejections": "rejections.jsonl",
    }
    for endpoint, filename in mapping.items():
        def reader(job_id, _name=filename, _key=endpoint):
            operational()
            return handle(lambda: {_key: manager.repository.jsonl(job_id, _name)})
        router.add_api_route(f"/jobs/{{job_id}}/{endpoint}", reader, methods=["GET"])

    @router.get("/jobs/{job_id}/known-limitations")
    def known_limitations(job_id: str):
        operational()
        return handle(lambda: manager.repository.read(job_id, "known_limitations.json"))

    @router.get("/jobs/{job_id}/result-summary")
    def result_summary(job_id: str):
        operational()
        return handle(lambda: manager.repository.read(job_id, "result_summary.json"))

    @router.get("/jobs/{job_id}/bundle")
    def bundle(job_id: str):
        root = manager.repository.job_dir(job_id)
        if not root.is_dir():
            raise HTTPException(404, "ble_gate2a2_job_not_found")
        target = tempfile.gettempdir() + f"/{job_id}"
        archive = shutil.make_archive(target, "zip", root)
        return FileResponse(archive, filename=f"{job_id}.zip", media_type="application/zip")

    @router.get("/hybrid/sessions")
    def hybrid_sessions():
        root = manager.repository.root.parent.parent / "ble_lab" / "sessions"
        values = []
        if root.is_dir():
            for session in root.iterdir():
                metrics = session / "correlation" / "metrics.json"
                packets = session / "correlation" / "decoded_packets.jsonl"
                if metrics.is_file() and packets.is_file():
                    values.append({"session_id":session.name,"metrics":manager.repository._read_json(metrics) if hasattr(manager.repository,"_read_json") else __import__('json').loads(metrics.read_text())})
        return {"sessions":sorted(values,key=lambda x:x["session_id"],reverse=True)}

    @router.get("/hybrid/sessions/{session_id}/packets")
    def hybrid_packets(session_id: str):
        if any(x in session_id for x in ("/", "\\", "..")): raise HTTPException(400,"invalid_session_id")
        path = manager.repository.root.parent.parent / "ble_lab" / "sessions" / session_id / "correlation" / "decoded_packets.jsonl"
        if not path.is_file(): raise HTTPException(404,"hybrid_session_not_found")
        import json
        return {"session_id":session_id,"packets":[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]}

    return router
