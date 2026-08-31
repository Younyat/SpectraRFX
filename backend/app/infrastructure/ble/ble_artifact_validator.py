import hashlib, json
from pathlib import Path
from .ble_contracts import CONTRACT_VERSION, WORKER_COMMIT
from .ble_errors import *

ALLOWED={"request.json","request.sha256","job.json","job_events.jsonl","worker_stdout.log","worker_stderr.log","worker_exit.json","artifacts_manifest.json"}

class BleArtifactValidator:
    def validate(self,root:Path,job_id:str):
        mp=root/"artifacts_manifest.json"
        if not mp.is_file(): raise ArtifactManifestMissing()
        try: m=json.loads(mp.read_text(encoding="utf-8"))
        except Exception as e: raise ArtifactSchemaInvalid(str(e)) from e
        if m.get("contract_version") != CONTRACT_VERSION: raise UnsupportedContractVersion()
        if m.get("job_id") != job_id: raise ArtifactJobIdMismatch()
        if m.get("worker_commit") != WORKER_COMMIT: raise ArtifactWorkerCommitMismatch()
        if m.get("scientific_status") not in (None,"BLE_P0_INCOMPLETE"): raise ArtifactSchemaInvalid("scientific_status")
        entries=m.get("files",m.get("artifacts"))
        if not isinstance(entries,list): raise ArtifactSchemaInvalid("files must be a list")
        declared=set()
        for item in entries:
            try: name,expected=item["path"],item["sha256"]
            except Exception as e: raise ArtifactSchemaInvalid() from e
            if Path(name).is_absolute() or ".." in Path(name).parts: raise ArtifactSchemaInvalid("unsafe path")
            declared.add(name); p=root/name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected: raise ArtifactHashMismatch(name)
            if "size_bytes" in item and p.stat().st_size != item["size_bytes"]: raise ArtifactHashMismatch(name)
        actual={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        extra=actual-declared-ALLOWED
        if extra: raise UndeclaredArtifact(sorted(extra)[0])
        data={n:self._jsonl(root/n) for n in ("candidate_packets.jsonl","confirmed_packets.jsonl","parsed_packets.jsonl","advertisements.jsonl")}
        confirmed=data["confirmed_packets.jsonl"]; ids=[p.get("packet_id") for p in confirmed]
        if None in ids or len(ids)!=len(set(ids)): raise DuplicatePacketId()
        if any(p.get("crc_valid") is not True for p in confirmed): raise InvalidCrcPacketPublished()
        valid=set(ids)
        for name in ("parsed_packets.jsonl","advertisements.jsonl"):
            pub=[p.get("packet_id") for p in data[name]]
            if len(pub)!=len(set(pub)): raise DuplicatePacketPublication(name)
            if any(x not in valid for x in pub): raise InvalidCrcPacketPublished(name)
        counts=m.get("counts",{})
        if counts.get("confirmed_packets") != len(confirmed): raise ArtifactCountMismatch()
        return m
    @staticmethod
    def _jsonl(path):
        if not path.exists(): return []
        out=[]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try: value=json.loads(line)
            except Exception as e: raise InvalidJsonlRecord(path.name) from e
            if not isinstance(value,dict): raise InvalidJsonlRecord(path.name)
            out.append(value)
        return out
