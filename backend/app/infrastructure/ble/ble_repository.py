import json
from pathlib import Path
from threading import Lock

class BleRepository:
    def __init__(self, root: Path): self.root=root; root.mkdir(parents=True,exist_ok=True); self.lock=Lock()
    def job_dir(self,jid):
        p=(self.root/jid).resolve()
        if p.parent != self.root.resolve(): raise ValueError("invalid job id")
        return p
    def create(self,jid,request): self.job_dir(jid).mkdir(); self.write(jid,"request.json",request); return self.job_dir(jid)
    def write(self,jid,name,value): (self.job_dir(jid)/name).write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    def read(self,jid,name): return json.loads((self.job_dir(jid)/name).read_text(encoding="utf-8"))
    def append_event(self,jid,event):
        with self.lock:
            with (self.job_dir(jid)/"job_events.jsonl").open("a",encoding="utf-8",newline="\n") as f: f.write(json.dumps(event,sort_keys=True)+"\n")
    def events(self,jid):
        p=self.job_dir(jid)/"job_events.jsonl"; return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
    def jsonl(self,jid,name):
        p=self.job_dir(jid)/name; return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
