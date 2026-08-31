"""Parallel drop-in replacement for ble_decode_burst_directory.py.

Each burst segment is decoded fully independently (run_offline_receiver
takes only that segment's own IQ samples and a fresh ReceiverConfig -- no
state carries over between segments), so decoding them across a process
pool changes nothing about the result, only how long it takes. Output order
and file contents are identical to the sequential script: results are
written in original segment order as they become available, not in
whatever order workers happen to finish.

Same CLI as the sequential script, so BleOfflineReplayService can call this
one instead with no other change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def rows(path: Path) -> list[dict]:
    if not path.is_file(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


_WORKER_REPOSITORY: Path | None = None
_CHANNEL: int | None = None


def _init_worker(worker_repository: str, channel: int) -> None:
    global _WORKER_REPOSITORY, _CHANNEL
    _WORKER_REPOSITORY = Path(worker_repository)
    _CHANNEL = channel
    sys.path.insert(0, str(_WORKER_REPOSITORY / "src"))


def _decode_one(segment_path_str: str) -> tuple[str, list[dict], list[dict]]:
    # Imported inside the worker (and only once, via _init_worker's sys.path
    # setup) since each ProcessPoolExecutor worker is a separate interpreter.
    from ble_gate2a2_offline_worker import normalized
    from ble_worker.dsp_models import ReceiverConfig
    from ble_worker.dsp_receiver import run_offline_receiver
    from ble_worker.iq_reader import IqReaderConfig, read_iq_file

    segment = Path(segment_path_str)
    iq = read_iq_file(segment, IqReaderConfig("cf32_le", 262_144))
    config = ReceiverConfig(channel_index=_CHANNEL, minimum_burst_samples=80, maximum_burst_samples=4096)
    result = run_offline_receiver(iq.samples, config, source_iq_sha256=iq.input_iq_sha256)
    parsed = [normalized(item) for item in result.semantic_packets]
    semantic_by_id = {item.get("packet_id"): item for item in parsed}
    packets = []
    for decoded in result.decoded_results:
        for packet in decoded.confirmed_packets:
            item = normalized(packet)
            sem = semantic_by_id.get(item.get("packet_sha256"), {})
            advertiser = (sem.get("addresses") or {}).get("advertiser") or {}
            advertising = sem.get("advertising_data") or {}
            item.update({
                "source": "usrp_b200", "frequency_hz": {37: 2402000000, 38: 2426000000, 39: 2480000000}[_CHANNEL],
                "address": advertiser.get("address_canonical"), "address_type": advertiser.get("address_type_from_header"),
                "advertising_data_hex": advertising.get("raw_hex"), "ad_structures": advertising.get("structures", []),
                "local_name": None, "power_dbfs": None, "snr_db": None,
            })
            packets.append(item)
    for value in packets: value["iq_segment"] = segment.name
    for value in parsed: value["iq_segment"] = segment.name
    return segment.name, packets, parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-repository", type=Path, required=True)
    parser.add_argument("--channel", type=int, default=37)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("BLE_RFFI_DECODE_WORKERS", str(min(os.cpu_count() or 4, 8)))))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    confirmed_count, semantic_count, attempts = 0, 0, []
    all_segments = sorted(args.segments_dir.glob("*.cf32"))
    selected_segments = all_segments[args.start_index:args.end_index]
    decoded_packets_path = args.output_dir / "decoded_packets.jsonl"
    semantic_packets_path = args.output_dir / "semantic_packets.jsonl"
    if args.start_index == 0:
        decoded_packets_path.write_text("", encoding="utf-8")
        semantic_packets_path.write_text("", encoding="utf-8")
    write_json(args.output_dir / "progress.json", {"processed_segments": 0, "total_segments": len(selected_segments), "crc_valid_packets": 0})

    if not selected_segments:
        write_json(args.output_dir / "batch_summary.json", {"segments": 0, "start_index": args.start_index, "end_index": args.end_index,
            "crc_valid_packets": 0, "semantic_packets": 0, "attempts": [], "partial": False})
        print(json.dumps({"segments": 0, "crc_valid_packets": 0}))
        return 0

    workers = max(1, min(args.workers, len(selected_segments)))
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(str(args.worker_repository), args.channel)) as pool:
        # map() yields results in the SAME order as the input, regardless of
        # which worker finishes first or when -- output files end up
        # byte-identical to the sequential script's ordering.
        for index, (segment_name, packets, parsed) in enumerate(pool.map(_decode_one, [str(s) for s in selected_segments]), start=1):
            append_jsonl(decoded_packets_path, packets)
            append_jsonl(semantic_packets_path, parsed)
            confirmed_count += len(packets); semantic_count += len(parsed)
            attempts.append({"iq_segment": segment_name, "confirmed_packets": len(packets), "semantic_packets": len(parsed)})
            write_json(args.output_dir / "batch_summary.json", {"segments": index, "start_index": args.start_index, "end_index": args.end_index,
                "crc_valid_packets": confirmed_count, "semantic_packets": semantic_count, "attempts": attempts, "partial": True})
            write_json(args.output_dir / "progress.json", {"processed_segments": index, "total_segments": len(selected_segments),
                "crc_valid_packets": confirmed_count, "current_segment": segment_name})

    write_json(args.output_dir / "batch_summary.json", {"segments": len(attempts), "start_index": args.start_index, "end_index": args.end_index,
        "crc_valid_packets": confirmed_count, "semantic_packets": semantic_count, "attempts": attempts, "partial": False})
    print(json.dumps({"segments": len(attempts), "crc_valid_packets": confirmed_count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
