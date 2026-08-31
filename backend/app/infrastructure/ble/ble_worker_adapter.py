import hashlib, json, subprocess, sys, time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .ble_contracts import WORKER_COMMIT
from .ble_errors import WorkerUnavailable, WorkerVersionMismatch

def utc(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

@dataclass
class WorkerConfig:
    repository: Path
    python_executable: Path
    entry_point: Path
    timeout_seconds: float=60.0

class BleWorkerAdapter:
    def __init__(self,config): self.config=config
    def verify(self):
        if not self.config.python_executable.is_file() or not self.config.repository.is_dir() or not self.config.entry_point.is_file(): raise WorkerUnavailable()
        try: commit=subprocess.run(["git","-c",f"safe.directory={self.config.repository}","-C",str(self.config.repository),"rev-parse","HEAD"],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        except Exception as e: raise WorkerUnavailable(str(e)) from e
        if commit != WORKER_COMMIT: raise WorkerVersionMismatch(commit)
    def run(self,job_id,job_dir,cancel_requested):
        self.verify(); req=job_dir/"request.json"; outp=job_dir/"worker_stdout.log"; errp=job_dir/"worker_stderr.log"
        cmd=[str(self.config.python_executable),str(self.config.entry_point),"--worker-repository",str(self.config.repository),"--request",str(req),"--output-dir",str(job_dir),"--job-id",job_id]
        started=utc(); monotonic=time.monotonic()
        with outp.open("wb") as out, errp.open("wb") as err:
            process=subprocess.Popen(cmd,cwd=self.config.entry_point.parent,stdout=out,stderr=err)
            while process.poll() is None:
                if cancel_requested(): process.terminate(); process.wait(timeout=5); return {"cancelled":True,"exit_code":process.returncode}
                if time.monotonic()-monotonic > self.config.timeout_seconds: process.kill(); process.wait(); raise TimeoutError("BLE worker timeout")
                time.sleep(.05)
        pyver=subprocess.run([str(self.config.python_executable),"--version"],capture_output=True,text=True,timeout=5).stdout.strip()
        result={"worker_repository":str(self.config.repository),"worker_commit":WORKER_COMMIT,"python_executable":str(self.config.python_executable),"python_version":pyver,"command_line":cmd,"working_directory":str(self.config.entry_point.parent),"request_sha256":hashlib.sha256(req.read_bytes()).hexdigest(),"start_timestamp_utc":started,"end_timestamp_utc":utc(),"exit_code":process.returncode,"stdout_path":outp.name,"stderr_path":errp.name,"timeout_seconds":self.config.timeout_seconds,"cancellation_status":"not_requested"}
        (job_dir/"worker_exit.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        return result
