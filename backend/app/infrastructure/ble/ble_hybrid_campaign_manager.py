from __future__ import annotations

import hashlib, json, os, re, statistics, subprocess, threading, time, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from .campaign_policy import (
    EXPLORATORY_TARGET_SEARCH,
    NEGATIVE_CONTROL,
    POSITIVE_TARGET_VALIDATION,
    contract_from_session,
    validate_campaign_contract,
)

TERMINAL={"completed","failed","cancelled","timed_out"}
def utc(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
POSITIVE_PILOT_GATE_VERSION="ble-rffi-positive-pilot-gate-v2"
POSITIVE_PILOT_PROFILE_ID="QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S"
POSITIVE_PILOT_RECEIVER_SERIAL="E3R04Z1B2"
SOURCE_CLEAN_IGNORE_PATHS=("backend/app/infrastructure/persistence/storage/kiwisdr/receiver_catalog.json",)

class BleHybridCampaignManager:
    """Thin orchestration layer over the existing native/capture/DSP tools."""
    def __init__(self, root:Path, capture, native, python:Path, decoder:Path, correlator:Path, worker_repo:Path):
        self.root,self.capture,self.native=root,capture,native; self.python,self.decoder,self.correlator,self.worker_repo=python,decoder,correlator,worker_repo
        root.mkdir(parents=True,exist_ok=True); self._lock=threading.Lock(); self._active=None; self._cancel=set()
    def _path(self,sid):
        if any(x in sid for x in ("/","\\","..")): raise ValueError("INVALID_SESSION_ID")
        return self.root/sid
    def _write(self,sid,**fields):
        # Real-hardware bug fix (2026-08-13): session_manifest.json used a
        # plain write_text() (truncate-then-write, not atomic) while get()
        # polls the SAME file every ~1s with an unguarded json.loads() --
        # a real, observed race during a live timing-diagnostic capture
        # (json.loads caught the file mid-truncation and crashed with
        # "Expecting value: line 1 column 1 (char 0)"). atomic_json's
        # write-to-.tmp-then-os.replace() pattern (already used everywhere
        # else in this codebase) makes every read see either the old or the
        # new complete content, never a transiently-empty file.
        path=self._path(sid); path.mkdir(parents=True,exist_ok=True); target=path/"session_manifest.json"; old=json.loads(target.read_text()) if target.exists() else {}
        atomic_json(target,{**old,**fields,"session_id":sid,"updated_at_utc":utc()})
    def _canonical_sha256(self,value:dict[str,Any]):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("utf-8")).hexdigest()
    def _git_output(self,*args):
        try:
            repo=Path(__file__).resolve().parents[4]
            return subprocess.run(["git","-C",str(repo),*args],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        except Exception:
            return None
    def _repository_state(self):
        commit=self._git_output("rev-parse","HEAD")
        pathspec=["--",".",*(f":(exclude){path}" for path in SOURCE_CLEAN_IGNORE_PATHS)]
        status=self._git_output("status","--porcelain=v1",*pathspec) or ""
        diff=self._git_output("diff","--binary","HEAD",*pathspec) or ""
        dirty=bool(status.strip())
        return {
            "repository_commit":commit or "UNKNOWN",
            "working_tree_status":"DIRTY_RECORDED" if dirty else "CLEAN",
            "working_tree_dirty":dirty,
            "working_tree_status_porcelain":status.splitlines(),
            "working_tree_diff_sha256":hashlib.sha256(diff.encode("utf-8")).hexdigest() if dirty else None,
        }
    def _freeze_positive_pilot_protocol(self,metadata:dict[str,Any],payload:dict[str,Any],channel:int,duration:float):
        if metadata.get("execution_purpose")!="POSITIVE_PILOT":
            return metadata
        # POSITIVE_PILOT always runs offline burst segmentation after I/Q
        # integrity verification. Treat this as a backend-enforced protocol
        # invariant, not as a UI-controlled operator option.
        metadata["analysis_enabled"]=True
        protocol_manifest=dict(metadata.get("protocol_manifest") or {})
        protocol_manifest["analysis_enabled"]=True
        metadata["protocol_manifest"]=protocol_manifest
        actual_serial=None
        try:
            actual_serial=self.capture.devices.private_args(payload["device_id"]).get("serial")
        except Exception:
            actual_serial=None
        expected={
            "protocol_id":metadata.get("protocol_id") or metadata.get("base_protocol_id") or "BLE-RFFI-ONE-TARGET-STAGE-ONE-v1",
            "protocol_revision":"positive-pilot-gate-v2",
            "quality_gate_version":POSITIVE_PILOT_GATE_VERSION,
            "execution_purpose":"POSITIVE_PILOT",
            "physical_unit_id":"CC2650-UNIT-01",
            "condition_id":"C001",
            "session_id":"S001-POS",
            "qualification_profile_id":POSITIVE_PILOT_PROFILE_ID,
            "receiver_serial":POSITIVE_PILOT_RECEIVER_SERIAL,
            "usb_mode":"USB_3",
            "center_frequency_hz":2402000000,
            "sample_rate_sps":4000000,
            "bandwidth_hz":2000000,
            "analog_bandwidth_hz":2000000,
            "cpu_format":"cf32",
            "file_format":"cf32_le",
            "sample_format":"cf32_le",
            "antenna":"RX2",
            "gain_db":20,
            "duration_seconds":10,
            "disk_persistence_enabled":True,
            "windows_ble_scan_enabled":True,
            "frontend_preview_enabled":False,
            "analysis_enabled":True,
            "online_decoder_enabled":False,
            "online_correlation_enabled":False,
            "minimum_unique_target_packets_for_e4_observation":1,
            "minimum_unique_target_packets_for_dataset_acceptance":3,
        }
        observed={
            "protocol_id":metadata.get("protocol_id") or metadata.get("base_protocol_id"),
            "protocol_revision":metadata.get("protocol_revision"),
            "quality_gate_version":metadata.get("quality_gate_version"),
            "execution_purpose":metadata.get("execution_purpose"),
            "physical_unit_id":metadata.get("physical_unit_id"),
            "condition_id":metadata.get("condition_id"),
            "session_id":metadata.get("session_id") or metadata.get("operator_session_id"),
            "qualification_profile_id":metadata.get("qualification_profile_id"),
            "receiver_serial":metadata.get("receiver_serial") or actual_serial,
            "usb_mode":metadata.get("usb_mode"),
            "center_frequency_hz":int(metadata.get("center_frequency_hz") or 0),
            "sample_rate_sps":int(metadata.get("sample_rate_sps") or 0),
            "bandwidth_hz":int(metadata.get("bandwidth_hz") or metadata.get("analog_bandwidth_hz") or 0),
            "analog_bandwidth_hz":int(metadata.get("analog_bandwidth_hz") or metadata.get("bandwidth_hz") or 0),
            "cpu_format":metadata.get("cpu_format"),
            "file_format":metadata.get("file_format") or metadata.get("sample_format"),
            "sample_format":metadata.get("sample_format") or metadata.get("file_format"),
            "antenna":metadata.get("antenna"),
            "gain_db":int(float(metadata.get("gain_db") or payload.get("gain_db") or 0)),
            "duration_seconds":int(float(metadata.get("effective_duration_seconds") or metadata.get("protocol_duration_seconds") or duration)),
            "disk_persistence_enabled":bool(metadata.get("disk_persistence_enabled")),
            "windows_ble_scan_enabled":bool(metadata.get("windows_ble_scan_enabled")),
            "frontend_preview_enabled":bool(metadata.get("frontend_preview_enabled")),
            "analysis_enabled":bool(metadata.get("analysis_enabled")),
            "online_decoder_enabled":bool(metadata.get("online_decoder_enabled",metadata.get("decoder_online_enabled",True))),
            "online_correlation_enabled":bool(metadata.get("online_correlation_enabled",metadata.get("correlation_online_enabled",True))),
            "minimum_unique_target_packets_for_e4_observation":int(metadata.get("minimum_unique_target_packets_for_e4_observation") or 0),
            "minimum_unique_target_packets_for_dataset_acceptance":int(metadata.get("minimum_unique_target_packets_for_dataset_acceptance") or 0),
        }
        if actual_serial!=POSITIVE_PILOT_RECEIVER_SERIAL:
            raise ValueError("PROTOCOL_FREEZE_MISMATCH:receiver_serial")
        if channel!=37 or abs(duration-10.0)>1e-6 or float(payload.get("gain_db",20))!=20.0:
            raise ValueError("PROTOCOL_FREEZE_MISMATCH:positive_pilot_profile")
        mismatches=[key for key,value in expected.items() if observed.get(key)!=value]
        if mismatches:
            raise ValueError("PROTOCOL_FREEZE_MISMATCH:"+",".join(mismatches))
        manifest=dict(metadata.get("protocol_manifest") or {})
        manifest_mismatches=[key for key,value in expected.items() if manifest.get(key)!=value]
        if manifest_mismatches:
            raise ValueError("PROTOCOL_FREEZE_MISMATCH:protocol_manifest."+(",".join(manifest_mismatches)))
        source_state=self._repository_state()
        if source_state["working_tree_status"]!="CLEAN":
            raise ValueError("PROTOCOL_FREEZE_MISMATCH:source_working_tree_status")
        manifest={key:expected[key] for key in sorted(expected)}
        protocol_hash=self._canonical_sha256(manifest)
        metadata.update({
            "freeze_validation_status":"PASSED",
            "quality_gate_version":POSITIVE_PILOT_GATE_VERSION,
            "receiver_serial":POSITIVE_PILOT_RECEIVER_SERIAL,
            "protocol_manifest":manifest,
            "protocol_manifest_sha256":protocol_hash,
            "protocol_hash":protocol_hash,
            "protocol_frozen_at_utc":utc(),
            "source_repository_commit":source_state["repository_commit"],
            "source_working_tree_status":source_state["working_tree_status"],
            "source_working_tree_dirty":source_state["working_tree_dirty"],
            "source_working_tree_diff_sha256":source_state["working_tree_diff_sha256"],
            "execution_freeze":{**source_state,"protocol_manifest_sha256":protocol_hash,"freeze_scope":"C001/S001-POS POSITIVE_PILOT"},
        })
        return metadata
    def start(self,payload:dict[str,Any]):
        channel=int(payload.get("channel",37)); duration=float(payload.get("duration_seconds",30)); target=payload.get("target") or {"kind":"any"}
        if channel not in (37,38,39) or not 1<=duration<=60 or not payload.get("device_id"): raise ValueError("INVALID_HYBRID_CONFIGURATION")
        contract=validate_campaign_contract(payload,target)
        metadata=dict(payload.get("experimental_metadata") or {})
        required=("distance","orientation","location","physical_unit_id","power_state")
        missing=[key for key in required if str(metadata.get(key) or "").strip().lower() in {"","documentar","pendiente","unknown","desconocido"}]
        if missing: raise ValueError("EXPERIMENTAL_METADATA_REQUIRED:"+",".join(missing))
        if not re.search(r"\d+(?:[.,]\d+)?\s*(?:mm|cm|m)\b",str(metadata["distance"]).strip(),re.IGNORECASE): raise ValueError("EXPERIMENTAL_DISTANCE_REQUIRES_UNIT")
        if contract["negative_control_type"]=="target_powered_off" and metadata["power_state"]!="powered_off": raise ValueError("NEGATIVE_CONTROL_POWER_STATE_MISMATCH")
        metadata["recorded_at_utc"]=utc()
        payload={**payload,"device_id":self.capture.resolve_device_id(payload.get("device_id"))}
        if metadata.get("execution_purpose")=="POSITIVE_PILOT":
            metadata=self._freeze_positive_pilot_protocol(metadata,payload,channel,duration)
        else:
            metadata.setdefault("protocol_duration_seconds", duration)
            metadata.setdefault("effective_duration_seconds", duration)
            metadata.setdefault("duration_source", "operator_parameter")
            metadata.setdefault("protocol_override", False)
            metadata.setdefault("override_reason", None)
            metadata.setdefault("protocol_revision", "rev1")
            metadata.setdefault("minimum_target_crc_packets", 1)
            metadata.setdefault("minimum_target_strong_matches", 1)
            metadata.setdefault("minimum_unique_target_packets_for_e4_observation", 1)
            metadata.setdefault("minimum_unique_target_packets_for_dataset_acceptance", 3)
            metadata.setdefault("quality_gate_version", POSITIVE_PILOT_GATE_VERSION)
            metadata.setdefault("protocol_manifest", {
                "protocol_revision": metadata.get("protocol_revision", "rev1"),
                "quality_gate_version": metadata["quality_gate_version"],
                "minimum_unique_target_packets_for_e4_observation": metadata["minimum_unique_target_packets_for_e4_observation"],
                "minimum_unique_target_packets_for_dataset_acceptance": metadata["minimum_unique_target_packets_for_dataset_acceptance"],
            })
            metadata.setdefault("decoder_online_enabled", False)
            metadata.setdefault("correlation_online_enabled", False)
        capture_disk_persistence = bool(metadata.get("disk_persistence_enabled", True))
        capture_frontend_preview = bool(metadata.get("frontend_preview_enabled", True))
        capture_ui_polling_mode = str(metadata.get("ui_polling_mode") or ("minimal" if not capture_frontend_preview else "normal"))
        capture_analysis_enabled = bool(metadata.get("analysis_enabled", metadata.get("execution_purpose") in {"POSITIVE_PILOT", "NEGATIVE_CONTROL"}))
        with self._lock:
            if self._active: raise RuntimeError("HYBRID_CAMPAIGN_ALREADY_RUNNING")
            sid="BLE-HYBRID-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:6]
            self._active=sid
        request={"device_id":payload["device_id"],"ble_channel":channel,"center_frequency_hz":{37:2402000000,38:2426000000,39:2480000000}[channel],"sample_rate_sps":4000000,"bandwidth_hz":2000000,"gain_mode":"manual","gain_db":float(payload.get("gain_db",20)),"antenna":"RX2","duration_seconds":duration,"sample_format":"cf32_le","purpose":"BLE hybrid dashboard campaign","controlled_transmitter_state":"unknown","operator_confirmed":False,"capture_role":"controlled_transmitter_active_B","disk_persistence_enabled":capture_disk_persistence,"frontend_preview_enabled":capture_frontend_preview,"ui_polling_mode":capture_ui_polling_mode,"analysis_enabled":capture_analysis_enabled,"experimental_metadata":metadata}
        target_mode="any_device" if target.get("kind")=="any" else "specific_device"
        self._write(sid,state="initializing",created_at_utc=utc(),mode="hybrid",channel=channel,duration_seconds=duration,
            target=target,target_mode=target_mode,target_device_id=target.get("device_id"),target_address=target.get("address"),
            target_name_at_start=target.get("label"),target_selection_source=target.get("selection_source","any_device"),
            campaign_intent=contract["campaign_intent"],negative_control_type=contract["negative_control_type"],
            operator_confirmation=contract["operator_confirmation"],target_seen_before_start=contract["target_seen_before_start"],
            experimental_metadata=metadata,
            steps={"hardware":"running","native_scan":"pending","b200_capture":"pending","burst_detection":"pending","decoding":"pending","correlation":"pending","results":"pending"},counters={})
        threading.Thread(target=self._run,args=(sid,request),daemon=True).start(); return self.get(sid)
    def _run(self,sid,request):
        try:
            self.native.start_scan(sid); self._write(sid,state="capturing",steps={"hardware":"completed","native_scan":"running","b200_capture":"running","burst_detection":"pending","decoding":"pending","correlation":"pending","results":"pending"})
            job=self.capture.create(request); cid=job["capture_id"]; self._write(sid,capture_id=cid)
            while job["state"] not in TERMINAL:
                if sid in self._cancel: self.capture.cancel(cid)
                time.sleep(.5); job=self.capture.get(cid)
            self.native.stop_scan()
            if job["state"]!="completed": raise RuntimeError(f"CAPTURE_{job['state'].upper()}")
            cap=self.capture._job_dir(cid); bursts=sum(1 for _ in (cap/"burst_candidates.jsonl").open(encoding="utf-8")); quality=json.loads((cap/"quality_report.json").read_text())
            decoded=cap/"decoded"; self._write(sid,state="decoding",capture_manifest=str(cap/"capture_manifest.json"),native_scan_path=str(self.native.root/"scans"/sid),steps={"hardware":"completed","native_scan":"completed","b200_capture":"completed","burst_detection":"completed","decoding":"running","correlation":"pending","results":"pending"},counters={"detected_bursts":bursts,"processed_bursts":0,"crc_valid_packets":0,"native_callbacks":self._native_count(sid),"overflows":quality["overflow_count"]})
            decode_timed_out=False
            try:
                subprocess.run([str(self.python),str(self.decoder),"--segments-dir",str(cap/"iq_bursts"),"--output-dir",str(decoded),"--worker-repository",str(self.worker_repo),"--channel",str(request["ble_channel"])],check=True,timeout=float(os.environ.get("BLE_HYBRID_DECODE_TIMEOUT_SECONDS","7200")))
            except subprocess.TimeoutExpired:
                decode_timed_out=True
                progress_path=decoded/"progress.json"; packets_path=decoded/"decoded_packets.jsonl"; summary_path=decoded/"batch_summary.json"
                progress=json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
                if not packets_path.exists() or int(progress.get("crc_valid_packets") or 0) <= 0:
                    raise
                if not summary_path.exists():
                    write_summary={"segments":int(progress.get("processed_segments") or 0),"start_index":0,"end_index":None,
                        "crc_valid_packets":int(progress.get("crc_valid_packets") or 0),"semantic_packets":0,"attempts":[],"partial":True}
                    summary_path.write_text(json.dumps(write_summary,indent=2)+"\n",encoding="utf-8")
            summary=json.loads((decoded/"batch_summary.json").read_text()); out=self._path(sid)/"correlation"
            decode_step="completed_partial_timeout" if decode_timed_out else "completed"
            self._write(sid,state="correlating",steps={"hardware":"completed","native_scan":"completed","b200_capture":"completed","burst_detection":"completed","decoding":decode_step,"correlation":"running","results":"pending"},decode_timed_out=decode_timed_out)
            subprocess.run([str(self.python),str(self.correlator),"--capture-dir",str(cap),"--decoded",str(decoded),"--native",str(self.native.root/"scans"/sid),"--output",str(out),"--window-ms","250"],check=True,timeout=120)
            metrics=json.loads((out/"metrics.json").read_text()); final_steps={k:"completed" for k in ("hardware","native_scan","b200_capture","burst_detection","decoding","correlation","results")}; final_steps["decoding"]=decode_step
            self._write(sid,state="completed",steps=final_steps,counters={"detected_bursts":bursts,"processed_bursts":summary["segments"],"crc_valid_packets":summary["crc_valid_packets"],"native_callbacks":self._native_count(sid),"overflows":quality["overflow_count"],"discontinuities":quality["discontinuity_count"],"strong_matches":metrics["strong_matches"],"payload_matches":metrics["payload_matches"],"ambiguous":metrics["ambiguous"]},result=metrics)
            self._write(sid,scientific_summary=self.scientific_summary(sid))
        except Exception as error: self._write(sid,state="cancelled" if sid in self._cancel else "failed",error=f"{type(error).__name__}:{error}")
        finally:
            try:
                if self.native.status().get("scanning") and self.native.status().get("scan_session_id") == sid: self.native.stop_scan()
            except Exception: pass
            with self._lock:
                if self._active==sid:self._active=None
    def _native_count(self,sid):
        path=self.native.root/"scans"/sid/"advertisements.jsonl"; return sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    def get(self,sid):
        value=json.loads((self._path(sid)/"session_manifest.json").read_text()); progress=self._capture_progress(value.get("capture_id")); value["live"]=progress
        decoded=self.capture.root/value["capture_id"]/"decoded"/"progress.json" if value.get("capture_id") else None
        if decoded and decoded.exists(): value["decode_progress"]=json.loads(decoded.read_text())
        return value
    def _capture_progress(self,cid):
        if not cid:return None
        try:return {"job":self.capture.get(cid),"telemetry":self.capture.live_frame(cid)}
        except Exception:return None
    def stop(self,sid):
        current=self.get(sid)
        if current.get("state") not in TERMINAL: self._cancel.add(sid)
        return self.get(sid)
    def list(self):
        values=[]
        for p in self.root.glob("BLE-HYBRID-*/session_manifest.json"):
            try:
                value=json.loads(p.read_text())
                if value.get("operational_visibility") != "internal_validation": values.append(value)
            except Exception: pass
        return sorted(values,key=lambda x:x.get("created_at_utc",""),reverse=True)

    @staticmethod
    def _jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file(): return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def results(self, sid: str) -> dict[str, Any]:
        session=self.get(sid)
        if session.get("state") != "completed": raise RuntimeError("HYBRID_RESULTS_NOT_READY")
        return {"session":session,"metrics":session.get("result",{}),"packets":self.packets(sid),"matches":self.matches(sid)}

    def packets(self, sid: str) -> list[dict[str, Any]]:
        session=self.get(sid); cid=session.get("capture_id")
        if not cid: return []
        correlated=self._path(sid)/"correlation"/"decoded_packets.jsonl"
        return self._jsonl(correlated if correlated.is_file() else self.capture.root/cid/"decoded"/"decoded_packets.jsonl")

    def matches(self, sid: str) -> list[dict[str, Any]]:
        self.get(sid)
        return self._jsonl(self._path(sid)/"correlation"/"matches.jsonl")

    def evidence(self, sid: str) -> dict[str, Any]:
        session=self.get(sid); cid=session.get("capture_id"); base=self._path(sid)
        return {"session_id":sid,"capture_id":cid,"artifacts":{
            "session_manifest":str(base/"session_manifest.json"),"correlation_metrics":str(base/"correlation"/"metrics.json"),
            "correlation_matches":str(base/"correlation"/"matches.jsonl"),
            "capture_manifest":session.get("capture_manifest"),"decoded_packets":str(self.capture.root/cid/"decoded"/"decoded_packets.jsonl") if cid else None,
            "native_advertisements":str(self.native.root/"scans"/sid/"advertisements.jsonl")}}

    @staticmethod
    def _artifact(path_value: str | Path | None) -> dict[str, Any]:
        path=Path(path_value) if path_value else None
        if not path or not path.is_file(): return {"available":False}
        record_count=None
        if path.suffix==".jsonl":
            record_count=sum(1 for line in path.open(encoding="utf-8") if line.strip())
        return {"available":True,"name":path.name,"path":str(path),"size_bytes":path.stat().st_size,"record_count":record_count,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"created_at_utc":datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat().replace("+00:00","Z")}

    def scientific_summary(self,sid:str)->dict[str,Any]:
        session=json.loads((self._path(sid)/"session_manifest.json").read_text()); cid=session.get("capture_id")
        contract=contract_from_session(session); intent=contract["campaign_intent"]
        cap=self.capture.root/cid if cid else None
        capture=json.loads((cap/"capture_manifest.json").read_text()) if cap and (cap/"capture_manifest.json").is_file() else {}
        quality=json.loads((cap/"quality_report.json").read_text()) if cap and (cap/"quality_report.json").is_file() else {}
        batch=json.loads((cap/"decoded"/"batch_summary.json").read_text()) if cap and (cap/"decoded"/"batch_summary.json").is_file() else {}
        packets=self.packets(sid); matches=self.matches(sid); native=self._jsonl(self.native.root/"scans"/sid/"advertisements.jsonl")
        eligible=[p for p in packets if p.get("pdu_type_name") not in {"SCAN_REQ","CONNECT_IND"}]
        eligible_status=Counter((p.get("correlation") or {}).get("status") or "B200_ONLY" for p in eligible)
        eligible_status["AMBIGUOUS_TIME_MATCH"] += eligible_status["AMBIGUOUS"]
        del eligible_status["AMBIGUOUS"]
        strong=[p for p in eligible if (p.get("correlation") or {}).get("status")=="MATCHED_BY_BOTH_STRONG"]
        deltas=[float((m.get("correlation") or {})["time_difference_ms"]) for m in strong if (m.get("correlation") or {}).get("time_difference_ms") is not None]
        b200_addresses={str(p.get("address")).upper() for p in eligible if p.get("address")}; native_addresses={str(n.get("address")).upper() for n in native if n.get("address")}
        target_address=str(session.get("target_address") or "").upper(); target_native=[n for n in native if str(n.get("address","")).upper()==target_address]
        target_native_ids={n.get("native_observation_id") for n in target_native}; target_packets=[p for p in packets if str(p.get("address","")).upper()==target_address]
        target_related=[p for p in packets if (p.get("correlation") or {}).get("native_observation_id") in target_native_ids]
        unique_packets={p.get("packet_sha256") or p.get("packet_id") or id(p):p for p in packets}
        target_strong=[p for p in {id(p):p for p in target_packets+target_related}.values() if (p.get("correlation") or {}).get("status")=="MATCHED_BY_BOTH_STRONG"]
        target_payload=[p for p in target_related if (p.get("correlation") or {}).get("payload_match") and p not in target_strong]
        target_ambiguous=[p for p in {id(p):p for p in target_packets+target_related}.values() if str((p.get("correlation") or {}).get("status","")).startswith("AMBIGUOUS")]
        target_b200_packet_ids={p.get("packet_sha256") or p.get("packet_id") for p in target_packets+target_related}
        target_b200_packet_ids.discard(None)
        target_b200_crc_packets=len(target_b200_packet_ids)
        target_strong_packet_ids={p.get("packet_sha256") or p.get("packet_id") for p in target_strong}
        target_strong_packet_ids.discard(None)
        unique_target_crc_packets_with_strong_association=len(target_strong_packet_ids)
        target_ambiguous_packet_ids={p.get("packet_sha256") or p.get("packet_id") for p in target_ambiguous}
        target_ambiguous_packet_ids.discard(None)
        target_conflicting_packet_ids={p.get("packet_sha256") or p.get("packet_id") for p in target_strong if int((p.get("correlation") or {}).get("candidate_count") or 0) > 1}
        target_conflicting_packet_ids.discard(None)
        strong_only_target_packet_ids=target_strong_packet_ids-target_conflicting_packet_ids-target_ambiguous_packet_ids
        unique_strong_only_target_crc_packets=len(strong_only_target_packet_ids)
        unique_target_crc_packets_with_ambiguous_association=len(target_ambiguous_packet_ids)
        unique_target_crc_packets_with_conflicting_association=len(target_conflicting_packet_ids)
        target_association_conflict_count=unique_target_crc_packets_with_conflicting_association
        environmental_crc_packets=sum(1 for key,p in unique_packets.items() if key not in target_b200_packet_ids and p.get("address") and str(p.get("address")).upper()!=target_address)
        unattributed_crc_packets=max(0,len(packets)-target_b200_crc_packets-environmental_crc_packets)
        false_target_attributions=len(target_native)+target_b200_crc_packets
        general_ok=bool(strong); specific=session.get("target_mode")=="specific_device"
        target_status=("TARGET_MATCHED_STRONG" if target_strong else "TARGET_MATCHED_BY_PAYLOAD" if target_payload else "TARGET_NATIVE_ONLY" if target_native and not target_packets else "TARGET_B200_ONLY" if target_packets and not target_native else "TARGET_AMBIGUOUS" if target_native and target_packets else "TARGET_NOT_OBSERVED") if specific else "TARGET_NOT_EVALUATED"
        bursts=int(quality.get("burst_candidate_count",session.get("counters",{}).get("detected_bursts",0))); processed=int(batch.get("segments",0)); crc=len(packets)
        metadata=dict(session.get("experimental_metadata") or {})
        minimum_target_crc_packets=int(metadata.get("minimum_target_crc_packets") or 1)
        minimum_target_strong_matches=int(metadata.get("minimum_target_strong_matches") or 1)
        minimum_unique_target_packets_for_e4_observation=int(metadata.get("minimum_unique_target_packets_for_e4_observation") or 1)
        minimum_unique_target_packets_for_dataset_acceptance=int(metadata.get("minimum_unique_target_packets_for_dataset_acceptance") or 3)
        quality_gate_version=str(metadata.get("quality_gate_version") or "ble-rffi-positive-pilot-gate-v2")
        competing_controlled_target_detected=bool(metadata.get("competing_controlled_target_detected", False))
        overflow_count=int(capture.get("overflow_count",0) or 0)
        discontinuity_count=int(capture.get("input_discontinuities",0) or 0)
        expected_samples=int(capture.get("expected_samples") or int((capture.get("requested_duration_seconds") or 0)*(capture.get("sample_rate_sps") or 0)))
        expected_file_size=int(capture.get("expected_file_size") or capture.get("expected_size_bytes") or 0)
        actual_samples=int(capture.get("actual_samples") or 0)
        actual_file_size=int(capture.get("actual_size_bytes") or 0)
        protocol_duration=float(capture.get("protocol_duration_seconds") or metadata.get("protocol_duration_seconds") or capture.get("requested_duration_seconds") or 0)
        effective_duration=float(capture.get("effective_duration_seconds") or metadata.get("effective_duration_seconds") or capture.get("requested_duration_seconds") or 0)
        protocol_override=bool(capture.get("protocol_override", metadata.get("protocol_override", False)))
        duration_conformant=effective_duration==protocol_duration
        artifact_verified=bool(capture.get("data_sha256")) and bool(capture.get("metadata_sha256"))
        fingerprint_ok=bool(quality.get("fingerprinting_eligible")) and overflow_count==0 and discontinuity_count==0
        clean_capture=overflow_count==0 and discontinuity_count==0
        e4_minimal_observed=specific and unique_target_crc_packets_with_strong_association>=minimum_unique_target_packets_for_e4_observation
        maximum_observed_evidence_level="E4" if e4_minimal_observed else "E3" if general_ok else "E2" if crc or bool(target_native) else "E1" if bursts else "E0"
        analysis_status=str(capture.get("analysis_status") or "").lower()
        analysis_execution_status="NOT_EXECUTED" if analysis_status in {"not_requested","not_executed","analysis_not_requested"} else "EXECUTED"
        acquisition_quality_status="PASSED" if clean_capture and capture.get("capture_complete") and actual_samples==expected_samples and actual_file_size==expected_file_size else "FAILED"
        target_association_ambiguous=target_association_conflict_count>0 or unique_target_crc_packets_with_ambiguous_association>0 or competing_controlled_target_detected
        e4_dataset_accepted=(
            e4_minimal_observed
            and acquisition_quality_status=="PASSED"
            and target_status=="TARGET_MATCHED_STRONG"
            and not target_association_ambiguous
            and target_b200_crc_packets>=minimum_target_crc_packets
            and len(target_strong)>=minimum_target_strong_matches
            and unique_strong_only_target_crc_packets>=minimum_unique_target_packets_for_dataset_acceptance
        )
        effective_claim_level="E4_ACCEPTED_FOR_DATASET" if e4_dataset_accepted else "E4_MINIMAL_OBSERVED" if e4_minimal_observed else ("E2" if acquisition_quality_status!="PASSED" and (crc or bool(target_native)) else maximum_observed_evidence_level)
        final_target_status="TARGET_AMBIGUOUS" if acquisition_quality_status!="PASSED" and specific else "TARGET_AMBIGUOUS" if target_association_ambiguous and e4_minimal_observed else target_status
        association_evidence_status="ACCEPTED" if e4_dataset_accepted else "AMBIGUOUS" if target_association_ambiguous and e4_minimal_observed else "MINIMAL_OBSERVATION" if e4_minimal_observed else "CANDIDATE" if maximum_observed_evidence_level in {"E3","E4"} or target_b200_crc_packets or bool(target_native) else "NOT_OBSERVED"
        ground_truth_status="PASSED_E4" if e4_dataset_accepted else "INSUFFICIENT_FOR_ACCEPTED_E4"
        metadata_status="COMPLETE" if metadata.get("condition_id") and metadata.get("operator_session_id") and metadata.get("physical_unit_id") else "INCOMPLETE"
        protocol_conformance_status="PASSED" if duration_conformant and not protocol_override else "OVERRIDE_DECLARED"
        artifact_integrity_status="VERIFIED" if artifact_verified else "NOT_VERIFIED"
        summary_status="COMPLETE"
        source_working_tree_status=str(metadata.get("source_working_tree_status") or "UNKNOWN")
        dataset_eligibility_status="ELIGIBLE" if (
            session.get("state")=="completed"
            and acquisition_quality_status=="PASSED"
            and ground_truth_status=="PASSED_E4"
            and association_evidence_status=="ACCEPTED"
            and protocol_conformance_status=="PASSED"
            and source_working_tree_status=="CLEAN"
            and metadata_status=="COMPLETE"
            and artifact_integrity_status=="VERIFIED"
            and summary_status=="COMPLETE"
        ) else "NOT_ELIGIBLE"
        reason_codes=[]
        if overflow_count>0: reason_codes.append("ACQUISITION_OVERFLOW")
        if discontinuity_count>0: reason_codes.append("ACQUISITION_DISCONTINUITY")
        if analysis_execution_status=="NOT_EXECUTED":
            reason_codes.append("ANALYSIS_NOT_EXECUTED")
        else:
            if bursts==0: reason_codes.append("ZERO_BURST_CANDIDATES")
            if crc==0: reason_codes.append("ZERO_CRC_VALID_PACKETS")
        if final_target_status=="TARGET_AMBIGUOUS" or target_association_ambiguous:
            reason_codes.append("TARGET_ASSOCIATION_AMBIGUOUS")
        elif specific and final_target_status=="TARGET_NATIVE_ONLY":
            reason_codes.append("TARGET_NATIVE_ONLY_B200_NOT_CORROBORATED")
        elif specific and final_target_status=="TARGET_B200_ONLY":
            reason_codes.append("TARGET_B200_ONLY_WINDOWS_NOT_CORROBORATED")
        elif specific and final_target_status=="TARGET_NOT_OBSERVED":
            reason_codes.append("TARGET_NOT_OBSERVED")
        elif specific and final_target_status!="TARGET_MATCHED_STRONG":
            reason_codes.append("TARGET_ASSOCIATION_NOT_ACCEPTED")
        if e4_minimal_observed and not e4_dataset_accepted and unique_strong_only_target_crc_packets<minimum_unique_target_packets_for_dataset_acceptance: reason_codes.append("INSUFFICIENT_UNIQUE_TARGET_PACKETS")
        if not e4_dataset_accepted: reason_codes.append("EVIDENCE_BELOW_ACCEPTED_E4")
        if source_working_tree_status!="CLEAN": reason_codes.append("SOURCE_WORKING_TREE_NOT_CLEAN")
        ambiguity_reason_codes=[]
        if overflow_count>0: ambiguity_reason_codes.append("ACQUISITION_OVERFLOW")
        if discontinuity_count>0: ambiguity_reason_codes.append("ACQUISITION_DISCONTINUITY")
        if (overflow_count>0 or discontinuity_count>0) and not quality.get("loss_events"): ambiguity_reason_codes.append("LOSS_INTERVALS_NOT_AVAILABLE")
        if maximum_observed_evidence_level=="E4" and acquisition_quality_status!="PASSED": ambiguity_reason_codes.append("OBSERVED_E4_DEGRADED_BY_ACQUISITION_QUALITY")
        if final_target_status=="TARGET_AMBIGUOUS": ambiguity_reason_codes.append("TARGET_ASSOCIATION_AMBIGUOUS")
        if target_association_conflict_count>0: ambiguity_reason_codes.append("TARGET_ASSOCIATION_CONFLICT")
        if competing_controlled_target_detected: ambiguity_reason_codes.append("COMPETING_CONTROLLED_TARGET_DETECTED")
        if target_b200_crc_packets and association_evidence_status=="CANDIDATE": ambiguity_reason_codes.append("TARGET_OBSERVATIONS_CANDIDATE_NOT_ACCEPTED")
        target_ambiguous_match_count=unique_target_crc_packets_with_ambiguous_association
        if final_target_status=="TARGET_AMBIGUOUS" and target_b200_crc_packets:
            target_ambiguous_match_count=max(target_ambiguous_match_count,target_b200_crc_packets)
        best_target=min(target_strong+target_payload,key=lambda p:abs(float((p.get("correlation") or {}).get("time_difference_ms",float("inf")))),default=None)
        best_correlation=(best_target or {}).get("correlation") or {}
        match_evidence=None
        if best_target:
            iq_path=cap/"iq_bursts"/str(best_target.get("segment_file")) if cap and best_target.get("segment_file") else None
            match_evidence={"packet_id":best_target.get("packet_id") or best_target.get("burst_id"),"pdu_type":best_target.get("pdu_type_name"),"address":best_target.get("address"),"advertising_data_hex":best_target.get("advertising_data_hex"),"payload_hex":best_target.get("payload_hex") or best_target.get("payload_octets"),"crc_received":best_target.get("crc_received"),"crc_computed":best_target.get("crc_computed"),"sdr_timestamp_utc":best_target.get("timestamp_utc") or best_target.get("timestamp"),"native_observation_id":best_correlation.get("native_observation_id"),"delta_ms":best_correlation.get("time_difference_ms"),"rule":best_correlation.get("rule"),"sample_start":best_target.get("sample_start"),"sample_end":best_target.get("sample_end"),"iq_artifact":{"available":bool(best_target.get("iq_segment")),"name":best_target.get("iq_segment"),"path":best_target.get("iq_segment_path"),"sha256":best_target.get("iq_segment_sha256")},"overlap_with_overflow":False if clean_capture else None,"overlap_with_discontinuity":False if clean_capture else None,"sample_continuity_verified":clean_capture}
        artifacts={name:self._artifact(path) for name,path in {"capture_manifest":cap/"capture_manifest.json" if cap else None,"quality_report":cap/"quality_report.json" if cap else None,"decoded_packets":self._path(sid)/"correlation"/"decoded_packets.jsonl","correlation_metrics":self._path(sid)/"correlation"/"metrics.json","correlation_matches":self._path(sid)/"correlation"/"matches.jsonl","native_observations":self.native.root/"scans"/sid/"advertisements.jsonl"}.items()}
        result={"schema_version":"ble-scientific-summary-v2","session_id":sid,"question":("Â¿Puede el dispositivo seleccionado ser observado y corroborado independientemente por el B200 y el adaptador Windows?" if specific else f"Â¿Puede el B200 recuperar paquetes BLE reales con CRC vÃ¡lido en CH{session.get('channel')} y corroborarlos mediante el adaptador Windows?"),
            "general_result":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED","success_criterion":"Al menos un evento MATCHED_BY_BOTH_STRONG", "evidence_level":effective_claim_level,"maximum_observed_evidence_level":maximum_observed_evidence_level,"association_evidence_status":association_evidence_status,"effective_claim_level":effective_claim_level,
            "funnel":{"iq_samples":capture.get("actual_samples"),"analysis_execution_status":analysis_execution_status,"burst_detection_status":"NOT_EVALUATED" if analysis_execution_status=="NOT_EXECUTED" else "EVALUATED","crc_validation_status":"NOT_EVALUATED" if analysis_execution_status=="NOT_EXECUTED" else "EVALUATED","candidate_bursts":None if analysis_execution_status=="NOT_EXECUTED" else bursts,"detected_bursts":None if analysis_execution_status=="NOT_EXECUTED" else bursts,"processed_bursts":None if analysis_execution_status=="NOT_EXECUTED" else processed,"decoded_packets":None if analysis_execution_status=="NOT_EXECUTED" else len(packets),"processing_coverage_percent":None if analysis_execution_status=="NOT_EXECUTED" else round(processed*100/bursts,2) if bursts else 0,"crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else crc,"total_crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else crc,"unique_crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else len(unique_packets),"windows_target_observations":len(target_native),"target_crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else target_b200_crc_packets,"target_strong_matches":len(target_strong),"target_strong_correlation_edges":len(target_strong),"unique_target_crc_packets_with_strong_association":unique_target_crc_packets_with_strong_association,"unique_strong_only_target_crc_packets":unique_strong_only_target_crc_packets,"unique_target_crc_packets_with_ambiguous_association":unique_target_crc_packets_with_ambiguous_association,"unique_target_crc_packets_with_conflicting_association":unique_target_crc_packets_with_conflicting_association,"target_association_conflict_count":target_association_conflict_count,"competing_controlled_target_detected":competing_controlled_target_detected,"target_ambiguous_matches":target_ambiguous_match_count,"target_ambiguous_correlation_edges":target_ambiguous_match_count,"environmental_crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else environmental_crc_packets,"environmental_strong_matches":max(0,len(strong)-len(target_strong)),"environmental_matches":max(0,len(strong)-len(target_strong)),"unattributed_crc_valid_packets":None if analysis_execution_status=="NOT_EXECUTED" else unattributed_crc_packets,"crc_yield_percent":None if analysis_execution_status=="NOT_EXECUTED" else round(crc*100/processed,2) if processed else 0,"eligible_advertisements":len(eligible),"strong_matches":len(strong),"unique_correlated_devices":len({str(p.get('address')).upper() for p in packets if (p.get('correlation') or {}).get('status')=='MATCHED_BY_BOTH_STRONG' and p.get('address')})},
            "counts":{"crc_events":crc,"unique_b200_addresses":len(b200_addresses),"unique_windows_addresses":len(native_addresses),"addresses_seen_by_both":len(b200_addresses&native_addresses),"unique_payloads":len({p.get('advertising_data_hex') for p in eligible if p.get('advertising_data_hex')}),"repeated_advertisements":max(0,len(eligible)-len({(p.get('address'),p.get('advertising_data_hex')) for p in eligible}))},
            "target":{"mode":session.get("target_mode"),"device_id":session.get("target_device_id"),"address":session.get("target_address"),"name":session.get("target_name_at_start"),"selection_source":session.get("target_selection_source"),"seen_before_start":session.get("target_seen_before_start"),"seen_during_campaign":bool(target_native),"seen_by_windows":bool(target_native),"windows_callbacks":len(target_native),"windows_target_observations":len(target_native),"seen_by_b200":bool(target_packets or target_related),"b200_crc_packets":target_b200_crc_packets,"strong_matches":len(target_strong),"unique_target_crc_packets_with_strong_association":unique_target_crc_packets_with_strong_association,"unique_strong_only_target_crc_packets":unique_strong_only_target_crc_packets,"unique_target_crc_packets_with_ambiguous_association":unique_target_crc_packets_with_ambiguous_association,"unique_target_crc_packets_with_conflicting_association":unique_target_crc_packets_with_conflicting_association,"target_association_conflict_count":target_association_conflict_count,"competing_controlled_target_detected":competing_controlled_target_detected,"payload_matches":len(target_payload),"ambiguous_matches":target_ambiguous_match_count,"best_delta_ms":min((abs(float((p.get('correlation') or {}).get('time_difference_ms'))) for p in target_strong+target_payload if (p.get('correlation') or {}).get('time_difference_ms') is not None),default=None),"channel":session.get("channel"),"status":final_target_status,"observed_status":target_status,"match_evidence":match_evidence,"functional_e4_observed":maximum_observed_evidence_level=="E4","clean_e4_evidence":e4_dataset_accepted,"ambiguity_reason_codes":ambiguity_reason_codes},
            "acquisition":{"channel":capture.get("ble_channel"),"frequency_hz":capture.get("center_frequency_hz"),"requested_duration_seconds":capture.get("requested_duration_seconds"),"protocol_duration_seconds":protocol_duration,"effective_duration_seconds":effective_duration,"duration_source":capture.get("duration_source") or metadata.get("duration_source"),"protocol_override":protocol_override,"override_reason":capture.get("override_reason") or metadata.get("override_reason"),"protocol_revision":capture.get("protocol_revision") or metadata.get("protocol_revision"),"actual_duration_seconds":capture.get("actual_duration_seconds"),"duration_difference_reason":None if capture.get("requested_duration_seconds")==capture.get("actual_duration_seconds") else "La captura terminÃ³ con una duraciÃ³n distinta de la solicitada.","sample_rate_sps":capture.get("sample_rate_sps"),"bandwidth_hz":capture.get("bandwidth_hz"),"gain_db":(capture.get("gain_configuration") or {}).get("gain_db"),"antenna":capture.get("antenna"),"expected_samples":expected_samples,"captured_samples":capture.get("actual_samples"),"expected_file_size":expected_file_size,"actual_file_size":actual_file_size,"bytes":capture.get("actual_size_bytes"),"overflows":overflow_count,"discontinuities":discontinuity_count,"lost_samples":capture.get("dropped_samples"),"loss_events":quality.get("loss_events") or [],"loss_intervals_available":bool(quality.get("loss_events")),"sha256_verified":bool(capture.get("data_sha256")),"functional_validation":"suitable" if capture.get("capture_complete") and crc else "not_suitable","fingerprinting":"suitable" if fingerprint_ok else "not_suitable"},
            "decoder":{"candidate_bursts":bursts,"processed_bursts":processed,"coverage_percent":round(processed*100/bursts,2) if bursts else 0,"crc_valid":crc,"crc_invalid":max(0,processed-crc),"parser_failures":None,"unsupported_pdu_types":None,"crc_yield_percent":round(crc*100/processed,2) if processed else 0},
            "correlation":{"native_callbacks":len(native),"eligible_native":len(native),"eligible_sdr":len(eligible),"strong_matches":eligible_status["MATCHED_BY_BOTH_STRONG"],"payload_matches":eligible_status["MATCHED_BY_PAYLOAD"],"ambiguous":eligible_status["AMBIGUOUS_TIME_MATCH"],"b200_only":eligible_status["B200_ONLY"],"category_sum":sum(eligible_status.values()),"excluded_non_advertising_pdus":len(packets)-len(eligible),"native_only":len(self._jsonl(self._path(sid)/"correlation"/"unmatched_native.jsonl")),"conflicts":target_association_conflict_count,"target_association_conflict_count":target_association_conflict_count,"window_ms":session.get("result",{}).get("window_ms"),"median_delta_ms":round(statistics.median(deltas),3) if deltas else None,"p95_abs_delta_ms":round(sorted(abs(x) for x in deltas)[max(0,int(len(deltas)*.95)-1)],3) if deltas else None,"minimum_delta_ms":min(deltas) if deltas else None,"maximum_delta_ms":max(deltas) if deltas else None},
            "conclusion":{"target_specific":"DEMONSTRATED" if ground_truth_status=="PASSED_E4" else "NOT_DEMONSTRATED","statement":f"El objetivo {session.get('target_address')} fue observado por Windows y B200 y alcanzo E4 aceptado para dataset en CH{session.get('channel')}." if ground_truth_status=="PASSED_E4" else "No se demostro E4 aceptado para dataset para el objetivo seleccionado.","functional_validation":"PASSED" if ground_truth_status=="PASSED_E4" else "NOT_PASSED","reproducibility":"PENDING","fingerprinting":"NOT_SUITABLE" if not fingerprint_ok else "SUITABLE","physical_identity":"NOT_DEMONSTRATED"},
            "uc02":{"case_id":"BLE-UC-02","session_id":sid,"target_address":session.get("target_address"),"channel":session.get("channel"),"functional_result":"PASSED" if e4_dataset_accepted else "NOT_PASSED","evidence_level":effective_claim_level,"effective_claim_level":effective_claim_level,"maximum_observed_evidence_level":maximum_observed_evidence_level,"windows_callbacks":len(target_native),"target_crc_packets":len({p.get('packet_sha256') or p.get('packet_id') for p in target_packets+target_related}),"target_strong_matches":len(target_strong),"unique_target_crc_packets_with_strong_association":unique_target_crc_packets_with_strong_association,"unique_strong_only_target_crc_packets":unique_strong_only_target_crc_packets,"clean_capture":clean_capture,"reproducibility":"PENDING","fingerprinting":"NOT_VALIDATED","physical_identity":"NOT_DEMONSTRATED"},
            "terminal_status":"COMPLETED" if session.get("state")=="completed" else str(session.get("state","UNKNOWN")).upper(),
            "acquisition_quality_status":acquisition_quality_status,
            "signal_quality_status":acquisition_quality_status,
            "ground_truth_status":ground_truth_status,
            "target_result":final_target_status,
            "observed_evidence_level":maximum_observed_evidence_level,
            "maximum_observed_evidence_level":maximum_observed_evidence_level,
            "association_evidence_status":association_evidence_status,
            "effective_claim_level":effective_claim_level,
            "e4_observation_status":"E4_MINIMAL_OBSERVED" if e4_minimal_observed else "NOT_OBSERVED",
            "e4_dataset_acceptance_status":"E4_ACCEPTED_FOR_DATASET" if e4_dataset_accepted else "NOT_ACCEPTED_FOR_DATASET",
            "quality_gate_version":quality_gate_version,
            "ambiguity_reason_codes":ambiguity_reason_codes,
            "protocol_conformance_status":protocol_conformance_status,
            "metadata_status":metadata_status,
            "artifact_integrity_status":artifact_integrity_status,
            "summary_status":summary_status,
            "dataset_eligibility_status":dataset_eligibility_status,
            "final_reason_codes":reason_codes,
            "protocol":{"protocol_duration_seconds":protocol_duration,"effective_duration_seconds":effective_duration,"duration_source":capture.get("duration_source") or metadata.get("duration_source"),"protocol_override":protocol_override,"override_reason":capture.get("override_reason") or metadata.get("override_reason"),"protocol_revision":capture.get("protocol_revision") or metadata.get("protocol_revision"),"quality_gate_version":quality_gate_version,"minimum_target_crc_packets":minimum_target_crc_packets,"minimum_target_strong_matches":minimum_target_strong_matches,"minimum_unique_target_packets_for_e4_observation":minimum_unique_target_packets_for_e4_observation,"minimum_unique_target_packets_for_dataset_acceptance":minimum_unique_target_packets_for_dataset_acceptance,"source_repository_commit":metadata.get("source_repository_commit"),"source_working_tree_status":source_working_tree_status,"source_working_tree_diff_sha256":metadata.get("source_working_tree_diff_sha256"),"protocol_manifest_sha256":metadata.get("protocol_manifest_sha256"),"protocol_hash":metadata.get("protocol_hash"),"protocol_frozen_at_utc":metadata.get("protocol_frozen_at_utc"),"freeze_validation_status":metadata.get("freeze_validation_status")},
            "protocol_manifest":metadata.get("protocol_manifest") or {"protocol_revision":capture.get("protocol_revision") or metadata.get("protocol_revision"),"quality_gate_version":quality_gate_version,"minimum_unique_target_packets_for_e4_observation":minimum_unique_target_packets_for_e4_observation,"minimum_unique_target_packets_for_dataset_acceptance":minimum_unique_target_packets_for_dataset_acceptance},
            "artifacts":artifacts,"limitations":[f"SÃ³lo se evaluÃ³ CH{session.get('channel')}.","No se validÃ³ fingerprint RF.","No se demostrÃ³ cobertura completa de transmisiones.","La identidad fÃ­sica del transmisor no queda demostrada Ãºnicamente por direcciÃ³n/payload."]}
        negative_control_passed=(intent==NEGATIVE_CONTROL and contract["operator_confirmation"] and bool(contract["negative_control_type"]) and false_target_attributions==0)
        result["schema_version"]="ble-scientific-summary-v3"
        result["question"]={
            POSITIVE_TARGET_VALIDATION:"Â¿Fue el objetivo preseleccionado y visto ahora observado por Windows y B200 durante la misma campaÃ±a?",
            NEGATIVE_CONTROL:"Â¿EvitÃ³ el sistema atribuir falsamente trÃ¡fico al objetivo bajo la condiciÃ³n negativa declarada?",
            EXPLORATORY_TARGET_SEARCH:"Â¿Se obtuvo evidencia del objetivo histÃ³rico sin presuponer que estaba presente?",
        }[intent]
        result["campaign"]={
            **contract,
            "result":final_target_status,
            "observed_result":target_status,
            "maximum_evidence":maximum_observed_evidence_level,
            "observed_evidence":maximum_observed_evidence_level,
            "effective_claim_level":effective_claim_level,
            "association_evidence_status":association_evidence_status,
            "positive_claim_allowed":intent==POSITIVE_TARGET_VALIDATION,
            "negative_claim_allowed":intent==NEGATIVE_CONTROL and contract["operator_confirmation"],
        }
        negative_result="PASSED_SINGLE_RUN" if negative_control_passed else "FAILED_FALSE_ATTRIBUTION"
        if intent==NEGATIVE_CONTROL:
            negative_source={
                "target_powered_off":"OPERATOR_DECLARED_TARGET_POWERED_OFF",
                "target_physically_absent":"OPERATOR_DECLARED_TARGET_PHYSICALLY_ABSENT",
                "other_device_substituted":"OPERATOR_DECLARED_OTHER_DEVICE_SUBSTITUTED",
                "ambient_only":"OPERATOR_DECLARED_AMBIENT_ONLY",
            }.get(contract["negative_control_type"],"OPERATOR_DECLARED_NEGATIVE_CONDITION")
            result["general_result"]=negative_result
            result["success_criterion"]="Cero atribuciones al objetivo bajo la condiciÃ³n negativa predeclarada"
            result["campaign"]["negative_control_result"]=negative_result
            result["negative_control"]={
                "declared_condition":contract["negative_control_type"].upper(),
                "declared_condition_display":"objetivo apagado" if contract["negative_control_type"]=="target_powered_off" else contract["negative_control_type"].replace("_"," "),
                "ground_truth_source":negative_source,
                "operator_confirmation":contract["operator_confirmation"],
                "ambient_ble_traffic_recovered":crc>target_b200_crc_packets,
                "ambient_crc_valid_packets":max(0,crc-target_b200_crc_packets),
                "target_native_observations":len(target_native),
                "target_b200_crc_valid_packets":target_b200_crc_packets,
                "target_strong_matches":len(target_strong),
                "false_target_attributions":false_target_attributions,
                "result":negative_result,
                "basic_control":"PASSED_SINGLE_RUN" if negative_control_passed else "FAILED",
                "positive_reference_correlation":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED",
                "reinforced_control":"PASSED_SINGLE_RUN" if negative_control_passed and general_ok and clean_capture else "PENDING",
                "clean_capture":clean_capture,
                "training_ready":False,
                "fingerprinting":"NOT_VALIDATED",
                "condition_provenance":"La condiciÃ³n fÃ­sica procede de la declaraciÃ³n y confirmaciÃ³n previa del operador; no fue inferida de la ausencia de detecciÃ³n RF.",
            }
        result["functional_validation"]={
            "iq_capture":{"status":"COMPLETED" if clean_capture else "COMPLETED_WITH_LOSS","label":"ValidaciÃ³n de captura IQ","detail":("Completada sin pÃ©rdidas notificadas" if clean_capture else f"Completada con pÃ©rdidas: {capture.get('overflow_count',0)} overflows y {capture.get('input_discontinuities',0)} discontinuidades")},
            "burst_detector":{"status":"PASSED" if bursts else "NOT_DEMONSTRATED","label":"ValidaciÃ³n del detector de rÃ¡fagas","detail":f"{bursts} rÃ¡fagas detectadas"},
            "ble_decoder":{"status":"PASSED_TO_E2" if crc else "NOT_DEMONSTRATED","label":"ValidaciÃ³n del decoder BLE","detail":f"{crc} paquetes con CRC vÃ¡lido"},
            "hybrid_correlation":{"status":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED","label":"CorrelaciÃ³n hÃ­brida Windowsâ€“B200","detail":f"{len(strong)} coincidencias fuertes"},
            "target_validation":{"status":"DEMONSTRATED" if ground_truth_status=="PASSED_E4" else "NEGATIVE_CONTROL_PASSED" if negative_control_passed else "NOT_DEMONSTRATED","label":"ValidaciÃ³n del objetivo","detail":final_target_status},
            "fingerprinting":{"status":"SUITABLE" if fingerprint_ok else "NOT_SUITABLE","label":"Fingerprinting","detail":"Requiere captura limpia y validaciÃ³n multisensiÃ³n"},
        }
        if intent==NEGATIVE_CONTROL:
            result["functional_validation"]["target_validation"]["status"]="NEGATIVE_CONTROL_PASSED_SINGLE_RUN" if negative_control_passed else "FAILED_FALSE_ATTRIBUTION"
            result["functional_validation"]["negative_control_basic"]={"status":"PASSED_SINGLE_RUN" if negative_control_passed else "FAILED","label":"Control negativo bÃ¡sico","detail":f"{false_target_attributions} atribuciones falsas al objetivo"}
            result["functional_validation"]["negative_control_reinforced"]={"status":"PASSED_SINGLE_RUN" if negative_control_passed and general_ok and clean_capture else "PENDING","label":"Control negativo con referencia positiva","detail":"Requiere una coincidencia E3 de otro dispositivo y captura limpia"}
        result["acquisition"].pop("functional_validation",None)
        result["target"]["interpretation"]={
            "meaning":"No se obtuvo evidencia suficiente del objetivo durante esta campaÃ±a." if target_status=="TARGET_NOT_OBSERVED" else None,
            "does_not_mean":["El dispositivo estaba apagado.","El dispositivo no transmitiÃ³.","El dispositivo no existe en el entorno.","El B200 no puede recibirlo."] if target_status=="TARGET_NOT_OBSERVED" else [],
            "possible_causes":["objetivo apagado o ausente","duraciÃ³n insuficiente","publicidad en CH38 o CH39","intervalo de advertising","interferencia","pÃ©rdidas de adquisiciÃ³n","distancia","estado de conexiÃ³n BLE"] if target_status=="TARGET_NOT_OBSERVED" else [],
        }
        if intent==NEGATIVE_CONTROL:
            declared_state="apagado" if contract["negative_control_type"]=="target_powered_off" else result["negative_control"]["declared_condition_display"]
            statement=(f"Antes de iniciar la campaÃ±a, el operador declarÃ³ y confirmÃ³ fÃ­sicamente que el {session.get('target_name_at_start') or session.get('target_address')} estaba "
                f"{declared_state}. Durante la adquisiciÃ³n, el B200 procesÃ³ {processed} rÃ¡fagas y recuperÃ³ {crc} paquetes BLE con CRC vÃ¡lido "
                f"correspondientes al trÃ¡fico ambiental de CH{session.get('channel')}. Ninguna observaciÃ³n Windows ni ningÃºn paquete B200 fue atribuido al dispositivo objetivo. "
                "Bajo el contrato experimental declarado, el sistema no produjo una atribuciÃ³n falsa al SensorTag y el control negativo se considera superado en esta ejecuciÃ³n. "
                "La condiciÃ³n fÃ­sica procede de la declaraciÃ³n experimental del operador; no fue inferida automÃ¡ticamente a partir de la ausencia de detecciÃ³n RF.")
            result["target"]["interpretation"]={
                "meaning":"El objetivo no fue observado y el sistema registrÃ³ cero atribuciones falsas bajo el control negativo predeclarado.",
                "does_not_mean":["La ausencia RF demostrÃ³ automÃ¡ticamente que el objetivo estaba apagado.","Se conoce la identidad fÃ­sica de los transmisores ambientales."],
                "possible_causes":[],
            }
        elif ground_truth_status=="PASSED_E4":
            statement=f"El objetivo {session.get('target_address')} fue observado por Windows y B200 y alcanzÃ³ E4 en CH{session.get('channel')}."
        elif target_status=="TARGET_NOT_OBSERVED":
            statement=(f"El B200 procesÃ³ {processed} rÃ¡fagas y recuperÃ³ {crc} paquetes BLE con CRC vÃ¡lido en CH{session.get('channel')}. "
                "Ninguno pudo asociarse con una observaciÃ³n Windows dentro de la campaÃ±a, y no se obtuvo evidencia del dispositivo objetivo. "
                "Este resultado no demuestra que el objetivo estuviera ausente; Ãºnicamente indica que no fue observado bajo las condiciones y duraciÃ³n de esta ejecuciÃ³n.")
        else:
            statement="No se demostrÃ³ correlaciÃ³n E4 para el objetivo seleccionado bajo las condiciones de esta campaÃ±a."
        if target_status=="TARGET_NATIVE_ONLY":
            statement=(f"Windows observo {len(target_native)} eventos del objetivo {session.get('target_address')} durante la campana, "
                f"pero el detector B200 produjo {bursts} rafagas candidatas y el decoder recupero {crc} paquetes BLE con CRC valido en CH{session.get('channel')}. "
                "La captura I/Q fue limpia e integra, pero no hay evidencia RF decodificada suficiente para aceptar E4 ni para dataset.")
            result["target"]["interpretation"]={
                "meaning":"Windows observo el objetivo, pero el B200 no recupero paquetes BLE CRC validos atribuibles al objetivo.",
                "does_not_mean":["El objetivo quedo identificado por RF.","Existe ground truth E4.","La sesion es apta para dataset.","El fallo es necesariamente de identidad del SensorTag."],
                "possible_causes":["objetivo visible para Windows pero no para la cadena B200 en CH37","antena, orientacion, distancia o ganancia insuficientes","publicidad concentrada en CH38/CH39 durante la ventana de 10 s","umbral del detector de rafagas demasiado estricto","decoder offline no alineado con la forma de onda capturada","interferencia o SNR insuficiente sin perdida de adquisicion"],
            }
        result["conclusion"].update(
            statement=statement,
            functional_validation=result["functional_validation"]["target_validation"]["status"],
            negative_control_result=(negative_result if intent==NEGATIVE_CONTROL else "NOT_APPLICABLE"),
        )
        result["uc02"]["campaign_intent"]=intent
        result["limitations"].insert(1,"TARGET_NOT_OBSERVED no demuestra ausencia fÃ­sica del objetivo.")
        if intent==NEGATIVE_CONTROL:
            result["limitations"].insert(2,"La condiciÃ³n negativa procede de la declaraciÃ³n fÃ­sica previa del operador; no fue inferida de la ausencia RF.")
            result["limitations"].insert(3,"El control negativo bÃ¡sico fue evaluado; la referencia positiva del correlador permanece pendiente si no hubo coincidencias E3 de otro dispositivo.")
        if session.get("state")=="completed":
            persisted={"target_seen_during_campaign":bool(target_native),"target_native_callbacks":len(target_native),"scientific_summary":result,
                "acquisition_quality_status":acquisition_quality_status,"signal_quality_status":acquisition_quality_status,"ground_truth_status":ground_truth_status,"target_result":final_target_status,
                "evidence_level":effective_claim_level,"effective_claim_level":effective_claim_level,"observed_evidence_level":maximum_observed_evidence_level,"maximum_observed_evidence_level":maximum_observed_evidence_level,"association_evidence_status":association_evidence_status,"dataset_eligibility_status":dataset_eligibility_status,"final_reason_codes":reason_codes,"ambiguity_reason_codes":ambiguity_reason_codes}
            if intent==NEGATIVE_CONTROL:
                persisted.update(campaign_intent="NEGATIVE_CONTROL",negative_control_type=str(contract["negative_control_type"]).upper(),operator_confirmation=contract["operator_confirmation"],target_native_observations=len(target_native),target_b200_crc_valid_packets=target_b200_crc_packets,target_strong_matches=len(target_strong),false_target_attributions=false_target_attributions,negative_control_result=negative_result)
            self._write(sid,**persisted)
        return result
