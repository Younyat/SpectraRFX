import shutil, tempfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.infrastructure.ble.ble_contracts import CAPABILITIES
from app.infrastructure.ble.ble_errors import BleIntegrationError

def build_ble_router(manager):
    r=APIRouter(prefix="/ble",tags=["ble-lab"])
    def operational():
        if not manager.enabled: raise HTTPException(404,"ble_analyzer_disabled")
    def handle(fn):
        try: return fn()
        except BleIntegrationError as e: raise HTTPException(409,{"code":e.code,"message":str(e)}) from e
        except FileNotFoundError as e: raise HTTPException(404,"ble_job_not_found") from e
        except (ValueError,PermissionError) as e: raise HTTPException(400,str(e)) from e
    @r.get("/capabilities")
    def capabilities(): return {"enabled":manager.enabled,**CAPABILITIES}
    @r.post("/jobs",status_code=202)
    def create(body:dict): operational(); return handle(lambda:manager.create(body))
    @r.get("/jobs/{jid}")
    def get(jid): operational(); return handle(lambda:manager.get(jid))
    @r.post("/jobs/{jid}/cancel")
    def cancel(jid): operational(); return handle(lambda:manager.cancel(jid))
    @r.post("/jobs/{jid}/retry",status_code=202)
    def retry(jid): operational(); return handle(lambda:manager.retry(jid))
    @r.get("/jobs/{jid}/events")
    def events(jid): operational(); return handle(lambda:{"events":manager.repository.events(jid)})
    mapping={"packets":"confirmed_packets.jsonl","advertisements":"advertisements.jsonl","diagnostics":"semantic_diagnostics.jsonl"}
    for endpoint,filename in mapping.items():
        def reader(jid,_name=filename,_key=endpoint): operational(); return handle(lambda:{_key:manager.repository.jsonl(jid,_name)})
        r.add_api_route(f"/jobs/{{jid}}/{endpoint}",reader,methods=["GET"])
    @r.get("/jobs/{jid}/advertisers")
    def advertisers(jid): operational(); return handle(lambda:manager.repository.read(jid,"advertisers.json"))
    @r.get("/jobs/{jid}/channels")
    def channels(jid): operational(); return handle(lambda:manager.repository.read(jid,"receiver_stage_summary.json"))
    @r.get("/jobs/{jid}/artifacts")
    def artifacts(jid): return handle(lambda:manager.repository.read(jid,"artifacts_manifest.json"))
    @r.get("/jobs/{jid}/bundle")
    def bundle(jid):
        root=manager.repository.job_dir(jid)
        if not root.is_dir(): raise HTTPException(404,"ble_job_not_found")
        target=tempfile.gettempdir()+f"/{jid}"; archive=shutil.make_archive(target,"zip",root)
        return FileResponse(archive,filename=f"{jid}.zip",media_type="application/zip")
    return r
