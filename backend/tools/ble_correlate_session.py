"""Deterministic correlation of CRC-valid SDR packets and native callbacks."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

def read_jsonl(path): return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
def write_jsonl(path, rows): Path(path).write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows),encoding="utf-8")
def epoch(value): return datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
def sdr_manufacturer(packet):
    for item in packet.get("ad_structures") or []:
        if item.get("ad_type_raw")==255:
            value=item.get("decoded_value") or {}; company=value.get("company_identifier"); payload=value.get("vendor_payload_hex")
            if company is not None and payload is not None: return f"0x{company:04X}",payload.upper()
    return None,None

def main():
    p=argparse.ArgumentParser(); p.add_argument("--capture-dir",type=Path,required=True); p.add_argument("--decoded",type=Path,required=True); p.add_argument("--native",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--window-ms",type=float,default=250); a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((a.capture_dir/"capture_manifest.json").read_text()); burst_rows=read_jsonl(a.capture_dir/"burst_candidates.jsonl"); bursts={Path(x["iq_segment_path"]).name:x for x in burst_rows}; natives=read_jsonl(a.native/"advertisements.jsonl"); packets=read_jsonl(a.decoded/"decoded_packets.jsonl")
    matches=[]; unmatched=[]; used=set(); enriched=[]; start=epoch(manifest["created_at_utc"]); rate=manifest["sample_rate_sps"]
    for index,packet in enumerate(packets):
        burst=bursts.get(packet.get("iq_segment"),{}); packet_time=start+float(burst.get("sample_start",0))/rate; packet_id="sdr-"+packet["packet_sha256"][:12]+"-"+str(burst.get("burst_id","unknown")); key,payload=sdr_manufacturer(packet); candidates=[]
        for native in natives:
            if native["native_observation_id"] in used: continue
            delta=(epoch(native["timestamp_callback_utc"])-packet_time)*1000
            if abs(delta)>a.window_ms: continue
            address_match=str(native.get("address","")).upper()==str(packet.get("address","")).upper()
            native_payload=(native.get("manufacturer_data") or {}).get(key) if key else None
            payload_match=native_payload is not None and native_payload.upper()==payload
            if address_match or payload_match: candidates.append((native,delta,address_match,payload_match))
        strong=[x for x in candidates if x[2] and x[3]]; by_payload=[x for x in candidates if x[3]]
        selected=strong[0] if len(strong)==1 else by_payload[0] if len(by_payload)==1 else None
        status="MATCHED_BY_BOTH_STRONG" if selected in strong else "MATCHED_BY_BOTH_PAYLOAD" if selected else "AMBIGUOUS" if candidates else "B200_ONLY"
        rule="address_payload_time" if status.endswith("STRONG") else "payload_structure_time" if status.endswith("PAYLOAD") else "multiple_or_partial" if candidates else "no_native_candidate"
        result={"status":status,"rule":rule,"sdr_observation_id":packet_id,"native_observation_id":selected[0]["native_observation_id"] if selected else None,"address_match":selected[2] if selected else any(x[2] for x in candidates),"payload_match":selected[3] if selected else any(x[3] for x in candidates),"manufacturer_data_match":selected[3] if selected else None,"service_data_match":None,"time_difference_ms":round(selected[1],3) if selected else None,"correlation_window_ms":a.window_ms,"candidate_count":len(candidates)}
        packet.update({"timestamp":datetime.fromtimestamp(packet_time,timezone.utc).isoformat().replace("+00:00","Z"),"capture_id":manifest["capture_id"],"burst_id":burst.get("burst_id"),"sample_start":burst.get("sample_start"),"sample_end":burst.get("sample_end"),"iq_segment_path":burst.get("iq_segment_path"),"iq_segment_sha256":burst.get("iq_segment_sha256"),"correlation":result}); enriched.append(packet)
        if selected: matches.append(result); used.add(selected[0]["native_observation_id"])
        else: unmatched.append(result)
    write_jsonl(a.output/"matches.jsonl",matches); write_jsonl(a.output/"unmatched_sdr.jsonl",unmatched); write_jsonl(a.output/"unmatched_native.jsonl",[x for x in natives if x["native_observation_id"] not in used]); write_jsonl(a.output/"decoded_packets.jsonl",enriched)
    metrics={"schema_version":"ble-correlation-metrics-v1","window_ms":a.window_ms,"sdr_packets":len(packets),"native_callbacks":len(natives),"strong_matches":sum(x["status"].endswith("STRONG") for x in matches),"payload_matches":sum(x["status"].endswith("PAYLOAD") for x in matches),"ambiguous":sum(x["status"]=="AMBIGUOUS" for x in unmatched),"b200_only":sum(x["status"]=="B200_ONLY" for x in unmatched)}; (a.output/"metrics.json").write_text(json.dumps(metrics,indent=2)+"\n"); print(json.dumps(metrics))
if __name__=="__main__": main()
