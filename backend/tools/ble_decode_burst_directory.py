"""Decode pre-segmented real BLE IQ bursts with the existing Gate 2A.2 chain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ble_gate2a2_offline_worker import normalized, write_json, write_jsonl


def rows(path: Path) -> list[dict]:
    if not path.is_file(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-repository", type=Path, required=True)
    parser.add_argument("--channel", type=int, default=37)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    import sys
    sys.path.insert(0, str(args.worker_repository / "src"))
    from ble_worker.dsp_models import ReceiverConfig
    from ble_worker.dsp_receiver import run_offline_receiver
    from ble_worker.iq_reader import IqReaderConfig, read_iq_file
    confirmed_count, semantic_count, attempts = 0, 0, []
    all_segments = sorted(args.segments_dir.glob("*.cf32"))
    selected_segments = all_segments[args.start_index:args.end_index]
    decoded_packets_path = args.output_dir / "decoded_packets.jsonl"
    semantic_packets_path = args.output_dir / "semantic_packets.jsonl"
    if args.start_index == 0:
        decoded_packets_path.write_text("", encoding="utf-8")
        semantic_packets_path.write_text("", encoding="utf-8")
    write_json(args.output_dir / "progress.json", {"processed_segments": 0, "total_segments": len(selected_segments), "crc_valid_packets": 0})
    for index, segment in enumerate(selected_segments, start=1):
        iq = read_iq_file(segment, IqReaderConfig("cf32_le", 262_144))
        config = ReceiverConfig(channel_index=args.channel, minimum_burst_samples=80, maximum_burst_samples=4096)
        result = run_offline_receiver(iq.samples, config, source_iq_sha256=iq.input_iq_sha256)
        parsed = [normalized(item) for item in result.semantic_packets]
        semantic_by_id = {item.get("packet_id"): item for item in parsed}
        packets = []
        # result.candidates and result.decoded_results are built in the same
        # single loop inside run_offline_receiver() (one candidate -> one
        # decode attempt, same order, same length) -- zipping them by index
        # is how the candidate that produced each decoded result is
        # recovered here. This is the exact point where
        # RecoveredBitstreamCandidate.detector_score/estimated_cfo_hz/
        # estimated_timing_phase/refined_cfo_hz were previously computed and
        # then discarded before reaching decoded_packets.jsonl.
        for candidate, decoded in zip(result.candidates, result.decoded_results):
            frequency_fit_quality = None
            if candidate.refined_cfo_hz is not None and candidate.estimated_cfo_hz is not None:
                frequency_fit_quality = abs(candidate.refined_cfo_hz - candidate.estimated_cfo_hz)
            for packet in decoded.confirmed_packets:
                item=normalized(packet); sem=semantic_by_id.get(item.get("packet_sha256"),{})
                advertiser=(sem.get("addresses") or {}).get("advertiser") or {}; advertising=sem.get("advertising_data") or {}
                item.update({"source":"usrp_b200","frequency_hz":{37:2402000000,38:2426000000,39:2480000000}[args.channel],
                    "address":advertiser.get("address_canonical"),"address_type":advertiser.get("address_type_from_header"),
                    "advertising_data_hex":advertising.get("raw_hex"),"ad_structures":advertising.get("structures",[]),
                    "local_name":None,"power_dbfs":None,"snr_db":None,
                    "synchronization_score":candidate.detector_score,"symbol_phase":candidate.estimated_timing_phase,
                    "frequency_offset_hz":candidate.estimated_cfo_hz,"frequency_fit_quality":frequency_fit_quality})
                packets.append(item)
        for value in packets: value["iq_segment"] = segment.name
        for value in parsed: value["iq_segment"] = segment.name
        append_jsonl(decoded_packets_path, packets)
        append_jsonl(semantic_packets_path, parsed)
        confirmed_count += len(packets); semantic_count += len(parsed)
        attempts.append({"iq_segment": segment.name, "confirmed_packets": len(packets), "semantic_packets": len(parsed)})
        write_json(args.output_dir / "batch_summary.json", {"segments": index, "start_index":args.start_index,"end_index":args.end_index,
            "crc_valid_packets": confirmed_count, "semantic_packets": semantic_count, "attempts": attempts, "partial": True})
        write_json(args.output_dir / "progress.json", {"processed_segments": index, "total_segments": len(selected_segments),
            "crc_valid_packets": confirmed_count, "current_segment": segment.name})
    write_json(args.output_dir / "batch_summary.json", {"segments": len(attempts), "start_index":args.start_index,"end_index":args.end_index,
        "crc_valid_packets": confirmed_count, "semantic_packets": semantic_count, "attempts": attempts, "partial": False})
    print(json.dumps({"segments": len(attempts), "crc_valid_packets": confirmed_count}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
