import hashlib, json, threading
from datetime import datetime, timezone
from .ble_artifact_validator import BleArtifactValidator
from .ble_contracts import BleJobRequest
from .ble_errors import BleIntegrationError, IqRecoveryNotAvailable

TERMINAL={"completed","completed_with_diagnostics","cancelled","failed","timed_out"}
def now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

class BleJobManager:
    def __init__(self,repository,adapter,enabled=True): self.repository=repository; self.adapter=adapter; self.enabled=enabled; self.validator=BleArtifactValidator(); self.cancelled=set(); self.lock=threading.Lock()
    def create(self,payload):
        if not self.enabled: raise PermissionError("ble_analyzer_disabled")
        request=BleJobRequest.model_validate(payload)
        if request.input_mode != "validated_bitstream_replay": raise IqRecoveryNotAvailable()
        with self.lock:
            nums=[int(p.name.rsplit("-",1)[-1]) for p in self.repository.root.glob("BLE-JOB-*") if p.name.rsplit("-",1)[-1].isdigit()]
            jid=f"BLE-JOB-{max(nums,default=0)+1:06d}"; request_data=request.model_dump(); request_data["job_id"]=jid; path=self.repository.create(jid,request_data)
            (path/"request.sha256").write_text(hashlib.sha256((path/"request.json").read_bytes()).hexdigest()+"\n",encoding="ascii")
            self.repository.write(jid,"job.json",{"job_id":jid,"state":"created","request":request_data}); self.transition(jid,"created",None,"request_accepted"); self.transition(jid,"queued","created","execution_scheduled")
        threading.Thread(target=self.execute,args=(jid,),daemon=True).start(); return self.get(jid)
    def transition(self,jid,state,previous,reason,**extra):
        event={"sequence":len(self.repository.events(jid))+1,"job_id":jid,"timestamp_utc":now(),"previous_state":previous,"new_state":state,"reason":reason,**extra}; self.repository.append_event(jid,event)
        job=self.repository.read(jid,"job.json"); job.update(state=state,updated_at_utc=event["timestamp_utc"],error=extra.get("error")); self.repository.write(jid,"job.json",job)
    def execute(self,jid):
        state="queued"
        try:
            for nxt,reason in (("validating_input","dequeued"),("starting_worker","input_valid"),("running","worker_started")): self.transition(jid,nxt,state,reason); state=nxt
            result=self.adapter.run(jid,self.repository.job_dir(jid),lambda:jid in self.cancelled)
            if result.get("cancelled"): self.transition(jid,"cancelled",state,"worker_cancelled"); return
            if result.get("exit_code") != 0: raise RuntimeError(f"worker_exit_nonzero:{result.get('exit_code')}")
            self.transition(jid,"validating_artifacts",state,"worker_exit_zero",worker_exit_code=0); state="validating_artifacts"
            root=self.repository.job_dir(jid); self.validator.validate(root,jid)
            job=self.get(jid); job["artifact_manifest_sha256"]=hashlib.sha256((root/"artifacts_manifest.json").read_bytes()).hexdigest(); self.repository.write(jid,"job.json",job)
            self.transition(jid,"completed",state,"artifacts_valid")
        except TimeoutError as e: self.transition(jid,"timed_out",state,"worker_timeout",error=str(e))
        except Exception as e: self.transition(jid,"failed",state,e.code if isinstance(e,BleIntegrationError) else "worker_failed",error=str(e))
    def get(self,jid): return self.repository.read(jid,"job.json")
    def cancel(self,jid):
        job=self.get(jid)
        if job["state"] not in TERMINAL: self.cancelled.add(jid); self.transition(jid,"cancel_requested",job["state"],"user_requested")
        return self.get(jid)
    def retry(self,jid):
        old=self.get(jid)
        if old["state"] not in TERMINAL: raise ValueError("job_not_terminal")
        return self.create(old["request"])
